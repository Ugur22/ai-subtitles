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
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import ledger  # noqa: E402
import prbody  # noqa: E402

ACTIONABLE = prbody.ACTIONABLE
load = ledger.load_events


def s(v, n=120):
    return ledger.sanitize("" if v is None else v, n)


def classify_reviews(events, dispositions=None, branch=None):
    """Each reviewer/advisor run as one of:
    confirmed-productive  an actionable finding (blocker/should-fix) was fixed, per the PR's ## Review
    rejected-only         every actionable finding was rejected (the review found nothing that held up)
    unresolved            an actionable finding has no disposition, or a blocker was deferred
    deferred              actionable findings were deferred, none fixed
    productive?           actionable findings, but no PR description to confirm what happened to them
    clean                 parsed, nothing actionable
    redundant             nothing actionable and the code equals an earlier review by the same agent on the branch
    unparsed              output not in the agreed format
    Dispositions (from --pr-body) apply only to runs on --branch."""
    seen, out = set(), []
    for e in events:
        if e.get("event") != "subagent" or e.get("agent") not in ("reviewer", "advisor"):
            continue
        findings = [f for f in e.get("findings") or [] if isinstance(f, dict)]
        actionable = [f for f in findings if f.get("severity") in ACTIONABLE]
        key = (e.get("agent"), e.get("branch"), e.get("tree") or e.get("state"))
        known = dispositions is not None and e.get("branch") == branch
        if not e.get("parsed"):
            kind = "unparsed"
        elif actionable and known:
            states = [dispositions.get(str(f.get("id", "")).upper(), {}).get("disposition") for f in actionable]
            if None in states or any(f.get("severity") == "blocker" and st == "deferred"
                                     for f, st in zip(actionable, states)):
                kind = "unresolved"
            elif "fixed" in states:
                kind = "confirmed-productive"
            elif all(st == "rejected" for st in states):
                kind = "rejected-only"
            else:
                kind = "deferred"
        elif actionable:
            kind = "productive?"
        elif key[2] and key in seen:
            kind = "redundant"
        else:
            kind = "clean"
        if key[2]:
            seen.add(key)
        out.append((kind, e, findings, actionable))
    return out


KINDS = ("confirmed-productive", "rejected-only", "unresolved", "deferred", "productive?", "clean", "redundant",
         "unparsed")


