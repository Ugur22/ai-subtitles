"""Deterministic risk classification of a change: ordinary, review or sensitive, with the reasons.

Pure rules over a list of changed files (stdlib `re` only, no git, no I/O), so the trusted policy check
(tools/policy/check_pr.py, from the files API) and the container's gates (gate.py, from git) judge with the same
code. The tier comes from what the diff touches, not from the agent's opinion of it: sensitive paths, sensitive
content in added lines, core modules, architectural scope and, as one signal among several, size. An agent may
escalate the tier (`ai-risk escalate`), never lower it.
"""

import re

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
    # Locked once merged (add-only for agents), so a wrong one gives lasting false assurance: advisor first.
    (re.compile(r"^backend/tests/invariants/"), "protected invariant tests"),
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
    Returns {tier, reasons, sensitive_paths, sensitive_content, lines, new_code_files}."""
    by_path, by_content, review, areas, lines, new_code = [], [], [], set(), 0, []
    for f in files:
        for p in (f.get("path"), f.get("old")):
            for rx, why in SENSITIVE_PATHS:
                if p and rx.search(p) and f"{why}: {p}" not in by_path:
                    by_path.append(f"{why}: {p}")
        path = f["path"]
        if TEST.search(path):
            continue
        for rx, prefix, why in SENSITIVE_CONTENT:
            if path.startswith(prefix) and any(rx.search(line) for line in f.get("added") or []) \
                    and f"{why}: {path}" not in by_content:
                by_content.append(f"{why}: {path}")
        if path in CORE:
            review.append(f"core module: {path}")
        a = area(path)
        if a:
            areas.add(a)
        if not LOCK.search(path):
            lines += int(f.get("changes") or 0)
        if f.get("status") == "A" and a:
            new_code.append(path)
    has_back = any(a.startswith("backend") for a in areas)
    has_front = any(a.startswith("frontend") for a in areas)
    if has_back and has_front:
        review.append("spans backend and frontend")
    elif len(areas) >= 3:
        review.append(f"spans {len(areas)} areas: {', '.join(sorted(areas))}")
    if lines > SIZE_LIMIT:
        review.append(f"{lines} changed lines outside tests and lockfiles (limit {SIZE_LIMIT})")
    tier = SENSITIVE if by_path or by_content else REVIEW if review else ORDINARY
    return {"tier": tier, "reasons": by_path + by_content + review, "sensitive_paths": by_path,
            "sensitive_content": by_content, "lines": lines, "new_code_files": new_code}


def effective(det_tier, events, branch):
    """The deterministic tier raised by any escalation logged on the branch; nothing lowers it."""
    tiers = [det_tier] + [e["tier"] for e in events if e.get("event") == "risk_escalation"
                          and e.get("branch") == branch and e.get("tier") in RANK]
    return max(tiers, key=RANK.get)


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
