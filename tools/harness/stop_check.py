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
    pr = gate.pr_view(root, "number,isDraft,state")
    if pr is None:
        return "no-pr"
    if pr.get("state") != "OPEN":
        return "no-open-pr"
    if pr.get("isDraft"):
        return "already-draft"
    try:
        r = subprocess.run(["gh", "pr", "ready", str(pr["number"]), "--undo"], cwd=root, capture_output=True,
                           timeout=20)
        return "drafted" if r.returncode == 0 else "draft-failed"
    except Exception:
        return "draft-failed"


_DRAFT_NOTE = {"drafted": " Its PR was converted to a draft.", "already-draft": " Its PR is a draft."}


def bounded(kind, ctx, log, block_text, demand_text, final_text, exhausted=False):
    """The bounded block loop shared by the check and the review stage: block up to CAP times, then demand an
    explicit NOT READY status once, then let the session end with a systemMessage (and the PR made a draft).
    block_text(n) and final_text(note) build the messages; log(state, **fields) writes the ledger event."""
    counter = os.path.join(ctx["sd"], f"{kind}-blocks-{ctx['session']}")
    flag = os.path.join(ctx["sd"], f"{kind}-status-{ctx['session']}")
    blocks = int(read(counter)) if read(counter).isdigit() else 0
    if exhausted or blocks >= CAP:
        last = str(ctx["payload"].get("last_assistant_message") or "")
        if not STATUS.search(last) and not os.path.exists(flag):
            write(flag, "1")
            log("status-demanded", n=blocks)
            return 2, demand_text, None
        pr = draft_pr(ctx["root"])
        log("giveup", n=blocks, status_given=bool(STATUS.search(last)), pr=pr)
        remove(counter, flag)
        return 0, "", {"systemMessage": final_text(_DRAFT_NOTE.get(pr, ""))}
    write(counter, str(blocks + 1))
    log("block", n=blocks + 1)
    return 2, block_text(blocks + 1), None


def reset(kind, ctx):
    """Clears a kind's streak; returns the number of blocks it had."""
    counter = os.path.join(ctx["sd"], f"{kind}-blocks-{ctx['session']}")
    blocks = int(read(counter)) if read(counter).isdigit() else 0
    remove(counter, os.path.join(ctx["sd"], f"{kind}-status-{ctx['session']}"))
    return blocks


def decide(payload):
    """Returns (exit code, stderr text, stdout JSON or None)."""
    root = ledger.repo_root(payload.get("cwd") or os.environ.get("CLAUDE_PROJECT_DIR") or ".")
    if not root or not has_check_target(root):
        return 0, "", None
    ctx = {"root": root, "sd": ledger.state_dir(root), "session": ledger.session_id(payload), "payload": payload}
    stamp = os.path.join(ctx["sd"], "green")
    # Taken before the check, so an edit made while it runs is never stamped green.
    current, tree = ledger.state(root)

    if read(stamp) == current:
        blocks = reset("check", ctx)
        if blocks:
            ledger.log(root, payload, "check", outcome="recovered", n=blocks, via="known-green-state")
        return review_stage(ctx, tree)

    ok, out = run_check(root)
    if ok:
        blocks = reset("check", ctx)
        ledger.log(root, payload, "check", outcome="recovered" if blocks else "pass", n=blocks)
        if ledger.state_hash(root) == current:
            write(stamp, current)
        return review_stage(ctx, tree)

    step, pattern = ledger.check_failure(out)

    def block_text(n):
        lines = [f"make check failed (block {n}/{CAP}, {pattern}); fix it before finishing."]
        if n == 2:
            lines.append("Second red attempt in a row: if it is the same failure, ask the advisor agent with this "
                         "output before another attempt.")
        if n == CAP:
            lines.append("Last attempt. If you cannot fix it, your final message must start with `NOT READY:` and "
                         "state the remaining failure, what you tried and whether you consulted the advisor agent.")
        return "\n".join(lines + [tail(out, 60)])

    return bounded(
        "check", ctx,
        lambda state, **kw: ledger.log(root, payload, "check", outcome=state, step=step, pattern=pattern, **kw),
        block_text,
        f"make check is still red after {CAP} blocked attempts ({pattern}). Do not attempt another fix. Your final "
        "message must start with `NOT READY:` and state the remaining failure (quote it), what you tried, whether "
        "you consulted the advisor agent, and that this must not be merged. Then stop.\n" + tail(out, 30),
        lambda note: (f"make check is still red after {CAP} blocked attempts ({pattern}): the work is NOT done and "
                      f"must not be merged.{note} Last output:\n{tail(out, 20)}"))


def review_stage(ctx, tree):
    """After a green check: the review requirements for review/sensitive changes (gate.py). The fallback for a
    lead that skipped them; bounded like a red check, then NOT READY."""
    if not gate.enabled():
        return 0, "", None
    req = gate.requirements(ctx["root"], tree=tree)
    if not req["missing"] and not req["limit_reached"]:
        reset("review", ctx)
        return 0, "", None
    unmet = list(req["missing"])
    if req["limit_reached"]:
        unmet.append(f"{gate.MAX_ROUNDS} review rounds used; changes since the last review are unreviewed: "
                     + "; ".join(req["delta"]))
    listing = "\n- " + "\n- ".join(unmet)
    tier, why = req["tier"], "; ".join(req["classification"]["reasons"][:4]) or "escalated"
    return bounded(
        "review", ctx,
        lambda state, **kw: ledger.log(ctx["root"], ctx["payload"], "gate", point="stop", decision=state, tier=tier,
                                       missing=[ledger.sanitize(m, 120) for m in unmet[:6]], **kw),
        lambda n: (f"`make check` is green, but this is a {tier} change and its review requirements are not met "
                   f"(review block {n}/{CAP}). Reasons: {why}.{listing}\nRun `ai-risk status` to check. See CLAUDE.md "
                   "(Risk lifecycle)."),
        f"The review requirements for this {tier} change are still not met. Do not start another review round. Your "
        "final message must start with `NOT READY:` and list what is unreviewed or unresolved, what the reviews found, "
        "and whether you consulted the advisor. If a PR is open it must stay a draft. Then stop." + listing,
        lambda note: f"Review requirements for this {tier} change are not met: the work is NOT ready to merge.{note}"
                     + listing,
        exhausted=req["limit_reached"])


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
