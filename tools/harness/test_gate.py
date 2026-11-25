import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import gate  # noqa: E402
import ledger  # noqa: E402
import prbody  # noqa: E402
import risk  # noqa: E402


def f(path, status="M", added=(), changes=1, old=""):
    return {"path": path, "status": status, "added": list(added), "changes": changes, "old": old}


# --- classification -----------------------------------------------------------------------------------------

def test_ordinary_small_change():
    assert risk.classify_files([f("frontend/src/utils/time.ts", changes=12)])["tier"] == "ordinary"


def test_sensitive_paths_and_content_raise_the_tier_without_size():
    for path in ("backend/config.py", "backend/middleware/auth.py", "backend/sql/migrations/025_x.sql",
                 "backend/services/job_queue_service.py", "backend/routers/billing.py", "infra/terraform/iam.tf",
                 "backend/services/encryption.py", "backend/tests/invariants/test_ownership.py"):
        assert risk.classify_files([f(path)])["tier"] == "sensitive", path
    content = [
        ("backend/routers/video.py", '@router.get("/api/x")'),
        ("backend/routers/jobs.py", "rows = supabase_service.client.table('jobs').select('*')"),
        ("backend/services/media_storage.py", "client.table('x').delete().eq('id', i)"),
        ("backend/llm_providers.py", "load_dotenv()"),
    ]
    for path, line in content:
        res = risk.classify_files([f(path, added=[line])])
        assert res["tier"] == "sensitive" and res["sensitive_content"], path


def test_review_tier_from_scope_core_and_size_but_not_tests_or_locks():
    assert risk.classify_files([f("backend/main.py")])["tier"] == "review"
    assert "spans backend and frontend" in risk.classify_files(
        [f("backend/services/chat/pipeline.py"), f("frontend/src/hooks/useJobs.ts")])["reasons"]
    three = [f("frontend/src/hooks/a.ts"), f("frontend/src/utils/b.ts"), f("frontend/src/components/c.tsx")]
    assert risk.classify_files(three)["tier"] == "review"
    assert risk.classify_files([f("frontend/src/utils/a.ts", changes=301)])["tier"] == "review"
    assert risk.classify_files([f("frontend/src/utils/a.test.ts", changes=900),
                                f("frontend/package-lock.json", changes=5000)])["tier"] == "ordinary"
    assert risk.classify_files([f("backend/tests/test_x.py", added=["load_dotenv()"])])["tier"] == "ordinary"


def test_escalation_raises_but_never_lowers():
    up = [{"event": "risk_escalation", "branch": "b", "tier": "sensitive"}]
    assert risk.effective("ordinary", up, "b") == "sensitive"
    assert risk.effective("ordinary", up, "other") == "ordinary"
    assert risk.effective("sensitive", [{"event": "risk_escalation", "branch": "b", "tier": "ordinary"}], "b") == \
        "sensitive"


# --- PR description ------------------------------------------------------------------------------------------

RISK = """## Risk
- Impact: config values could load differently for local runs
- Verification: test_settings_sources.py; make check
- Rollback: revert the commit and redeploy
- Reversibility: code-only (no stored data changes)
- Uncertainty: real backend/.env not exercised
"""


def test_risk_section():
    assert prbody.risk_problems(RISK) == []
    assert prbody.risk_problems("## Summary\nx") == ["## Risk section is missing"]
    bad = RISK.replace("- Uncertainty: real backend/.env not exercised\n", "").replace("code-only", "easy")
    probs = prbody.risk_problems(bad)
    assert any("Uncertainty" in p for p in probs) and any("Reversibility must start" in p for p in probs)


