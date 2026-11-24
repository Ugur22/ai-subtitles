#!/usr/bin/env python3
"""Trusted static PR policy. Runs from main's revision (.github/workflows/policy.yml) and reads the PR only as
data: the files API list and the reviews API list. Stdlib only; never imports or executes anything from the PR.

Usage: check_pr.py <files.jsonl> <reviews.json> <author-login> <head-sha> [<pr.json>]
Exit 1 with one line per violation.

Agent PRs are also judged by risk (tools/harness/risk.py, from main like this file): review and sensitive changes
need a well-formed ## Review section (a disposition per finding, no deferred blocker), sensitive ones also
[sensitive] in the title and a complete ## Risk section. This checks the form of what the owner will read,
not that a review really happened; the owner's approval of the exact commit stays the decision.
"""

import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", "harness"))
import prbody  # noqa: E402
import risk  # noqa: E402

OWNER = "Ugur22"
MIGRATIONS = "backend/sql/migrations/"
# Paths that decide whether a change is acceptable, or how the agent is confined: only the owner changes them.
GUARD = re.compile(
    r"^(\.github/|tools/policy/|tools/agent-container/|tools/harness/|bin/agent$|scripts/hooks/|scripts/githooks/|\.claude/|"
    r"skills/|\.agents/|infra/|Makefile$|CLAUDE\.md$|AGENTS\.md$|skills-lock\.json$|pytest\.ini$|"
    r"backend/ruff\.toml$|frontend/eslint\.config\.js$|frontend/tsconfig[^/]*\.json$|frontend/vite\.config\.ts$|"
    r"frontend/package\.json$|backend/evals/[^/]*cases[^/]*\.json$)"
)
TEST = re.compile(r"^backend/tests/.*\.py$|\.test\.tsx?$")


def file_violations(files, author):
    out = []
    added = {f["filename"] for f in files if f["status"] == "added"}
    for f in files:
        name, status, old = f["filename"], f["status"], f.get("previous_filename", "")
        if (name.startswith(MIGRATIONS) or old.startswith(MIGRATIONS)) and status != "added":
            out.append(f"{old or name}: applied migrations are immutable ({status}); add a new numbered migration")
        if name in added and name.startswith(MIGRATIONS) and name.endswith(".sql") and not name.endswith("_rollback.sql"):
            if name[:-4] + "_rollback.sql" not in added:
                out.append(f"{name}: needs {name[:-4]}_rollback.sql in the same PR")
        if author != OWNER and (GUARD.match(name) or GUARD.match(old)):
            out.append(f"{name}: guard path; only {OWNER} may change it")
        if author != OWNER and TEST.search(old or name) and status in ("removed", "renamed"):
            out.append(f"{old or name}: test {status}; only {OWNER} may remove tests")
    return out


def approval_violations(reviews, author, head_sha):
    """A PR by anyone but the owner needs the owner's approval of the exact head commit; any later push
    produces a new head SHA, so the approval no longer counts."""
    if author == OWNER:
        return []
    latest = None
    for r in reviews:  # API order is chronological
        if (r.get("user") or {}).get("login") == OWNER and r.get("state") in ("APPROVED", "CHANGES_REQUESTED", "DISMISSED"):
            latest = r
    if latest is None or latest["state"] != "APPROVED":
        return [f"needs an approving review from {OWNER}"]
    if latest.get("commit_id") != head_sha:
        return [f"{OWNER}'s approval is for {latest.get('commit_id', '?')[:12]}, not the head {head_sha[:12]}; re-review"]
    return []


_STATUS = {"added": "A", "modified": "M", "removed": "D", "renamed": "R", "copied": "A", "changed": "M"}


def risk_files(files):
    """The files API entries in risk.classify_files() form; added lines come from the patch when GitHub sends one."""
    out = []
    for f in files:
        patch = f.get("patch") or ""
        out.append({"path": f["filename"], "old": f.get("previous_filename", ""),
                    "status": _STATUS.get(f.get("status"), "M"), "changes": f.get("changes", 0),
                    "added": [ln[1:] for ln in patch.splitlines() if ln.startswith("+") and not ln.startswith("+++")]})
    return out


def risk_violations(files, author, title, body):
    if author == OWNER:
        return []
    res = risk.classify_files(risk_files(files))
    tier, out = res["tier"], []
    if tier == risk.ORDINARY:
        if prbody.section(body, "Review") is not None:
            out += [p for p in prbody.dispositions(body)[1] if "No findings" not in p]
    else:
        out += prbody.dispositions(body)[1]
        if tier == risk.SENSITIVE:
            if "[sensitive]" not in (title or "").lower():
                out.append("the title must start with [sensitive]")
            out += prbody.risk_problems(body)
    why = "; ".join(res["reasons"][:3])
    return [f"risk {tier} ({why}): {p}" for p in out]


def main(files_path, reviews_path, author, head_sha, pr_path=None):
    files = [json.loads(line) for line in open(files_path) if line.strip()]
    reviews = json.load(open(reviews_path))
    pr = json.load(open(pr_path)) if pr_path else {}
    # Approval last: the first line becomes the status description, and it should name what the agent can fix.
    found = (file_violations(files, author) + risk_violations(files, author, pr.get("title", ""), pr.get("body") or "")
             + approval_violations(reviews, author, head_sha))
    for v in found:
        print(v)
    print(f"policy: author={author} head={head_sha[:12]} files={len(files)} violations={len(found)}")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:6]))
