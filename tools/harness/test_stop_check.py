import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
STOP = HERE / "stop_check.py"

MAKEFILE = "check: lint-frontend\n\nlint-frontend:\n\t@sh ./checker.sh\n"
# Pass or fail on demand; counts its runs; can edit a tracked file mid-run to simulate a concurrent edit.
CHECKER = """count="$CTRL.count"; echo $(( $(cat "$count" 2>/dev/null || echo 0) + 1 )) > "$count"
[ -n "${MUTATE:-}" ] && echo changed >> tracked.txt
[ "$(cat "$CTRL")" = pass ] && { echo "All good"; exit 0; }
echo "/w/src/a.ts"; echo "  3:1  error  'x' is defined but never used  @typescript-eslint/no-unused-vars"; exit 1
"""


def git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


@pytest.fixture
def env(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "Makefile").write_text(MAKEFILE)
    (repo / "checker.sh").write_text(CHECKER)
    (repo / "tracked.txt").write_text("v1\n")
    (repo / ".gitignore").write_text("ignored/\n")
    e = dict(os.environ, GIT_CONFIG_GLOBAL="/dev/null", GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
             GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t", CTRL=str(tmp_path / "ctrl"),
             AI_SUBS_LEDGER=str(tmp_path / "ledger" / "ledger.jsonl"))
    e.pop("AI_SUBS_DRAFT_ON_GIVEUP", None)
    git(repo, "init", "-q", "-b", "main")
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True, env=e)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "init"], check=True, env=e)
    (tmp_path / "ctrl").write_text("pass")

    class Env:
        path = tmp_path
        root = repo
        vars = e

        def result(self, value):
            (tmp_path / "ctrl").write_text(value)

        def runs(self):
            p = tmp_path / "ctrl.count"
            return int(p.read_text()) if p.exists() else 0

        def stop(self, session="s1", last="", **extra_env):
            payload = {"hook_event_name": "Stop", "session_id": session, "cwd": str(repo),
                       "last_assistant_message": last}
            r = subprocess.run([sys.executable, "-I", str(STOP)], input=json.dumps(payload), capture_output=True,
                               text=True, env=dict(e, **extra_env))
            return r.returncode, r.stdout, r.stderr

        def ledger(self):
            p = Path(e["AI_SUBS_LEDGER"])
            return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []

        def outcomes(self):
            return [x["outcome"] for x in self.ledger() if x["event"] == "check"]

        def commit(self, msg="c"):
            subprocess.run(["git", "-C", str(repo), "commit", "-qam", msg], check=True, env=e)

    return Env()


def test_green_is_stamped_and_unchanged_state_skips(env):
    assert env.stop()[0] == 0 and env.runs() == 1
    assert env.stop()[0] == 0 and env.runs() == 1
    assert env.outcomes() == ["pass"]


def test_committed_work_is_checked(env):
    """The gap both container runs showed: everything committed, so `git status` was clean and the check skipped."""
    env.stop()
    (env.root / "tracked.txt").write_text("v2\n")
    env.commit()
    env.result("fail")
    code, _, err = env.stop()
    assert code == 2 and env.runs() == 2 and "lint-frontend:@typescript-eslint/no-unused-vars" in err


def test_state_covers_deletions_untracked_and_staged_but_not_ignored(env):
    env.stop()
    runs = 1
    for change in (lambda: (env.root / "tracked.txt").unlink(),
                   lambda: (env.root / "new.txt").write_text("a"),
                   lambda: (env.root / "new.txt").write_text("b"),
                   lambda: git(env.root, "add", "-A")):
        change()
        env.stop()
        runs += 1
        assert env.runs() == runs
    (env.root / "ignored").mkdir()
    (env.root / "ignored" / "x").write_text("x")
    env.stop()
    assert env.runs() == runs


def test_three_blocks_then_status_demand_then_giveup_never_reports_success(env):
    env.result("fail")
    (env.root / "tracked.txt").write_text("v2\n")
    msgs = [env.stop() for _ in range(3)]
    assert [m[0] for m in msgs] == [2, 2, 2]
    assert "block 1/3" in msgs[0][2] and "advisor" in msgs[1][2] and "NOT READY" in msgs[2][2]
    code, out, err = env.stop(last="I could not fix it.")
    assert code == 2 and "must start with `NOT READY:`" in err and out == ""
    code, out, _ = env.stop(last="Still trying")
    msg = json.loads(out)["systemMessage"]
    assert code == 0 and "NOT done" in msg and "must not be merged" in msg
    assert env.outcomes() == ["block", "block", "block", "status-demanded", "giveup"]
    assert env.ledger()[-1]["status_given"] is False