def test_dispositions_strict_form():
    body = ("## Review\n- R1 [should-fix] fixed: b07ac76 adds test_settings_sources.py\n"
            "- R2 [should-fix] rejected: checked origin/main, same parsing\n"
            "- **R3** [nit] deferred: follow-up issue for dotenv loading\n\n## Testing\n")
    found, probs = prbody.dispositions(body)
    assert probs == [] and set(found) == {"R1", "R2", "R3"}
    _, probs = prbody.dispositions("## Review\n- R3 (nit): no change needed\n")
    assert "not in the required form" in probs[0]
    _, probs = prbody.dispositions("## Review\n- R1 [blocker] deferred: later, tracked in a follow-up\n")
    assert any("can't be deferred" in p for p in probs)
    _, probs = prbody.dispositions("## Review\n- R1 [should-fix] rejected:\n")
    assert any("justification" in p for p in probs)
    assert prbody.dispositions("## Review\nNo findings.\n") == ({}, [])
    assert "list every finding" in prbody.dispositions("## Review\nnone run\n")[1][0]


# --- git fixture -----------------------------------------------------------------------------------------------

class Repo(type(Path())):
    """A path that also carries the fixture's helpers."""


@pytest.fixture
def repo(tmp_path, monkeypatch):
    r = Repo(tmp_path / "repo")
    (r / "backend" / "tests").mkdir(parents=True)
    (r / "frontend" / "src" / "utils").mkdir(parents=True)
    (r / "backend" / "config.py").write_text("A = 1\n")
    (r / "frontend" / "src" / "utils" / "time.ts").write_text("export const a = 1;\n")
    (r / "Makefile").write_text("check:\n\t@true\n")
    env = {"GIT_CONFIG_GLOBAL": "/dev/null", "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t", "AI_SUBS_LEDGER": str(tmp_path / "ledger.jsonl"),
           "AI_SUBS_REVIEW_GATE": "1"}
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    g = lambda *a: subprocess.run(["git", "-C", str(r), *a], check=True, capture_output=True)  # noqa: E731
    g("init", "-q", "-b", "main")
    g("add", ".")
    g("commit", "-qm", "init")
    g("update-ref", "refs/remotes/origin/main", "HEAD")
    g("switch", "-qc", "agent/x")
    r.git = g
    r.env = dict(os.environ)
    r.ledger_file = tmp_path / "ledger.jsonl"
    return r


def subagent(repo, agent, text):
    ledger.handle({"hook_event_name": "SubagentStop", "cwd": str(repo), "session_id": "s", "agent_type": agent,
                   "last_assistant_message": text})


def pre(repo, command):
    return gate.pr_gate({"hook_event_name": "PreToolUse", "tool_name": "Bash", "cwd": str(repo), "session_id": "s",
                         "tool_input": {"command": command}})


def write_body(repo, text, name="pr.md"):
    (repo / name).write_text(text)
    return name


def test_ordinary_change_passes_without_review(repo):
    (repo / "frontend/src/utils/time.ts").write_text("export const a = 2;\n")
    assert gate.requirements(str(repo))["missing"] == []
    assert pre(repo, 'gh pr create --title "Fix time" --body "small"') is None


def test_sensitive_change_needs_advisor_reviewer_dispositions_and_risk(repo):
    (repo / "backend/config.py").write_text("A = 2\n")
    reason = pre(repo, 'gh pr create --title "Config" --body "x"')
    assert "reviewer: no `reviewer` run" in reason and "advisor:" in reason and "--body-file" in reason
    subagent(repo, "advisor", "A1 [nit][config:env-loading] backend/config.py:1 - keep the defaults\n")
    subagent(repo, "reviewer", "R1 [should-fix][tests:no-behavior-test] backend/config.py:1 - no test\n"
                               "R2 [nit][size] x - fine\n")
    name = write_body(repo, "## Review\n- R2 [nit] rejected: size is fine for this change\n")
    reason = pre(repo, f'gh pr create --title "Config" --body-file {name}')
    assert "R1 [should-fix]" in reason and "has no disposition" in reason
    assert "## Risk section is missing" in reason and "[sensitive]" in reason
    assert "advisor:" not in reason and "reviewer:" not in reason
    name = write_body(repo, RISK + "\n## Review\n- R1 [should-fix] fixed: added test_config.py for defaults\n"
                            "- R2 [nit] rejected: size is fine for this change\n")
    assert pre(repo, f'gh pr create --title "[sensitive] Config" --body-file {name}') is None


