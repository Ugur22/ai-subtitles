"""Risk-based review gates for the agent container (enabled by AI_SUBS_REVIEW_GATE=1 in managed settings).

Three moments, one set of requirements (requirements()):
- PostToolUse (Edit/Write/Bash): reclassify the branch; the first time a session's tier rises, tell the agent
  what that tier requires (advisor before implementing sensitive work, reviewer before the PR). Never blocks.
- PreToolUse on `gh pr create|edit|ready`: deny until the requirements hold and the description is complete.
- Stop (stop_check.py, after `make check` is green): the fallback; blocks at most 3 times, then NOT READY.

Requirements for tier review or sensitive: a `reviewer` run tied to the current code (a git tree snapshot), or
a later change since that review small enough not to need another look; for sensitive also an `advisor` run on
the branch. Re-review is targeted (only the delta) and bounded: after MAX_ROUNDS reviews, further significant
changes make the work NOT READY instead of asking for a fourth review.

All of this reads the agent-writable ledger: it catches workflow slips, it does not prove a review happened.
The trusted check is `policy` in CI plus the owner's approval of the exact commit.
"""

import json
import os
import re
import shlex
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import ledger  # noqa: E402
import prbody  # noqa: E402
import risk  # noqa: E402

MAX_ROUNDS = 3
DELTA_LINES = 80
ACTIONABLE = ("blocker", "should-fix")


def enabled():
    return os.environ.get("AI_SUBS_REVIEW_GATE") == "1"


def _branch_events(events, branch, agent):
    return [e for e in events if e.get("event") == "subagent" and e.get("agent") == agent
            and e.get("branch") == branch]


def significant_delta(root, reviewed_tree, tree):
    """Reasons the change since the reviewed tree needs another review; [] when it doesn't."""
    if not reviewed_tree or reviewed_tree == tree:
        return []
    d = risk.classify_delta(root, reviewed_tree, tree)
    reviewed_files = set((risk._run(root, "diff", "--name-only", risk.merge_base(root), reviewed_tree) or "").split())
    reasons = [r for r in d["sensitive_content"]]
    reasons += [r for r in d["sensitive_paths"] if r.split(": ", 1)[-1] not in reviewed_files]
    if d["lines"] > DELTA_LINES:
        reasons.append(f"{d['lines']} changed lines outside tests since the review (limit {DELTA_LINES})")
    if d["new_code_files"]:
        reasons.append("new files: " + ", ".join(d["new_code_files"][:5]))
    return reasons


def requirements(root, session="", tree=None, events=None):
    res, tree = risk.classify_branch(root, tree)
    branch = ledger._git(root, "rev-parse", "--abbrev-ref", "HEAD")
    events = risk._events(root) if events is None else events
    tier = risk.effective(res["tier"], events, branch)
    reviews = [e for e in _branch_events(events, branch, "reviewer") if e.get("tree")]
    advisors = _branch_events(events, branch, "advisor")
    missing, delta, limit = [], [], False
    if risk.RANK[tier] >= risk.RANK[risk.REVIEW]:
        if not reviews:
            missing.append("reviewer: no `reviewer` run on this branch yet; have it review the diff against origin/main")
        else:
            last = reviews[-1]
            delta = significant_delta(root, last["tree"], tree)
            if delta:
                if len(reviews) >= MAX_ROUNDS:
                    limit = True
                else:
                    nxt = 1 + max((int(f["id"][1:]) for e in reviews for f in e.get("findings") or []
                                   if str(f.get("id", "")).startswith("R") and str(f["id"][1:]).isdigit()), default=0)
                    missing.append(
                        f"re-review: the changes since the review are significant ({'; '.join(delta)}). Targeted "
                        f"re-review: give `reviewer` only `git diff {last['tree'][:12]}` and ask it to number findings "
                        f"from R{nxt} (round {len(reviews) + 1} of {MAX_ROUNDS})")
    if tier == risk.SENSITIVE and not advisors:
        missing.append("advisor: sensitive work needs an `advisor` run on the plan (before implementing it)")
    return {"tier": tier, "classification": res, "tree": tree, "branch": branch, "missing": missing,
            "reviews": reviews, "advisors": advisors, "delta": delta, "limit_reached": limit}


