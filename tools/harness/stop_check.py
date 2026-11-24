"""Claude Code Stop hook: refuse to finish while `make check` is red.

- Runs `make check` whenever the tree's git state (ledger.state_hash: HEAD, tracked changes, untracked files)
  differs from the last state it saw green. Committed work counts, so finishing after a commit no longer skips it.
- Blocks (exit 2, output fed back to the agent) at most 3 times per session. The second block points to the
  advisor; the third asks for an explicit NOT READY status if the agent can't fix it.
- After the cap it never reports success: it demands the NOT READY status once if the final message lacks it,
  then lets the session end with a systemMessage telling the user the work is not done. In the agent container
  (AI_SUBS_DRAFT_ON_GIVEUP=1) it also turns the branch's open PR into a draft. CI stays the merge gate.

The green stamp and the counters live in <git dir>/ai-subs-harness/. The agent runs as the same user, so it could
forge them: they make the hook cheap and bounded, not tamper-proof. Every decision is also written to the ledger.
"""

import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import gate  # noqa: E402
import ledger  # noqa: E402

CAP = 3
CHECK_TIMEOUT = 240
STATUS = re.compile(r"^\W*NOT READY\b", re.M)


def read(path):
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return ""


def write(path, text):
    with open(path, "w") as f:
        f.write(text)


def remove(*paths):
    for p in paths:
        try:
            os.remove(p)
        except OSError:
            pass


def has_check_target(root):
    return re.search(r"^check\s*:", read(os.path.join(root, "Makefile")), re.M) is not None


def run_check(root):
    try:
        r = subprocess.run(["make", "check"], cwd=root, capture_output=True, timeout=CHECK_TIMEOUT)
        out = (r.stdout + r.stderr).decode("utf-8", "replace")
        return r.returncode == 0, out
    except subprocess.TimeoutExpired:
        return False, f"make: *** [timeout] make check did not finish within {CHECK_TIMEOUT}s"
    except OSError as exc:
        return False, f"make: *** [unavailable] could not run make check: {exc}"


def tail(text, n):
    return "\n".join(ledger._ANSI.sub("", text).rstrip().splitlines()[-n:])


def draft_pr(root):
    if os.environ.get("AI_SUBS_DRAFT_ON_GIVEUP") != "1":
        return "not-attempted"
    try:
        r = subprocess.run(["gh", "pr", "view", "--json", "number,isDraft,state"], cwd=root, capture_output=True,
                           timeout=20)
        if r.returncode != 0:
            return "no-pr"
        pr = json.loads(r.stdout or "{}")
        if pr.get("state") != "OPEN":
            return "no-open-pr"
        if pr.get("isDraft"):
            return "already-draft"
        r = subprocess.run(["gh", "pr", "ready", str(pr["number"]), "--undo"], cwd=root, capture_output=True,
                           timeout=20)
        return "drafted" if r.returncode == 0 else "draft-failed"
    except Exception:
        return "draft-failed"