def test_test_only_fix_after_review_needs_no_rereview_but_a_large_change_does(repo):
    (repo / "backend/config.py").write_text("A = 2\n")
    subagent(repo, "advisor", "No findings.\n")
    subagent(repo, "reviewer", "R1 [should-fix][tests:no-behavior-test] backend/config.py:1 - no test\n")
    (repo / "backend/tests/test_config.py").write_text("def test_a():\n    assert True\n" * 50)
    assert gate.requirements(str(repo))["missing"] == []
    repo.git("add", "-A")
    repo.git("commit", "-qm", "fix")
    assert gate.requirements(str(repo))["missing"] == [], "committing reviewed work is not a change"
    (repo / "backend/services").mkdir()
    (repo / "backend/services/new_module.py").write_text("X = 1\n" * 90)
    missing = gate.requirements(str(repo))["missing"]
    assert len(missing) == 1 and "re-review" in missing[0] and "from R2" in missing[0] and "round 2 of 3" in missing[0]


def test_review_rounds_are_bounded_and_end_as_not_ready(repo, monkeypatch):
    (repo / "backend/config.py").write_text("A = 2\n")
    subagent(repo, "advisor", "No findings.\n")
    for i in range(3):
        (repo / f"backend/m{i}.py").write_text("X = 1\n" * 100)
        subagent(repo, "reviewer", f"R{i + 1} [nit][size] backend/m{i}.py:1 - long\n")
    (repo / "backend/m9.py").write_text("X = 1\n" * 100)
    req = gate.requirements(str(repo))
    assert req["limit_reached"] and req["missing"] == []
    name = write_body(repo, RISK + "\n## Review\nNo findings.\n")
    reason = pre(repo, f'gh pr create --title "[sensitive] x" --body-file {name}')
    assert "review rounds are used up" in reason and "--draft" in reason
    name = write_body(repo, "NOT READY: m9.py is unreviewed\n\n" + RISK + "\n## Review\nNo findings.\n", "pr2.md")
    assert pre(repo, f'gh pr create --draft --title "[sensitive] x" --body-file {name}') is None
    monkeypatch.setattr(gate, "pr_view", lambda root, fields: {"title": "[sensitive] x", "body": RISK + "\n## Review\nNo findings.\n"})
    assert "stays a draft" in pre(repo, "gh pr ready 5")


def test_ready_is_gated_and_undo_is_not(repo, monkeypatch):
    (repo / "backend/config.py").write_text("A = 2\n")
    monkeypatch.setattr(gate, "pr_view", lambda root, fields: {"title": "x", "body": ""})
    assert "reviewer:" in pre(repo, "gh pr ready 7")
    assert pre(repo, "gh pr ready 7 --undo") is None
    assert pre(repo, "gh pr edit 7 --add-label x") is None


def test_unparsable_command_must_use_body_file(repo):
    (repo / "backend/config.py").write_text("A = 2\n")
    reason = pre(repo, "gh pr create --title x --body \"$(cat <<'EOF'\nbody\nEOF\n)\"")
    assert "--body-file" in reason
    action, opts = gate.parse_gh("cd /w && gh pr create -t 'a b' -F pr.md && echo done")
    assert action == "create" and opts["title"] == "a b" and opts["body_file"] == "pr.md"


def test_reassess_tells_the_agent_once_per_rise(repo):
    payload = {"hook_event_name": "PostToolUse", "tool_name": "Edit", "cwd": str(repo), "session_id": "s"}
    assert gate.reassess(payload) is None
    (repo / "frontend/src/utils/b.ts").write_text("x\n")
    (repo / "frontend/src/hooks").mkdir()
    (repo / "frontend/src/hooks/c.ts").write_text("x\n")
    (repo / "frontend/src/components").mkdir()
    (repo / "frontend/src/components/d.tsx").write_text("x\n")
    assert "REVIEW" in gate.reassess(payload)
    assert gate.reassess(payload) is None
    (repo / "backend/config.py").write_text("A = 3\n")
    msg = gate.reassess(payload)
    assert "SENSITIVE" in msg and "advisor" in msg
    assert gate.reassess(payload) is None
    events = [json.loads(x) for x in repo.ledger_file.read_text().splitlines()]
    assert [e["tier"] for e in events if e["event"] == "risk"] == ["review", "sensitive"]


