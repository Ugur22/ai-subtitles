#!/usr/bin/env python3
"""Trusted static PR policy. Runs from main's revision (.github/workflows/policy.yml) and reads the PR only as
data: the files API list and the reviews API list. Stdlib only; never imports or executes anything from the PR.

Usage: check_pr.py <files.jsonl> <reviews.json> <author-login> <head-sha>
Exit 1 with one line per violation.
"""

import json
import re
import sys

OWNER = "Ugur22"
MIGRATIONS = "backend/sql/migrations/"
# Paths that decide whether a change is acceptable, or how the agent is confined: only the owner changes them.
GUARD = re.compile(
    r"^(\.github/|tools/policy/|tools/agent-container/|bin/agent$|scripts/hooks/|scripts/githooks/|\.claude/|"
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


def main(files_path, reviews_path, author, head_sha):
    files = [json.loads(line) for line in open(files_path) if line.strip()]
    reviews = json.load(open(reviews_path))
    found = file_violations(files, author) + approval_violations(reviews, author, head_sha)
    for v in found:
        print(v)
    print(f"policy: author={author} head={head_sha[:12]} files={len(files)} violations={len(found)}")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:5]))
