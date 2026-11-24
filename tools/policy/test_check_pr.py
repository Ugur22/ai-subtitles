import importlib.util
import json
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


RISK = """## Risk
- Impact: local config could load differently
- Verification: test_settings_sources.py and make check
- Rollback: revert and redeploy
- Reversibility: code-only
- Uncertainty: real backend/.env not exercised
"""
REVIEW = "## Review\n- R1 [should-fix] fixed: b07ac76 adds behaviour tests\n"


def af(name, patch="", changes=1, status="modified"):
    return {"filename": name, "status": status, "patch": patch, "changes": changes}


def test_agent_sensitive_pr_needs_title_risk_and_review():
    files = [af("backend/config.py")]
    found = cp.risk_violations(files, AGENT, "Load settings", "## Summary\nx")
    text = "\n".join(found)
    assert "[sensitive]" in text and "## Risk section is missing" in text and "## Review section is missing" in text
    assert all(v.startswith("risk sensitive (config and secrets loading") for v in found)
    assert cp.risk_violations(files, AGENT, "[sensitive] Load settings", RISK + REVIEW) == []


def test_sensitive_content_from_the_patch_counts():
    files = [af("backend/routers/video.py", patch='@@ -1 +1,2 @@\n+@router.get("/api/new")\n def x():')]
    assert any("[sensitive]" in v for v in cp.risk_violations(files, AGENT, "x", REVIEW))


def test_review_tier_needs_dispositions_not_none_run():
    files = [af("backend/main.py")]
    assert cp.risk_violations(files, AGENT, "x", "## Review\nnone run (Ordinary change)\n")
    assert cp.risk_violations(files, AGENT, "x", "## Review\nNo findings.\n") == []
    bad = "## Review\n- R1 [blocker] deferred: will do it later in another PR\n"
    assert any("can't be deferred" in v for v in cp.risk_violations(files, AGENT, "x", bad))


def test_ordinary_agent_pr_and_owner_pr_are_not_burdened():
    assert cp.risk_violations([af("frontend/src/utils/time.ts")], AGENT, "x", "") == []
    assert cp.risk_violations([af("backend/config.py")], OWNER, "x", "") == []
    malformed = "## Review\n- R1 (nit): no change needed\n"
    assert cp.risk_violations([af("frontend/src/utils/time.ts")], AGENT, "x", malformed)


def test_main_reads_pr_json_and_puts_fixable_violations_first(tmp_path, capsys):
    files = tmp_path / "files.jsonl"
    files.write_text(json.dumps(af("backend/config.py")) + "\n")
    reviews = tmp_path / "reviews.json"
    reviews.write_text("[]")
    pr = tmp_path / "pr.json"
    pr.write_text(json.dumps({"title": "x", "body": None}))
    assert cp.main(str(files), str(reviews), AGENT, HEAD, str(pr)) == 1
    lines = capsys.readouterr().out.splitlines()
    assert lines[0].startswith("risk sensitive") and "approving review" in lines[-2]
