"""Regression tests for the trust boundary in .github/workflows: the required "policy" status can only come
from policy.yml, policy.yml runs only main's code, and no workflow that runs PR code can write statuses or
checks. Agents can't edit workflows (the GitHub App has no workflows permission); these catch owner mistakes."""

import re
from pathlib import Path

import yaml

WF = Path(__file__).resolve().parents[2] / ".github/workflows"
POLICY = "policy.yml"


def load(name):
    d = yaml.safe_load((WF / name).read_text())
    d["on"] = d.pop(True, d.get("on"))  # PyYAML reads the bare key `on` as True
    return d


def workflows():
    return sorted(p.name for p in WF.glob("*.yml"))


def write_scopes(d):
    scopes = []
    for perms in [d.get("permissions")] + [j.get("permissions") for j in d["jobs"].values()]:
        if perms == "write-all":
            scopes.append("write-all")
        elif isinstance(perms, dict):
            scopes += [k for k, v in perms.items() if v == "write"]
    return scopes


def test_only_policy_workflow_can_write_statuses_or_checks():
    for name in workflows():
        scopes = write_scopes(load(name))
        assert "write-all" not in scopes, name
        if name != POLICY:
            assert not {"statuses", "checks"} & set(scopes), name


def test_every_workflow_declares_top_level_permissions():
    for name in workflows():
        assert isinstance(load(name).get("permissions"), dict), f"{name} relies on default token permissions"


def test_nothing_else_produces_a_policy_context():
    for name in workflows():
        text = (WF / name).read_text()
        d = load(name)
        assert "policy" not in d["jobs"], f"{name}: a job named policy would shadow the required status"
        assert all(j.get("name") != "policy" for j in d["jobs"].values()), name
        if name != POLICY:
            assert "context=policy" not in text and "/statuses/" not in text, name


def test_policy_workflow_runs_only_trusted_code():
    d = load(POLICY)
    assert set(d["on"]) == {"pull_request_target", "pull_request_review"}
    (job,) = d["jobs"].values()
    checkout = [s for s in job["steps"] if str(s.get("uses", "")).startswith("actions/checkout")]
    assert len(checkout) == 1
    assert checkout[0]["with"]["ref"] == "${{ github.event.pull_request.base.repo.default_branch }}"
    assert checkout[0]["with"]["persist-credentials"] is False
    runs = "\n".join(s.get("run", "") for s in job["steps"])
    assert "github.event" not in runs, "event data must reach run: only through env"
    for forbidden in (r"\bnpm\b", r"\bpip\b", r"\bmake\b", r"\bbash\s+\S", r"\./", r"\bsource\b", r"actions/setup-"):
        assert not re.search(forbidden, runs + str(job["steps"])), forbidden
    assert "python3 -I tools/policy/check_pr.py" in runs


def test_untrusted_pr_workflows_get_read_only_tokens():
    for name in workflows():
        d = load(name)
        if name != POLICY and set(d["on"]) & {"pull_request", "pull_request_target", "pull_request_review"}:
            assert write_scopes(d) == [], name
