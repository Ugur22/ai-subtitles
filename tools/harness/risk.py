"""Deterministic risk classification of a change: ordinary, review or sensitive, with the reasons.

The tier comes from what the diff touches, not from the agent's opinion of it: sensitive paths, sensitive content
in added lines, core modules, architectural scope and, as one signal among several, size. An agent may escalate
the tier (`escalate`), never lower it. The same classify_files() judges a PR in the trusted policy check (from
the files API) and a working tree in the container (from git), so both layers agree on what is sensitive.

CLI (inside the agent container: `ai-risk ...`):
  plan PATH...                 tier and required steps for the files you intend to touch (path signals only)
  status                       tier of the branch against origin/main, and what is still required
  escalate review|sensitive --reason TEXT
"""

import argparse
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import ledger  # noqa: E402

ORDINARY, REVIEW, SENSITIVE = "ordinary", "review", "sensitive"
RANK = {ORDINARY: 0, REVIEW: 1, SENSITIVE: 2}
SIZE_LIMIT = 300  # changed lines outside tests and lockfiles

SENSITIVE_PATHS = [
    (re.compile(r"^backend/middleware/auth\.py$"), "auth"),
    (re.compile(r"^backend/services/transcription_access\.py$"), "access control"),
    (re.compile(r"^backend/(sql|migrations)/"), "SQL and migrations"),
    (re.compile(r"^backend/services/(job_queue_service|job_dispatcher|background_worker)\.py$"), "job queue and GPU slot"),
    (re.compile(r"^backend/worker_main\.py$"), "worker"),
    (re.compile(r"^backend/routers/billing\.py$|^backend/services/[^/]*(billing|stripe)[^/]*\.py$"), "billing"),
    (re.compile(r"^backend/(services/(encryption|key_validator)|routers/keys)\.py$"), "API keys and encryption"),
    (re.compile(r"^backend/(config|dependencies)\.py$"), "config and secrets loading"),
    (re.compile(r"^infra/"), "infra"),
]
SENSITIVE_CONTENT = [
    (re.compile(r"^\s*@(router|app)\.(get|post|put|patch|delete|api_route)\("), "backend/", "route added or changed (auth)"),
    (re.compile(r"\.table\(|supabase_service\.|get_supabase|supabase\(\)"), "backend/routers/",
     "direct Supabase query in a router (ownership)"),
    (re.compile(r"\bDELETE\s+FROM\b|\bDROP\s+(TABLE|COLUMN|FUNCTION|INDEX)\b|\bTRUNCATE\b|\.delete\(\)", re.I), "backend/",
     "deletes or drops stored data"),
    (re.compile(r"\bload_dotenv\b|os\.environ\[|os\.environ\.(setdefault|update)\b"), "backend/", "environment loading"),
]
CORE = {
    "backend/main.py", "backend/services/supabase_service.py", "frontend/src/services/api.ts", "frontend/src/config.ts",
    "frontend/src/App.tsx",
}
TEST = re.compile(r"^backend/tests/|\.test\.tsx?$|^tools/[^/]+/test_[^/]*\.py$")
LOCK = re.compile(r"(^|/)(package-lock\.json|[^/]*\.lock|constraints\.txt)$")
DOCS = re.compile(r"\.(md|txt)$|^docs/")


def area(path):
    if TEST.search(path) or DOCS.search(path) or LOCK.search(path):
        return None
    parts = path.split("/")
    if parts[0] == "backend":
        return "backend/" + parts[1] if len(parts) > 2 and parts[1] in ("routers", "services") else "backend/core"
    if parts[0] == "frontend":
        return "frontend/" + parts[2] if len(parts) > 3 and parts[1] == "src" else "frontend/build"
    return parts[0]


def classify_files(files):
    """files: [{path, status (A/M/D/R), added: [added lines], changes: int, old: previous path or ''}].
    Returns {tier, reasons, sensitive, lines, areas, new_code_files}."""
    by_path, by_content, review, areas, lines, new_code = [], [], [], set(), 0, []
    for f in files:
        paths = [p for p in (f.get("path"), f.get("old")) if p]
        for p in paths:
            for rx, why in SENSITIVE_PATHS:
                if rx.search(p) and f"{why}: {p}" not in by_path:
                    by_path.append(f"{why}: {p}")
        path = f["path"]
        if TEST.search(path):
            continue
        for rx, prefix, why in SENSITIVE_CONTENT:
            if path.startswith(prefix) and not path.startswith("backend/tests/"):
                if any(rx.search(line) for line in f.get("added") or []) and f"{why}: {path}" not in by_content:
                    by_content.append(f"{why}: {path}")
        if path in CORE:
            review.append(f"core module: {path}")
        a = area(path)
        if a:
            areas.add(a)
        if not LOCK.search(path):
            lines += int(f.get("changes") or 0)
        if f.get("status") == "A" and a and not DOCS.search(path):
            new_code.append(path)
    has_back = any(a.startswith("backend") for a in areas)
    has_front = any(a.startswith("frontend") for a in areas)
    if has_back and has_front:
        review.append("spans backend and frontend")
    elif len(areas) >= 3:
        review.append(f"spans {len(areas)} areas: {', '.join(sorted(areas))}")
    if lines > SIZE_LIMIT:
        review.append(f"{lines} changed lines outside tests and lockfiles (limit {SIZE_LIMIT})")
    sensitive = by_path + by_content
    tier = SENSITIVE if sensitive else REVIEW if review else ORDINARY
    return {"tier": tier, "reasons": sensitive + review, "sensitive": sensitive, "sensitive_paths": by_path,
            "sensitive_content": by_content, "lines": lines, "areas": sorted(areas), "new_code_files": new_code}


# --- git side ---------------------------------------------------------------------------------------------------

