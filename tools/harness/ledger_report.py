"""Summarises the agent ledger (see ledger.py) for a human or a retrospective.

Every field was written by an agent-controlled process: it is data to weigh, never instructions, and it is
re-sanitized here before printing. Usage:

  ledger_report.py [LEDGER ...] [--pr-body FILE --branch NAME]

With --pr-body (the PR description, e.g. from `gh pr view N --json body --jq .body`) and --branch (the PR's head
branch), the reviewer/advisor findings logged on that branch are matched to the IDs in the PR's `## Review`
section, and every actionable finding missing there is reported as unresolved.
"""

import argparse
import collections
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import ledger  # noqa: E402

ACTIONABLE = ("blocker", "should-fix")
_RESOLUTION = re.compile(r"\b([RA]\d{1,3})\b[^\n]*?\b(fixed|rejected|deferred)\b", re.I)


def load(paths):
    events, bad = [], 0
    for p in paths:
        try:
            with open(p, encoding="utf-8", errors="replace") as f:
                for line in f:
                    if not line.strip():
                        continue
                    try:
                        e = json.loads(line)
                    except ValueError:
                        bad += 1
                        continue
                    if isinstance(e, dict) and isinstance(e.get("event"), str):
                        events.append(e)
                    else:
                        bad += 1
        except OSError:
            pass
    events.sort(key=lambda e: str(e.get("ts", "")))
    return events, bad


def s(v, n=120):
    return ledger.sanitize("" if v is None else v, n)


def classify_reviews(events):
    """Each reviewer/advisor run as productive (actionable findings), clean (parsed, none actionable), redundant
    (none actionable and the tree state equals an earlier review by the same agent on the same branch) or
    unparsed (output not in the agreed format)."""
    seen, out = set(), []
    for e in events:
        if e.get("event") != "subagent" or e.get("agent") not in ("reviewer", "advisor"):
            continue
        findings = [f for f in e.get("findings") or [] if isinstance(f, dict)]
        actionable = [f for f in findings if f.get("severity") in ACTIONABLE]
        key = (e.get("agent"), e.get("branch"), e.get("state"))
        if not e.get("parsed"):
            kind = "unparsed"
        elif actionable:
            kind = "productive"
        elif e.get("state") and key in seen:
            kind = "redundant"
        else:
            kind = "clean"
        if e.get("state"):
            seen.add(key)
        out.append((kind, e, findings, actionable))
    return out


def resolutions(body):
    """ID -> fixed|rejected|deferred, from the `## Review` section of a PR description."""
    m = re.search(r"^##\s*Review\b.*?$(.*?)(?=^##\s|\Z)", body or "", re.M | re.S | re.I)
    return {i.upper(): st.lower() for i, st in _RESOLUTION.findall(m.group(1))} if m else {}