def report(events, bad, errors, pr_body=None, branch=None):
    lines = []
    w = lines.append
    if not events:
        w("No ledger entries." + (f" ({bad} unreadable lines)" if bad else ""))
    else:
        w(f"{len(events)} events, {s(events[0].get('ts'))[:10]} to {s(events[-1].get('ts'))[:10]}"
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
    # A red run the agent followed with a green one in the same session: a recovery it made on its own.
    red, fixed = set(), 0
    for e in selfchecks:
        if e.get("result") == "fail":
            red.add(e.get("session"))
        elif e.get("result") == "pass" and e.get("session") in red:
            red.discard(e.get("session"))
            fixed += 1
    w("Agent-run make check: " + (", ".join(f"{k} {v}" for k, v in sorted(sc.items())) or "no events")
      + (f"; recovered {fixed}" if fixed else ""))
    # Block streaks that ended in neither a recovery nor a give-up (session ended, turns ran out).
    streak = {}
    for e in checks:
        key = (e.get("session"), e.get("branch"))
        if e.get("outcome") in ("block", "status-demanded"):
            streak[key] = e
        else:
            streak.pop(key, None)
    for e in streak.values():
        w(f"  ABANDONED after block {e.get('n')}: {s(e.get('branch'), 60)} {s(e.get('pattern'), 120)}")
    fails = collections.Counter(s(e.get("pattern"), 120) for e in checks + selfchecks
                                if e.get("outcome") == "block" or e.get("result") == "fail")
    for pat, n in fails.most_common():
        w(f"  red: {pat}  x{n}" + ("  (output hidden from the hook)" if pat == "unknown" else ""))
    for e in checks:
        if e.get("outcome") == "giveup":
            w(f"  GIVE-UP {s(e.get('branch'), 60)} {s(e.get('pattern'), 120)} status_given={e.get('status_given')} "
              f"pr={s(e.get('pr'), 20)}")

    # Agents.
    w("\n## Agents")
    agents = collections.Counter(s(e.get("agent"), 40) for e in events if e.get("event") == "subagent")
    w(", ".join(f"{k} {v}" for k, v in sorted(agents.items())) or "no subagent runs")
    disp, disp_problems = None, []
    if pr_body is not None:
        found, disp_problems = prbody.dispositions(pr_body)
        disp = found or {}
    reviews = classify_reviews(events, disp, branch)
    kinds = collections.Counter(k for k, *_ in reviews)
    if reviews:
        w("Reviews: " + ", ".join(f"{k} {kinds[k]}" for k in KINDS if kinds.get(k)))
    for kind, e, findings, actionable in reviews:
        w(f"  {s(e.get('agent'), 20)} {s(e.get('branch'), 60)} @{s(e.get('head'), 12)}: {kind}, "
          f"{len(actionable)} actionable / {len(findings)} findings")
        for f in findings:
            w(f"    {s(f.get('id'), 5)} [{s(f.get('severity'), 10)}][{s(f.get('pattern'), 50)}] {s(f.get('summary'))}")

    # Risk and gates.
    w("\n## Risk and review gates")
    rises = [e for e in events if e.get("event") == "risk"]
    for e in rises:
        w(f"  risk rose to {s(e.get('tier'), 10)} on {s(e.get('branch'), 60)}: {s('; '.join(e.get('reasons') or []))}")
    for e in events:
        if e.get("event") == "risk_escalation":
            w(f"  escalated to {s(e.get('tier'), 10)} on {s(e.get('branch'), 60)}: {s(e.get('reason'))}")
    gates = collections.Counter(f"{s(e.get('point'), 10)} {s(e.get('decision'), 20)}" for e in events
                                if e.get("event") == "gate")
    w("  gates: " + (", ".join(f"{k} {v}" for k, v in sorted(gates.items())) or "none fired"))

    # Recurring patterns: the same specific id in two or more sessions.
    w("\n## Recurring (same pattern id in 2+ sessions)")
    sessions = collections.defaultdict(set)
    for e in checks + selfchecks:
        if e.get("pattern"):
            sessions["check " + s(e.get("pattern"), 120)].add(e.get("session"))
    for _, e, findings, _ in reviews:
        for f in findings:
            sessions["finding " + s(f.get("pattern"), 50)].add(e.get("session"))
    rec = sorted(((k, len(v)) for k, v in sessions.items() if len(v) >= 2), key=lambda kv: -kv[1])
    w("\n".join(f"  {k}: {n} sessions" for k, n in rec) or "  none")

    # Resolution against the PR.
    if pr_body is not None and branch:
        w(f"\n## Findings vs PR review section (branch {s(branch, 60)})")
        res = {k: v["disposition"] for k, v in disp.items()}
        on_branch = [e for _, e, _, _ in reviews if e.get("branch") == branch]
        latest = {s(k, 5): f for k, f in ledger.latest_findings(on_branch).items()}
        ids = collections.Counter(str(f.get("id", "")).upper() for e in on_branch for f in e.get("findings") or []
                                  if isinstance(f, dict))
        ambiguous = {k for k, n in ids.items() if n > 1}
        if not latest:
            w("  no reviewer/advisor findings logged on this branch")
        for fid, f in sorted(latest.items()):
            status = res.get(fid)
            if status is None:
                status = "UNRESOLVED (missing from ## Review)" if f.get("severity") in ACTIONABLE else "not listed"
            w(f"  {fid} [{s(f.get('severity'), 10)}][{s(f.get('pattern'), 50)}]: {status}")
        for fid in sorted(set(res) - set(latest)):
            w(f"  {s(fid, 5)}: in the PR but not in the ledger ({res[fid]})")
        for p in disp_problems:
            w(f"  PR format: {s(p)}")
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