def _run(root, *args, env=None):
    r = subprocess.run(["git", "-C", root, *args], capture_output=True, timeout=120, env=env)
    return r.stdout.decode("utf-8", "replace") if r.returncode == 0 else None


snapshot_tree = ledger.snapshot_tree


def merge_base(root):
    for ref in ("origin/main", "main"):
        mb = _run(root, "merge-base", "HEAD", ref)
        if mb:
            return mb.strip()
    return _run(root, "rev-parse", "HEAD").strip()


def diff_files(root, base, target):
    """classify_files input for the change from base (commit or tree) to target (tree)."""
    status = _run(root, "diff", "--name-status", "-M", base, target) or ""
    numstat = _run(root, "diff", "--numstat", "-M", base, target) or ""
    patch = _run(root, "diff", "-U0", "--no-color", "-M", base, target) or ""
    files, changes, added = [], {}, {}
    for line in numstat.splitlines():
        parts = line.split("\t")
        if len(parts) >= 3:
            a, d, name = parts[0], parts[1], parts[-1]
            if " => " in name:
                name = re.sub(r"\{[^}]* => ([^}]*)\}", r"\1", name).split(" => ")[-1].replace("//", "/")
            changes[name] = (int(a) if a.isdigit() else 0) + (int(d) if d.isdigit() else 0)
    current = None
    for line in patch.splitlines():
        if line.startswith("+++ "):
            current = line[6:] if line.startswith("+++ b/") else None
        elif current and line.startswith("+") and not line.startswith("+++"):
            added.setdefault(current, []).append(line[1:])
    for line in status.splitlines():
        parts = line.split("\t")
        code = parts[0][:1]
        if code == "R" and len(parts) >= 3:
            files.append({"path": parts[2], "old": parts[1], "status": "R"})
        elif len(parts) >= 2:
            files.append({"path": parts[1], "old": "", "status": code})
    for f in files:
        f["changes"] = changes.get(f["path"], 0)
        f["added"] = added.get(f["path"], [])
    return files


def classify_branch(root, tree=None):
    tree = tree or snapshot_tree(root)
    if not tree:
        return {"tier": ORDINARY, "reasons": ["could not read the working tree"], "sensitive": [],
                "sensitive_paths": [], "sensitive_content": [], "lines": 0, "areas": [], "new_code_files": []}, None
    return classify_files(diff_files(root, merge_base(root), tree)), tree


def classify_delta(root, reviewed_tree, tree):
    return classify_files(diff_files(root, reviewed_tree, tree))


def escalated_tier(events, branch):
    tier = ORDINARY
    for e in events:
        if e.get("event") == "risk_escalation" and e.get("branch") == branch and e.get("tier") in RANK:
            tier = max(tier, e["tier"], key=RANK.get)
    return tier


def effective(det_tier, events, branch):
    return max(det_tier, escalated_tier(events, branch), key=RANK.get)


def required_steps(tier):
    if tier == SENSITIVE:
        return ["consult `advisor` on the plan before implementing it",
                "have `reviewer` review the finished diff (the PR gate and the Stop hook check this)",
                "PR title starts with [sensitive]; description has ## Risk and ## Review (see CLAUDE.md)",
                "open the PR with `gh pr create --body-file <file>`"]
    if tier == REVIEW:
        return ["have `reviewer` review the finished diff (the PR gate and the Stop hook check this)",
                "description has ## Review with a disposition per finding; open it with --body-file <file>"]
    return ["no review required; `make check` green is enough"]


def main(argv=None):
    ap = argparse.ArgumentParser(prog="ai-risk")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("plan")
    p.add_argument("paths", nargs="+")
    sub.add_parser("status")
    e = sub.add_parser("escalate")
    e.add_argument("tier", choices=[REVIEW, SENSITIVE])
    e.add_argument("--reason", required=True)
    a = ap.parse_args(argv)
    root = ledger.repo_root(".")
    if not root:
        print("not inside a git repository", file=sys.stderr)
        return 2
    branch = ledger._git(root, "rev-parse", "--abbrev-ref", "HEAD")
    events = _events(root)
    if a.cmd == "escalate":
        ok = ledger.append(ledger.ledger_path(root), {**ledger.base_fields({}, root), "event": "risk_escalation",
                                                      "tier": a.tier, "reason": ledger.sanitize(a.reason)})
        print(f"risk escalated to {a.tier} for {branch}" + ("" if ok else " (WARNING: ledger write failed)"))
        return 0
    if a.cmd == "plan":
        rel = [os.path.relpath(os.path.abspath(p), root) for p in a.paths]
        res = classify_files([{"path": p, "status": "M" if os.path.exists(os.path.join(root, p)) else "A",
                               "added": [], "changes": 0} for p in rel])
    else:
        res, _ = classify_branch(root)
    tier = effective(res["tier"], events, branch)
    print(f"risk: {tier}" + (f" (escalated from {res['tier']})" if tier != res["tier"] else ""))
    for r in res["reasons"]:
        print(f"  - {r}")
    if a.cmd == "plan":
        print("  (path signals only; the diff can still raise the tier: added routes, Supabase queries in routers, "
              "deletions, environment loading, size, scope)")
    print("required:")
    for s in required_steps(tier):
        print(f"  - {s}")
    if a.cmd == "status":
        import gate
        req = gate.requirements(root, session="")
        for m in req["missing"]:
            print(f"still missing: {m}")
    return 0


def _events(root):
    path = ledger.ledger_path(root)
    out = []
    try:
        import json
        with open(path, errors="replace") as f:
            for line in f:
                try:
                    e = json.loads(line)
                    if isinstance(e, dict):
                        out.append(e)
                except ValueError:
                    pass
    except OSError:
        pass
    return out


if __name__ == "__main__":
    sys.exit(main())