def decide(payload):
    """Returns (exit code, stderr text, stdout JSON or None)."""
    root = ledger.repo_root(payload.get("cwd") or os.environ.get("CLAUDE_PROJECT_DIR") or ".")
    if not root or not has_check_target(root):
        return 0, "", None
    git_dir = ledger._git(root, "rev-parse", "--path-format=absolute", "--git-dir")
    sd = os.path.join(git_dir or os.path.join(root, ".git"), "ai-subs-harness")
    os.makedirs(sd, exist_ok=True)
    session = re.sub(r"[^A-Za-z0-9_-]", "", str(payload.get("session_id", ""))) or "default"
    counter, flag, stamp = (os.path.join(sd, f"blocks-{session}"), os.path.join(sd, f"status-{session}"),
                            os.path.join(sd, "green"))
    path = ledger.ledger_path(root)
    base = ledger.base_fields(payload, root)

    def log(**kw):
        ledger.append(path, {**base, "event": "check", **kw})

    # Taken before the check, so an edit made while it runs is never stamped green.
    current = ledger.state_hash(root)
    blocks = int(read(counter)) if read(counter).isdigit() else 0

    if read(stamp) == current:
        if blocks:
            log(outcome="recovered", n=blocks, via="known-green-state")
            remove(counter, flag)
        return review_stage(root, sd, session, payload, path, base)

    ok, out = run_check(root)
    if ok:
        log(outcome="recovered" if blocks else "pass", n=blocks)
        remove(counter, flag)
        if ledger.state_hash(root) == current:
            write(stamp, current)
        return review_stage(root, sd, session, payload, path, base)

    step, pattern = ledger.check_failure(out)
    if blocks >= CAP:
        last = str(payload.get("last_assistant_message") or "")
        if not STATUS.search(last) and not os.path.exists(flag):
            write(flag, "1")
            log(outcome="status-demanded", n=blocks, step=step, pattern=pattern)
            return 2, (
                f"make check is still red after {CAP} blocked attempts ({pattern}). Do not attempt another fix. "
                "Your final message must start with `NOT READY:` and state the remaining failure (quote it), what "
                "you tried, whether you consulted the advisor agent, and that this must not be merged. Then stop.\n"
                + tail(out, 30)
            ), None
        pr = draft_pr(root)
        log(outcome="giveup", n=blocks, step=step, pattern=pattern, status_given=bool(STATUS.search(last)), pr=pr)
        remove(counter, flag)
        note = {"drafted": " Its PR was converted to a draft.", "already-draft": " Its PR is a draft."}.get(pr, "")
        msg = (f"make check is still red after {CAP} blocked attempts ({pattern}): the work is NOT done and must "
               f"not be merged.{note} Last output:\n{tail(out, 20)}")
        return 0, "", {"systemMessage": msg}

    n = blocks + 1
    write(counter, str(n))
    log(outcome="block", n=n, step=step, pattern=pattern)
    lines = [f"make check failed (block {n}/{CAP}, {pattern}); fix it before finishing."]
    if n == 2:
        lines.append("Second red attempt in a row: if it is the same failure, ask the advisor agent with this "
                     "output before another attempt.")
    if n == CAP:
        lines.append("Last attempt. If you cannot fix it, your final message must start with `NOT READY:` and "
                     "state the remaining failure, what you tried and whether you consulted the advisor agent.")
    lines.append(tail(out, 60))
    return 2, "\n".join(lines), None


def review_stage(root, sd, session, payload, path, base):
    """After a green check: the review requirements for review/sensitive changes (gate.py). The fallback for a
    lead that skipped them; bounded by its own cap of 3 blocks, then NOT READY like a red check."""
    if not gate.enabled():
        return 0, "", None
    req = gate.requirements(root, session)
    counter, flag = os.path.join(sd, f"review-blocks-{session}"), os.path.join(sd, f"review-status-{session}")
    if not req["missing"] and not req["limit_reached"]:
        remove(counter, flag)
        return 0, "", None

    def log(**kw):
        ledger.append(path, {**base, "event": "gate", "point": "stop", "tier": req["tier"],
                             "missing": [ledger.sanitize(m, 120) for m in req["missing"][:6]], **kw})

    unmet = list(req["missing"])
    if req["limit_reached"]:
        unmet.append(f"{gate.MAX_ROUNDS} review rounds used; changes since the last review are unreviewed: "
                     + "; ".join(req["delta"]))
    blocks = int(read(counter)) if read(counter).isdigit() else 0
    if req["limit_reached"] or blocks >= CAP:
        last = str(payload.get("last_assistant_message") or "")
        if not STATUS.search(last) and not os.path.exists(flag):
            write(flag, "1")
            log(decision="status-demanded", n=blocks)
            return 2, (f"The review requirements for this {req['tier']} change are still not met. Do not start "
                       "another review round. Your final message must start with `NOT READY:` and list what is "
                       "unreviewed or unresolved, what the reviews found, and whether you consulted the advisor. "
                       "If a PR is open it must stay a draft. Then stop.\n- " + "\n- ".join(unmet)), None
        pr = draft_pr(root)
        log(decision="giveup", n=blocks, status_given=bool(STATUS.search(last)), pr=pr)
        remove(counter, flag)
        note = {"drafted": " Its PR was converted to a draft.", "already-draft": " Its PR is a draft."}.get(pr, "")
        return 0, "", {"systemMessage": f"Review requirements for this {req['tier']} change are not met: the work is "
                                        f"NOT ready to merge.{note}\n- " + "\n- ".join(unmet)}
    n = blocks + 1
    write(counter, str(n))
    log(decision="block", n=n)
    return 2, (f"`make check` is green, but this is a {req['tier']} change and its review requirements are not met "
               f"(review block {n}/{CAP}). Reasons: {'; '.join(req['classification']['reasons'][:4]) or 'escalated'}."
               "\n- " + "\n- ".join(unmet) + "\nRun `ai-risk status` to check. See CLAUDE.md (Risk lifecycle)."), None


def main():
    if ledger.shadowed_by_image():
        return 0
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except ValueError:
        payload = {}
    code, err, out = decide(payload)
    if out is not None:
        print(json.dumps(out))
    if err:
        print(err, file=sys.stderr)
    return code


if __name__ == "__main__":
    sys.exit(main())