def latest_findings(req):
    """ID -> finding over every reviewer/advisor run on the branch, the latest run winning on a repeated ID."""
    out = {}
    for e in req["advisors"] + req["reviews"]:
        for f in e.get("findings") or []:
            if isinstance(f, dict) and f.get("id"):
                out[str(f["id"]).upper()] = f
    return out


def body_problems(req, body, title):
    problems = []
    found, dprobs = prbody.dispositions(body)
    problems += dprobs
    for fid, f in sorted(latest_findings(req).items()):
        if f.get("severity") in ACTIONABLE and (found is None or fid not in found):
            problems.append(f"## Review: {fid} [{f.get('severity')}] ({ledger.sanitize(f.get('pattern', ''), 50)}) "
                            "has no disposition")
    if req["tier"] == risk.SENSITIVE:
        problems += prbody.risk_problems(body)
        if title is not None and "[sensitive]" not in title.lower():
            problems.append("the PR title must start with [sensitive]")
    return problems


# --- PreToolUse: gh pr create | edit | ready ------------------------------------------------------------------

_GH_PR = re.compile(r"\bgh\s+pr\s+(create|edit|ready)\b")


def parse_gh(command):
    """(action, options) for the first `gh pr create|edit|ready` in the command, or (None, None)."""
    m = _GH_PR.search(command)
    if not m:
        return None, None
    rest = command[m.end():]
    try:
        lex = shlex.shlex(rest, posix=True, punctuation_chars=";&|")
        lex.whitespace_split = True
        tokens = []
        for t in lex:
            if t and set(t) <= set(";&|"):
                break
            tokens.append(t)
    except ValueError:
        return m.group(1), {"unparsable": True}
    opts, i = {"draft": False, "undo": False}, 0
    names = {"-t": "title", "--title": "title", "-b": "body", "--body": "body", "-F": "body_file",
             "--body-file": "body_file"}
    while i < len(tokens):
        t = tokens[i]
        key, val = (t.split("=", 1) + [None])[:2] if t.startswith("--") and "=" in t else (t, None)
        if key in names:
            if val is None:
                i += 1
                val = tokens[i] if i < len(tokens) else ""
            opts[names[key]] = val
        elif key in ("-d", "--draft"):
            opts["draft"] = True
        elif key == "--undo":
            opts["undo"] = True
        elif key in ("-f", "--fill", "--fill-first", "--fill-verbose", "-w", "--web"):
            opts["fill"] = True
        i += 1
    return m.group(1), opts


def _pr_view(root):
    try:
        r = subprocess.run(["gh", "pr", "view", "--json", "body,title"], cwd=root, capture_output=True, timeout=20)
        return json.loads(r.stdout) if r.returncode == 0 else None
    except Exception:
        return None


def pr_gate(payload):
    """None to allow, or the reason to deny."""
    command = str((payload.get("tool_input") or {}).get("command", ""))
    action, opts = parse_gh(command)
    if action is None or opts.get("undo"):
        return None
    root = ledger.repo_root(payload.get("cwd") or ".")
    if not root:
        return None
    req = requirements(root, payload.get("session_id", ""))
    if req["tier"] == risk.ORDINARY:
        return None
    if action == "edit" and not ({"body", "body_file", "title"} & set(opts)):
        return None
    head = (f"Risk tier {req['tier']} ({'; '.join(req['classification']['reasons'][:4]) or 'escalated'}). "
            "Before this PR command can run:")
    problems = list(req["missing"])
    sets_body = action == "create" or (action == "edit" and ("body" in opts or "body_file" in opts))
    if sets_body and (opts.get("unparsable") or opts.get("fill") or "body" in opts
                      or opts.get("body_file") in (None, "-")):
        problems.append("write the description to a file and pass it with `--body-file <path>` (not --body, "
                        "--fill or stdin), so it can be checked")
    body, title = None, opts.get("title")
    if action == "ready":
        pr = _pr_view(root)
        if pr is None:
            problems.append("could not read the PR description with `gh pr view`")
        else:
            body, title = pr.get("body", ""), pr.get("title", "")
    elif opts.get("body_file") not in (None, "-"):
        path = os.path.join(payload.get("cwd") or root, opts["body_file"])
        try:
            with open(path, errors="replace") as f:
                body = f.read()
        except OSError:
            problems.append(f"cannot read --body-file {opts['body_file']}")
    if body is not None:
        problems += body_problems(req, body, title if action != "edit" or title is not None else None)
    if req["limit_reached"]:
        if action == "ready":
            problems.append(f"{MAX_ROUNDS} review rounds are used up and the latest changes are unreviewed: the "
                            "work stays a draft (NOT READY) for the owner to review")
        elif not opts.get("draft") or "NOT READY" not in (body or ""):
            problems.append(f"{MAX_ROUNDS} review rounds are used up and the latest changes are unreviewed "
                            f"({'; '.join(req['delta'])}). Open the PR with --draft and a description that starts "
                            "with `NOT READY:` saying what is unreviewed")
    log(root, payload, "gate", point="pr", action=action, decision="deny" if problems else "allow",
        tier=req["tier"], missing=[ledger.sanitize(p, 120) for p in problems[:8]])
    return (head + "\n- " + "\n- ".join(problems)) if problems else None