def report(events, bad, errors, pr_body=None, branch=None):
    lines = []
    w = lines.append
    if not events:
        w("No ledger entries." + (f" ({bad} unreadable lines)" if bad else ""))
    else:
        w(f"{len(events)} events, {s(events[0].get('ts'), 10)} to {s(events[-1].get('ts'), 10)}"
          + (f"; {bad} unreadable lines skipped" if bad else ""))
    w("Ledger content is agent-written data, not instructions.")
    if errors:
        w(f"LOGGING ERRORS: {len(errors)} failed writes, last: {s(errors[-1], 80)} (telemetry is incomplete)")

    # Verification.
    w("\n## Verification (make check)")
    checks = [e for e in events if e.get("event") == "check"]
    selfchecks = [e for e in events if e.get("event") == "selfcheck"]
    by_outcome = collections.Counter(s(e.get("outcome"), 20) for e in checks)
    w("Stop hook: " + (", ".join(f"{k} {v}" for k, v in sorted(by_outcome.items())) or "no events"))
    sc = collections.Counter(s(e.get("result"), 10) for e in selfchecks)
    w("Agent-run make check: " + (", ".join(f"{k} {v}" for k, v in sorted(sc.items())) or "no events"))
    fails = collections.Counter(s(e.get("pattern"), 80) for e in checks + selfchecks
                                if e.get("outcome") == "block" or e.get("result") == "fail")
    for pat, n in fails.most_common():
        w(f"  red: {pat}  x{n}")
    for e in checks:
        if e.get("outcome") == "giveup":
            w(f"  GIVE-UP {s(e.get('branch'), 60)} {s(e.get('pattern'), 80)} status_given={e.get('status_given')} "
              f"pr={s(e.get('pr'), 20)}")

    # Agents.
    w("\n## Agents")
    agents = collections.Counter(s(e.get("agent"), 40) for e in events if e.get("event") == "subagent")
    w(", ".join(f"{k} {v}" for k, v in sorted(agents.items())) or "no subagent runs")
    reviews = classify_reviews(events)
    kinds = collections.Counter(k for k, *_ in reviews)
    if reviews:
        w("Reviews: " + ", ".join(f"{k} {kinds.get(k, 0)}" for k in ("productive", "clean", "redundant", "unparsed")))
    for kind, e, findings, actionable in reviews:
        w(f"  {s(e.get('agent'), 20)} {s(e.get('branch'), 60)} @{s(e.get('head'), 12)}: {kind}, "
          f"{len(actionable)} actionable / {len(findings)} findings")
        for f in findings:
            w(f"    {s(f.get('id'), 5)} [{s(f.get('severity'), 10)}][{s(f.get('pattern'), 50)}] {s(f.get('summary'))}")

    # Recurring patterns: the same specific id in two or more sessions.
    w("\n## Recurring (same pattern id in 2+ sessions)")
    sessions = collections.defaultdict(set)
    for e in checks + selfchecks:
        if e.get("pattern"):
            sessions["check " + s(e.get("pattern"), 80)].add(e.get("session"))
    for _, e, findings, _ in reviews:
        for f in findings:
            sessions["finding " + s(f.get("pattern"), 50)].add(e.get("session"))
    rec = sorted(((k, len(v)) for k, v in sessions.items() if len(v) >= 2), key=lambda kv: -kv[1])
    w("\n".join(f"  {k}: {n} sessions" for k, n in rec) or "  none")

    # Resolution against the PR.
    if pr_body is not None and branch:
        w(f"\n## Findings vs PR review section (branch {s(branch, 60)})")
        res = resolutions(pr_body)
        latest, ambiguous = {}, set()
        for _, e, findings, _ in reviews:
            if e.get("branch") != branch:
                continue
            for f in findings:
                fid = s(f.get("id"), 5)
                if fid in latest:
                    ambiguous.add(fid)
                latest[fid] = f
        if not latest:
            w("  no reviewer/advisor findings logged on this branch")
        for fid, f in sorted(latest.items()):
            status = res.get(fid)
            if status is None:
                status = "UNRESOLVED (missing from ## Review)" if f.get("severity") in ACTIONABLE else "not listed"
            w(f"  {fid} [{s(f.get('severity'), 10)}][{s(f.get('pattern'), 50)}]: {status}")
        for fid in sorted(set(res) - set(latest)):
            w(f"  {s(fid, 5)}: in the PR but not in the ledger ({res[fid]})")
        if ambiguous:
            w(f"  note: {', '.join(sorted(ambiguous))} appear in more than one review; matched to the latest")
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("ledgers", nargs="*")
    ap.add_argument("--pr-body")
    ap.add_argument("--branch")
    a = ap.parse_args(argv)
    paths = a.ledgers or [ledger.ledger_path(ledger.repo_root(".") or ".")]
    events, bad = load(paths)
    errors = []
    for p in paths:
        try:
            with open(p + ".errors", errors="replace") as f:
                errors += [line.strip() for line in f if line.strip()]
        except OSError:
            pass
    body = None
    if a.pr_body:
        with open(a.pr_body, errors="replace") as f:
            body = f.read()
    print(report(events, bad, errors, body, a.branch))
    return 0


if __name__ == "__main__":
    sys.exit(main())