def stop(repo, last=""):
    payload = {"hook_event_name": "Stop", "session_id": "s", "cwd": str(repo), "last_assistant_message": last}
    r = subprocess.run([sys.executable, "-I", str(HERE / "stop_check.py")], input=json.dumps(payload),
                       capture_output=True, text=True, env=repo.env)
    return r.returncode, r.stdout, r.stderr


def test_stop_is_the_bounded_fallback(repo):
    (repo / "backend/config.py").write_text("A = 2\n")
    codes = [stop(repo) for _ in range(3)]
    assert [c[0] for c in codes] == [2, 2, 2] and "review block 1/3" in codes[0][2] and "advisor:" in codes[0][2]
    code, _, err = stop(repo, last="done")
    assert code == 2 and "must start with `NOT READY:`" in err
    code, out, _ = stop(repo, last="done")
    assert code == 0 and "NOT ready to merge" in json.loads(out)["systemMessage"]
    gates = [json.loads(x) for x in repo.ledger_file.read_text().splitlines()]
    assert [g["decision"] for g in gates if g["event"] == "gate"] == ["block", "block", "block", "status-demanded",
                                                                       "giveup"]


def test_stop_passes_once_requirements_hold(repo):
    (repo / "backend/config.py").write_text("A = 2\n")
    assert stop(repo)[0] == 2
    subagent(repo, "advisor", "No findings.\n")
    subagent(repo, "reviewer", "No findings.\n")
    assert stop(repo)[0] == 0


def test_gate_is_off_without_the_container_flag(repo, monkeypatch):
    (repo / "backend/config.py").write_text("A = 2\n")
    env = dict(repo.env)
    env.pop("AI_SUBS_REVIEW_GATE")
    payload = {"hook_event_name": "Stop", "session_id": "s", "cwd": str(repo)}
    r = subprocess.run([sys.executable, "-I", str(HERE / "stop_check.py")], input=json.dumps(payload),
                       capture_output=True, text=True, env=env)
    assert r.returncode == 0


def run_hook(repo, payload):
    r = subprocess.run([sys.executable, "-I", str(HERE / "gate.py")], input=json.dumps(payload), capture_output=True,
                       text=True, env=repo.env)
    return r.returncode, r.stdout, r.stderr


def test_hook_protocol_deny_and_context(repo):
    (repo / "backend/config.py").write_text("A = 2\n")
    base = {"cwd": str(repo), "session_id": "s", "tool_name": "Bash"}
    code, out, err = run_hook(repo, {**base, "hook_event_name": "PreToolUse",
                                     "tool_input": {"command": "gh pr create --title x --body-file pr.md"}})
    d = json.loads(out)["hookSpecificOutput"]
    assert code == 0 and err == "" and d["permissionDecision"] == "deny" and "reviewer" in d["permissionDecisionReason"]
    code, out, _ = run_hook(repo, {**base, "hook_event_name": "PreToolUse", "tool_input": {"command": "ls -la"}})
    assert code == 0 and out == ""
    code, out, _ = run_hook(repo, {**base, "hook_event_name": "PostToolUse", "tool_input": {"command": "make check"},
                                   "tool_response": {"stdout": "exit=0"}})
    ctx = json.loads(out)["hookSpecificOutput"]
    assert ctx["hookEventName"] == "PostToolUse" and "SENSITIVE" in ctx["additionalContext"]
    events = [json.loads(x)["event"] for x in repo.ledger_file.read_text().splitlines()]
    assert events == ["gate", "selfcheck", "risk"]