def test_status_given_goes_straight_to_giveup(env):
    env.result("fail")
    (env.root / "tracked.txt").write_text("v2\n")
    for _ in range(3):
        env.stop()
    code, out, _ = env.stop(last="NOT READY: lint still fails (no-unused-vars); tried X and Y; advisor consulted.")
    assert code == 0 and "NOT done" in json.loads(out)["systemMessage"]
    assert env.outcomes()[-1] == "giveup" and env.ledger()[-1]["status_given"] is True


def test_fix_after_block_is_a_recovery(env):
    env.result("fail")
    (env.root / "tracked.txt").write_text("v2\n")
    assert env.stop()[0] == 2
    env.result("pass")
    (env.root / "tracked.txt").write_text("v3\n")
    assert env.stop()[0] == 0
    assert env.outcomes() == ["block", "recovered"] and env.ledger()[-1]["n"] == 1


def test_back_to_known_green_state_recovers_without_rerun(env):
    env.stop()
    env.result("fail")
    (env.root / "tracked.txt").write_text("broken\n")
    assert env.stop()[0] == 2
    (env.root / "tracked.txt").write_text("v1\n")
    runs = env.runs()
    assert env.stop()[0] == 0 and env.runs() == runs
    assert env.ledger()[-1]["via"] == "known-green-state"


def test_sessions_have_separate_counters(env):
    env.result("fail")
    (env.root / "tracked.txt").write_text("v2\n")
    for _ in range(3):
        env.stop("s1")
    assert "block 1/3" in env.stop("s2")[2]


def test_edit_during_check_is_not_stamped_green(env):
    (env.root / "tracked.txt").write_text("v2\n")
    assert env.stop(MUTATE="1")[0] == 0
    assert not list(env.root.glob(".git/ai-subs-harness/green")) or \
        (env.root / ".git/ai-subs-harness/green").read_text() != ""
    runs = env.runs()
    env.stop()
    assert env.runs() == runs + 1


def test_ledger_failure_never_changes_the_decision_and_is_recorded(env, tmp_path):
    bad = tmp_path / "ledger-is-a-dir"
    bad.mkdir()
    env.result("fail")
    (env.root / "tracked.txt").write_text("v2\n")
    code, _, err = env.stop(AI_SUBS_LEDGER=str(bad))
    assert code == 2 and "block 1/3" in err
    assert "IsADirectoryError" in (tmp_path / "ledger-is-a-dir.errors").read_text()


def test_draft_on_giveup_in_the_container(env, tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "gh").write_text(
        '#!/bin/sh\necho "$@" >> "$GH_LOG"\n'
        'case "$*" in "pr view"*) echo \'{"number":7,"isDraft":false,"state":"OPEN"}\';; esac\n')
    (bin_dir / "gh").chmod(0o755)
    extra = {"PATH": f"{bin_dir}:{os.environ['PATH']}", "GH_LOG": str(tmp_path / "gh.log"),
             "AI_SUBS_DRAFT_ON_GIVEUP": "1"}
    env.result("fail")
    (env.root / "tracked.txt").write_text("v2\n")
    for _ in range(3):
        env.stop(**extra)
    code, out, _ = env.stop(last="NOT READY: still red", **extra)
    assert code == 0 and "converted to a draft" in json.loads(out)["systemMessage"]
    assert "pr ready 7 --undo" in (tmp_path / "gh.log").read_text()
    assert env.ledger()[-1]["pr"] == "drafted"


def test_known_limitation_forged_stamp_skips_the_check(env):
    """Documents why the stamp is not trusted state: the agent runs as the same user and can write it.
    CI and the policy check, not this hook, are the merge gate."""
    sys.path.insert(0, str(HERE))
    import ledger
    (env.root / "tracked.txt").write_text("unchecked\n")
    sd = env.root / ".git" / "ai-subs-harness"
    sd.mkdir(exist_ok=True)
    (sd / "green").write_text(ledger.state_hash(str(env.root)))
    env.result("fail")
    assert env.stop()[0] == 0 and env.runs() == 0


def test_repo_without_check_target_is_ignored(env):
    (env.root / "Makefile").write_text("build:\n\ttrue\n")
    assert env.stop() == (0, "", "") and env.ledger() == []
