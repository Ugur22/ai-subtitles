import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("check_pr", Path(__file__).with_name("check_pr.py"))
cp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cp)

AGENT, OWNER, HEAD = "ai-subs-agent[bot]", cp.OWNER, "a" * 40


def f(name, status="modified", old=None):
    d = {"filename": name, "status": status}
    if old:
        d["previous_filename"] = old
    return d


def review(state, commit=HEAD, user=OWNER):
    return {"user": {"login": user}, "state": state, "commit_id": commit}


def test_app_change_by_agent_passes_file_rules():
    assert cp.file_violations([f("backend/services/jobs.py"), f("frontend/src/App.tsx", "added")], AGENT) == []


def test_agent_cannot_change_any_guard_path():
    for p in [".github/workflows/check.yml", "tools/policy/check_pr.py", "tools/agent-container/agent-checks.sh",
              "bin/agent", "tools/harness/stop_check.py", "Makefile", "CLAUDE.md", "pytest.ini", "frontend/tsconfig.app.json", "frontend/package.json",
              ".claude/settings.json", "backend/evals/chat_cases.json", "infra/scripts/deploy_image.sh",
              "infra/terraform/iam.tf", "scripts/githooks/pre-commit"]:
        assert cp.file_violations([f(p)], AGENT), p
    assert cp.file_violations([f("ok.txt", "renamed", old=".github/workflows/deploy.yml")], AGENT)


def test_owner_may_change_guard_paths():
    assert cp.file_violations([f(".github/workflows/check.yml"), f("bin/agent")], OWNER) == []


def test_applied_migration_immutable_for_everyone():
    for status in ("modified", "removed", "renamed"):
        assert cp.file_violations([f("backend/sql/migrations/024_job_dedup_by_model.sql", status)], OWNER)


def test_new_migration_needs_rollback():
    m = "backend/sql/migrations/025_x.sql"
    assert cp.file_violations([f(m, "added")], AGENT)
    assert cp.file_violations([f(m, "added"), f("backend/sql/migrations/025_x_rollback.sql", "added")], AGENT) == []


def test_agent_cannot_remove_tests():
    assert cp.file_violations([f("backend/tests/test_job_security.py", "removed")], AGENT)
    assert cp.file_violations([f("frontend/src/a.test.tsx", "renamed", old="frontend/src/b.test.tsx")], AGENT)
    assert cp.file_violations([f("backend/tests/test_job_security.py", "modified")], AGENT) == []


def test_agent_pr_needs_owner_approval_on_exact_head():
    assert cp.approval_violations([], AGENT, HEAD)
    assert cp.approval_violations([review("APPROVED")], AGENT, HEAD) == []
    assert cp.approval_violations([review("APPROVED", commit="b" * 40)], AGENT, HEAD), "stale approval must not count"
    assert cp.approval_violations([review("APPROVED"), review("CHANGES_REQUESTED")], AGENT, HEAD)
    assert cp.approval_violations([review("APPROVED"), review("DISMISSED")], AGENT, HEAD)
    assert cp.approval_violations([review("APPROVED", user=AGENT)], AGENT, HEAD), "self-approval must not count"
    assert cp.approval_violations([review("APPROVED"), review("COMMENTED")], AGENT, HEAD) == []


def test_owner_pr_needs_no_review():
    assert cp.approval_violations([], OWNER, HEAD) == []


def test_main_reports_and_exits(tmp_path, capsys):
    files = tmp_path / "files.jsonl"
    files.write_text('{"filename": "Makefile", "status": "modified"}\n')
    reviews = tmp_path / "reviews.json"
    reviews.write_text("[]")
    assert cp.main(str(files), str(reviews), AGENT, HEAD) == 1
    out = capsys.readouterr().out
    assert "guard path" in out and "approving review" in out