def test_reassess_skips_work_when_the_tree_is_unchanged(repo, monkeypatch):
    payload = {"hook_event_name": "PostToolUse", "tool_name": "Bash", "cwd": str(repo), "session_id": "s"}
    gate.reassess(payload)
    calls = []
    monkeypatch.setattr(gate, "diff_files", lambda *a: calls.append(a) or [])
    assert gate.reassess(payload) is None and calls == [], "no reclassification without a change"


def test_cli_plan_status_escalate(repo, monkeypatch, capsys):
    monkeypatch.chdir(repo)
    assert gate.cli(["plan", "backend/config.py"]) == 0
    assert "risk: sensitive" in capsys.readouterr().out
    (repo / "frontend/src/utils/time.ts").write_text("export const a = 3;\n")
    gate.cli(["status"])
    assert "risk: ordinary" in capsys.readouterr().out
    gate.cli(["escalate", "review", "--reason", "touches the upload flow"])
    gate.cli(["status"])
    out = capsys.readouterr().out
    assert "risk: review (escalated from ordinary)" in out and "still missing: reviewer" in out


def test_diff_files_counts_and_added_lines(repo):
    (repo / "backend/config.py").write_text("A = 1\nB = 2\n+++ not a header\n")
    (repo / "frontend/src/utils/time.ts").unlink()
    files = {f["path"]: f for f in gate.diff_files(str(repo), gate.merge_base(str(repo)), ledger.snapshot_tree(str(repo)))}
    assert files["backend/config.py"]["changes"] == 2 and files["backend/config.py"]["added"] == ["B = 2", "+++ not a header"]
    assert files["frontend/src/utils/time.ts"] == {"path": "frontend/src/utils/time.ts", "old": "", "status": "D",
                                                   "changes": 1, "added": []}


def test_pr_commands_must_run_from_the_sessions_checkout(repo, tmp_path):
    """Seen in the Phase C run: `cd <worktree> && gh pr create` was judged on the main checkout's reviews."""
    wt = tmp_path / "wt"
    repo.git("worktree", "add", "-q", "-b", "agent/other", str(wt))
    reason = pre(repo, f'cd {wt} && gh pr create --title x --body-file pr.md')
    assert "this session's checkout" in reason and "no worktrees" in reason
    assert "this session's checkout" in pre(repo, f'cd "{wt}" && gh pr edit 3 --body-file pr.md')
    assert pre(repo, 'cd backend && gh pr create --title "Fix" --body small') is None, "a subdirectory is fine"
    assert "--head agent/other is not the checked-out branch" in pre(repo, "gh pr create -H agent/other -t x -b y")
    assert pre(repo, "gh pr create --head agent/x --title x --body y") is None
    assert pre(repo, "gh pr create --head Ugur22:agent/x --title x --body y") is None
    events = [json.loads(x) for x in repo.ledger_file.read_text().splitlines()]
    assert [e["decision"] for e in events if e["event"] == "gate"] == ["deny", "deny", "deny"]


def work(repo, tool, **tool_input):
    return gate.work_gate({"hook_event_name": "PreToolUse", "tool_name": tool, "cwd": str(repo), "session_id": "s",
                           "tool_input": tool_input})


def test_worktree_add_is_refused_but_list_and_remove_are_not(repo):
    """Seen twice (PR #84 and #101): the agent built in a second worktree the gate and the ledger don't watch."""
    for cmd in ("git worktree add -b agent/y ../wt", "cd /w && git -C /work/ai-subtitles worktree add ../wt main",
                "git -c core.x=1 worktree   add ../wt", "/usr/bin/git worktree add ../wt",
                "git --work-tree /w worktree add ../wt", 'git -C "dir with space" worktree add ../wt',
                "cd /w\ngit worktree add ../wt", "FOO=1 env git worktree add ../wt"):
        assert "No `git worktree add`" in work(repo, "Bash", command=cmd), cmd
    for cmd in ("git worktree list", "git worktree remove ../wt", "git log --grep 'git worktree add'",
                "ls worktree", 'echo "then git worktree add"',
                "cat > pr.md <<'EOF'\nRun git worktree add, then\ngit commit\nEOF\ngh pr view"):
        assert work(repo, "Bash", command=cmd) is None, cmd