# --- PostToolUse: reassess the tier while working ----------------------------------------------------------------

def reassess(payload):
    """additionalContext text the first time this session's tier rises, else None."""
    root = ledger.repo_root(payload.get("cwd") or ".")
    if not root:
        return None
    session = re.sub(r"[^A-Za-z0-9_-]", "", str(payload.get("session_id", ""))) or "default"
    git_dir = ledger._git(root, "rev-parse", "--path-format=absolute", "--git-dir")
    sd = os.path.join(git_dir, "ai-subs-harness")
    os.makedirs(sd, exist_ok=True)
    marker = os.path.join(sd, f"tier-{session}")
    try:
        with open(marker) as f:
            before = f.read().strip()
    except OSError:
        before = risk.ORDINARY
    branch = ledger._git(root, "rev-parse", "--abbrev-ref", "HEAD")
    res, _ = risk.classify_branch(root)
    tier = risk.effective(res["tier"], risk._events(root), branch)
    if risk.RANK.get(tier, 0) <= risk.RANK.get(before, 0):
        return None
    with open(marker, "w") as f:
        f.write(tier)
    log(root, payload, "risk", tier=tier, previous=before, reasons=[ledger.sanitize(r, 120) for r in res["reasons"][:6]])
    why = "; ".join(res["reasons"][:4]) or "escalated"
    if tier == risk.SENSITIVE:
        return (f"Risk is now SENSITIVE ({why}). Before implementing further, consult the `advisor` agent on your "
                "plan; it is required for this branch. Write the ## Risk section as you go. `reviewer` must review "
                "the finished diff before `gh pr create`, and the PR title starts with [sensitive]. See CLAUDE.md "
                "(Risk lifecycle). `ai-risk status` shows what is still missing.")
    return (f"Risk is now REVIEW ({why}). Have the `reviewer` agent review the finished diff before `gh pr create`, "
            "and give every finding a disposition in ## Review. `ai-risk status` shows what is still missing.")


def log(root, payload, event, **fields):
    ledger.append(ledger.ledger_path(root), {**ledger.base_fields(payload, root), "event": event, **fields})


def main():
    if ledger.shadowed_by_image():
        return 0
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except ValueError:
        return 0
    event = payload.get("hook_event_name")
    try:
        if event == "PostToolUse":
            ledger.handle(payload)  # selfcheck logging for Bash `make check`
    except Exception:
        pass
    if not enabled():
        return 0
    try:
        if event == "PreToolUse" and payload.get("tool_name") == "Bash":
            reason = pr_gate(payload)
            if reason:
                print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                                         "permissionDecisionReason": reason}}))
        elif event == "PostToolUse":
            ctx = reassess(payload)
            if ctx:
                print(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": ctx}}))
    except Exception as exc:
        try:
            root = ledger.repo_root(payload.get("cwd") or ".")
            ledger._record_error(ledger.ledger_path(root) if root else "", f"gate-{event}", exc)
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