def test_git_subcommands_parse_command_positions_only():
    assert gate.git_subcommands("git -C /w --git-dir /w/.git commit -m 'a; b' && git push") == [
        ("commit", ["-m", "a; b"]), ("push", [])]
    assert gate.git_subcommands("git commit-tree x | git commit-graph write") == [
        ("commit-tree", ["x"]), ("commit-graph", ["write"])]
    assert gate.git_subcommands("echo 'unbalanced") == []


def test_sensitive_work_waits_for_advisor_before_edits_and_commits(repo):
    """Seen in #101: the whole implementation was committed before advisor saw the plan."""
    assert work(repo, "Bash", command="git commit -qm wip") is None, "ordinary branch"
    (repo / "backend/config.py").write_text("A = 2\n")
    assert "no `advisor` run on agent/x" in work(repo, "Bash", command="git add -A && git commit -m impl")
    assert "no `advisor` run" in work(repo, "Bash", command="git -C . commit --amend --no-edit")
    for cmd in ("/usr/bin/git commit -m x", "git cherry-pick abc", "git rebase --continue", "git merge main"):
        assert "no `advisor` run" in work(repo, "Bash", command=cmd), cmd
    assert work(repo, "Bash", command="git commit-graph write") is None
    target = str(repo / "backend/config.py")
    assert work(repo, "Edit", file_path=target) is None, "until the session's tier marker says sensitive"
    gate.reassess({"hook_event_name": "PostToolUse", "tool_name": "Edit", "cwd": str(repo), "session_id": "s"})
    assert "Edits on this branch are refused" in work(repo, "Edit", file_path=target)
    assert "no `advisor` run" in work(repo, "Write", file_path="backend/new.py")
    assert "no `advisor` run" in work(repo, "MultiEdit", file_path=target)
    assert "no `advisor` run" in work(repo, "NotebookEdit", notebook_path="backend/n.ipynb")
    assert work(repo, "Write", file_path="../outside.md") is None, "a relative path out of the checkout"
    assert work(repo, "Write", file_path="/tmp/pr.md") is None, "files outside the checkout, e.g. a PR description"
    assert work(repo, "Bash", command="make check") is None
    subagent(repo, "advisor", "No findings.\n")
    assert work(repo, "Edit", file_path=target) is None
    assert work(repo, "Bash", command="git commit -m impl") is None
    events = [json.loads(x) for x in repo.ledger_file.read_text().splitlines()]
    assert [(e["point"], e["decision"]) for e in events if e["event"] == "gate"] == [("commit", "deny")] * 6 + [
        ("edit", "deny")] * 4


def test_the_tier_marker_follows_the_branch(repo):
    (repo / "backend/config.py").write_text("A = 2\n")
    gate.reassess({"hook_event_name": "PostToolUse", "tool_name": "Edit", "cwd": str(repo), "session_id": "s"})
    assert "no `advisor` run" in work(repo, "Edit", file_path="backend/config.py")
    repo.git("stash", "-q")
    repo.git("switch", "-qc", "agent/clean")
    assert gate.session_tier(str(repo), {"session_id": "s"}) == risk.ORDINARY
    assert work(repo, "Edit", file_path="backend/config.py") is None


def test_hook_denies_edits_through_the_protocol(repo):
    (repo / "backend/config.py").write_text("A = 2\n")
    gate.reassess({"hook_event_name": "PostToolUse", "tool_name": "Edit", "cwd": str(repo), "session_id": "s"})
    code, out, _ = run_hook(repo, {"hook_event_name": "PreToolUse", "tool_name": "Edit", "cwd": str(repo),
                                   "session_id": "s", "tool_input": {"file_path": str(repo / "backend/config.py")}})
    d = json.loads(out)["hookSpecificOutput"]
    assert code == 0 and d["permissionDecision"] == "deny" and "advisor" in d["permissionDecisionReason"]
