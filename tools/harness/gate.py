"""Risk-based review gates for the agent container (enabled by AI_SUBS_REVIEW_GATE=1 in managed settings), and
the `ai-risk` CLI. risk.py holds the pure rules; this module applies them to git and the ledger.

Three moments, one set of requirements (requirements()):
- PostToolUse (Edit/Write/Bash): reclassify the branch; the first time a session's tier rises, tell the agent
  what that tier requires (advisor before implementing sensitive work, reviewer before the PR). Never blocks.
- PreToolUse on `gh pr create|edit|ready`: deny until the requirements hold and the description is complete.
- PreToolUse on `git worktree add` (always denied), and on commit-making git commands and the edit tools while the
  branch is sensitive with no `advisor` run: deny, so the plan reaches advisor before the code does. Edits made
  through Bash (sed, tee) aren't seen; the commit check still is.
- Stop (stop_check.py, after `make check` is green): the fallback; blocks at most 3 times, then NOT READY.

Requirements for tier review or sensitive: a `reviewer` run tied to the current code (a git tree snapshot), or
a later change since that review small enough not to need another look; for sensitive also an `advisor` run on
the branch. Re-review is targeted (only the delta) and bounded: after MAX_ROUNDS reviews, further significant
changes make the work NOT READY instead of asking for a fourth review.

All of this reads the agent-writable ledger: it catches workflow slips, it does not prove a review happened.
The trusted check is `policy` in CI plus the owner's approval of the exact commit.

CLI (`ai-risk` in the container):
  plan PATH...                 tier and required steps for the files you intend to touch (path signals only)
  status                       tier of the branch against origin/main, and what is still required
  escalate review|sensitive --reason TEXT
"""

import argparse
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


def enabled():
    return os.environ.get("AI_SUBS_REVIEW_GATE") == "1"


# --- git side ----------------------------------------------------------------------------------------------------

def merge_base(root):
    for ref in ("origin/main", "main"):
        mb = ledger._git(root, "merge-base", "HEAD", ref)
        if mb:
            return mb
    return ledger._git(root, "rev-parse", "HEAD")


def diff_files(root, base, target):
    """risk.classify_files input for the change from base (commit or tree) to target (tree)."""
    status = ledger._git(root, "diff", "--name-status", "-M", base, target, strip=False, timeout=120)
    patch = ledger._git(root, "diff", "-U0", "--no-color", "-M", base, target, strip=False, timeout=120)
    added, changes, current, in_hunk = {}, {}, None, False
    for line in patch.splitlines():
        if line.startswith("diff --git "):
            current, in_hunk = line.rsplit(" b/", 1)[-1], False
        elif line.startswith("@@"):
            in_hunk = True
        elif in_hunk and current and line[:1] in "+-":
            changes[current] = changes.get(current, 0) + 1
            if line[:1] == "+":
                added.setdefault(current, []).append(line[1:])
    files = []
    for line in status.splitlines():
        parts = line.split("\t")
        if parts[0][:1] == "R" and len(parts) >= 3:
            f = {"path": parts[2], "old": parts[1], "status": "R"}
        elif len(parts) >= 2:
            f = {"path": parts[1], "old": "", "status": parts[0][:1]}
        else:
            continue
        f.update(changes=changes.get(f["path"], 0), added=added.get(f["path"], []))
        files.append(f)
    return files


def significant_delta(root, base, reviewed_tree, tree):
    """Reasons the change since the reviewed tree needs another review; [] when it doesn't."""
    if not reviewed_tree or reviewed_tree == tree:
        return []
    d = risk.classify_files(diff_files(root, reviewed_tree, tree))
    reviewed_files = set(ledger._git(root, "diff", "--name-only", base, reviewed_tree, timeout=120).split())
    reasons = list(d["sensitive_content"])
    reasons += [r for r in d["sensitive_paths"] if r.split(": ", 1)[-1] not in reviewed_files]
    if d["lines"] > DELTA_LINES:
        reasons.append(f"{d['lines']} changed lines outside tests since the review (limit {DELTA_LINES})")
    if d["new_code_files"]:
        reasons.append("new files: " + ", ".join(d["new_code_files"][:5]))
    return reasons


def runs(events, branch, agent):
    return [e for e in events if e.get("event") == "subagent" and e.get("agent") == agent and e.get("branch") == branch]


def requirements(root, tree=None, events=None):
    tree = tree or ledger.snapshot_tree(root)
    base = merge_base(root)
    if tree:
        res = risk.classify_files(diff_files(root, base, tree))
    else:
        res = dict(risk.classify_files([]), reasons=["could not read the working tree"])
    branch = ledger._git(root, "rev-parse", "--abbrev-ref", "HEAD")
    events = ledger.events(root) if events is None else events
    tier = risk.effective(res["tier"], events, branch)
    reviews = [e for e in runs(events, branch, "reviewer") if e.get("tree")]
    advisors = runs(events, branch, "advisor")
    missing, delta, limit = [], [], False
    if risk.RANK[tier] >= risk.RANK[risk.REVIEW]:
        if not reviews:
            missing.append("reviewer: no `reviewer` run on this branch yet; have it review the diff against origin/main")
        else:
            last = reviews[-1]
            delta = significant_delta(root, base, last["tree"], tree)
            if delta and len(reviews) >= MAX_ROUNDS:
                limit = True
            elif delta:
                nxt = 1 + max((int(f["id"][1:]) for f in ledger.latest_findings(reviews).values()
                               if str(f["id"]).upper().startswith("R") and str(f["id"])[1:].isdigit()), default=0)
                missing.append(
                    f"re-review: the changes since the review are significant ({'; '.join(delta)}). Targeted "
                    f"re-review: give `reviewer` only `git diff {last['tree'][:12]}` and ask it to number findings "
                    f"from R{nxt} (round {len(reviews) + 1} of {MAX_ROUNDS})")
    if tier == risk.SENSITIVE and not advisors:
        missing.append("advisor: sensitive work needs an `advisor` run on the plan (before implementing it)")
    return {"tier": tier, "classification": res, "tree": tree, "branch": branch, "missing": missing,
            "reviews": reviews, "advisors": advisors, "delta": delta, "limit_reached": limit}


def body_problems(req, body, title):
    """prbody's rules for the tier, plus: every actionable finding logged on the branch has a disposition."""
    out = prbody.problems(req["tier"], title, body)
    found = prbody.dispositions(body)[0] or {}
    for fid, f in sorted(ledger.latest_findings(req["advisors"] + req["reviews"]).items()):
        if f.get("severity") in prbody.ACTIONABLE and fid not in found:
            out.append(f"## Review: {fid} [{f.get('severity')}] ({ledger.sanitize(f.get('pattern', ''), 50)}) "
                       "has no disposition")
    return out


def pr_view(root, fields):
    """`gh pr view --json <fields>` for the current branch's PR, or None."""
    try:
        r = subprocess.run(["gh", "pr", "view", "--json", fields], cwd=root, capture_output=True, timeout=20)
        return json.loads(r.stdout or "{}") if r.returncode == 0 else None
    except Exception:
        return None


# --- PreToolUse: gh pr create | edit | ready ------------------------------------------------------------------

_GH_PR = re.compile(r"\bgh\s+pr\s+(create|edit|ready)\b")


def parse_gh(command):
    """(action, options) for the first `gh pr create|edit|ready` in the command, or (None, None)."""
    m = _GH_PR.search(command)
    if not m:
        return None, None
    try:
        lex = shlex.shlex(command[m.end():], posix=True, punctuation_chars=";&|")
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
             "--body-file": "body_file", "-H": "head", "--head": "head"}
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
    cds = _CD.findall(command[:m.start()])
    if cds:
        opts["cd"] = cds[-1].strip("'\"")
    return m.group(1), opts


_CD = re.compile(r"(?:^|[;&|(]\s*|\s)cd\s+(\"[^\"]*\"|'[^']*'|[^\s;&|)]+)")


def elsewhere(root, cwd, opts):
    """Why the command would act on another checkout or branch than the one the hooks see, or None. Hooks get
    the session's working directory; a `cd` elsewhere or `--head` of another branch would be judged by the
    wrong code (seen: `cd <worktree> && gh pr create` passed on the main checkout's reviews)."""
    if opts.get("cd"):
        target = ledger.repo_root(os.path.join(cwd, os.path.expanduser(opts["cd"])))
        if not target or os.path.realpath(target) != os.path.realpath(root):
            return (f"run gh pr from this session's checkout ({root}), not after `cd {opts['cd']}`: the review "
                    "gate and the ledger only see this checkout. One session, one checkout, no worktrees.")
    branch = ledger._git(root, "rev-parse", "--abbrev-ref", "HEAD")
    if opts.get("head") and opts["head"].split(":")[-1] != branch:
        return (f"--head {opts['head']} is not the checked-out branch ({branch}); switch to it in this checkout "
                "and run gh pr from there, so the gate judges that branch's code.")
    return None


def pr_gate(payload):
    """None to allow, or the reason to deny."""
    action, opts = parse_gh(str((payload.get("tool_input") or {}).get("command", "")))
    if action is None or opts.get("undo"):
        return None
    if action == "edit" and not ({"body", "body_file", "title"} & set(opts)):
        return None
    root = ledger.repo_root(payload.get("cwd") or ".")
    if not root:
        return None
    wrong_place = elsewhere(root, payload.get("cwd") or root, opts)
    if wrong_place:
        ledger.log(root, payload, "gate", point="pr", action=action, decision="deny", missing=[wrong_place[:120]])
        return wrong_place
    req = requirements(root)
    if req["tier"] == risk.ORDINARY:
        return None
    problems = list(req["missing"])
    sets_body = action == "create" or "body" in opts or "body_file" in opts
    if sets_body and (opts.get("unparsable") or opts.get("fill") or "body" in opts
                      or opts.get("body_file") in (None, "-")):
        problems.append("write the description to a file and pass it with `--body-file <path>` (not --body, "
                        "--fill or stdin), so it can be checked")
    body, title = None, opts.get("title")
    if action == "ready":
        pr = pr_view(root, "body,title")
        if pr is None:
            problems.append("could not read the PR description with `gh pr view`")
        else:
            body, title = pr.get("body") or "", pr.get("title") or ""
    elif opts.get("body_file") not in (None, "-"):
        try:
            with open(os.path.join(payload.get("cwd") or root, opts["body_file"]), errors="replace") as f:
                body = f.read()
        except OSError:
            problems.append(f"cannot read --body-file {opts['body_file']}")
    if body is not None:
        problems += body_problems(req, body, title)
    if req["limit_reached"]:
        if action == "ready":
            problems.append(f"{MAX_ROUNDS} review rounds are used up and the latest changes are unreviewed: the "
                            "work stays a draft (NOT READY) for the owner to review")
        elif not opts.get("draft") or "NOT READY" not in (body or ""):
            problems.append(f"{MAX_ROUNDS} review rounds are used up and the latest changes are unreviewed "
                            f"({'; '.join(req['delta'])}). Open the PR with --draft and a description that starts "
                            "with `NOT READY:` saying what is unreviewed")
    ledger.log(root, payload, "gate", point="pr", action=action, decision="deny" if problems else "allow",
               tier=req["tier"], missing=[ledger.sanitize(p, 120) for p in problems[:8]])
    if not problems:
        return None
    why = "; ".join(req["classification"]["reasons"][:4]) or "escalated"
    return f"Risk tier {req['tier']} ({why}). Before this PR command can run:\n- " + "\n- ".join(problems)


# --- PreToolUse: no worktrees; advisor before sensitive work goes further ----------------------------------------

_SEPARATORS = frozenset({";", "&&", "||", "|", "&", "(", ")", "\n"})
_PREFIXES = frozenset({"sudo", "env", "command", "exec", "time", "nice", "nohup"})
_GIT_VALUE_OPTIONS = frozenset({"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--super-prefix",
                                "--config-env", "--exec-path"})
_COMMIT_MAKING = frozenset({"commit", "merge", "cherry-pick", "revert", "am", "rebase"})
_HEREDOC = re.compile(r"<<-?\s*(['\"]?)(\w+)\1")


def without_heredoc_bodies(command):
    out, end = [], None
    for line in command.split("\n"):
        if end is not None:
            end = None if line.strip() == end else end
            continue
        out.append(line)
        m = _HEREDOC.search(line)
        end = m.group(2) if m else None
    return "\n".join(out)


def git_subcommands(command):
    """[(subcommand, args)] for every `git` run as a command (not text inside a quoted string or a heredoc)."""
    try:
        lex = shlex.shlex(without_heredoc_bodies(command).replace("\n", " \n "), posix=True,
                          punctuation_chars=";&|()")
        lex.whitespace = " \t\r"
        lex.whitespace_split = True
        tokens = list(lex)
    except ValueError:
        return []
    found, i, start = [], 0, True
    while i < len(tokens):
        t = tokens[i]
        if t in _SEPARATORS:
            start = True
        elif start and (t in _PREFIXES or re.fullmatch(r"\w+=\S*", t)):
            pass
        elif start and os.path.basename(t) == "git":
            j = i + 1
            while j < len(tokens) and tokens[j].startswith("-") and tokens[j] not in _SEPARATORS:
                j += 2 if tokens[j] in _GIT_VALUE_OPTIONS else 1
            k = j
            while k < len(tokens) and tokens[k] not in _SEPARATORS:
                k += 1
            if j < k:
                found.append((tokens[j], tokens[j + 1:k]))
            i, start = k, False
            continue
        else:
            start = False
        i += 1
    return found


EDIT_TOOLS = ("Edit", "Write", "MultiEdit", "NotebookEdit")


def advisor_first(root, payload, point):
    """The reason to stop, while the branch is sensitive and has no `advisor` run yet; None otherwise."""
    events = ledger.events(root)
    branch = ledger._git(root, "rev-parse", "--abbrev-ref", "HEAD")
    if runs(events, branch, "advisor"):
        return None
    req = requirements(root, events=events)
    if req["tier"] != risk.SENSITIVE:
        return None
    ledger.log(root, payload, "gate", point=point, decision="deny", tier=req["tier"], missing=["advisor"])
    why = "; ".join(req["classification"]["reasons"][:4]) or "escalated"
    return (f"Risk tier sensitive ({why}) and no `advisor` run on {branch} yet. Give `advisor` your plan before "
            f"implementing further or committing (CLAUDE.md, Risk lifecycle 1): put the plan in the advisor prompt, "
            f"or write it to a file outside the checkout. {'Edits' if point == 'edit' else 'Commits'} on this "
            f"branch are refused until advisor has run on it (runs count per branch name).")


def tier_marker(root, payload):
    branch = re.sub(r"[^A-Za-z0-9_.-]", "_", ledger._git(root, "rev-parse", "--abbrev-ref", "HEAD") or "HEAD")
    return os.path.join(ledger.state_dir(root), f"tier-{ledger.session_id(payload)}-{branch}")


def session_tier(root, payload):
    try:
        with open(tier_marker(root, payload)) as f:
            return f.read().split(" ", 1)[0]
    except OSError:
        return risk.ORDINARY


def inside(root, path):
    return bool(path) and os.path.realpath(os.path.join(root, path)).startswith(os.path.realpath(root) + os.sep)


def work_gate(payload):
    """None to allow, or the reason to deny: `git worktree add`, and edits or commits on a sensitive branch before
    `advisor` has run. Edits read the session's tier marker first, so ordinary work pays nothing extra."""
    root = ledger.repo_root(payload.get("cwd") or ".")
    if not root:
        return None
    tool, tool_input = payload.get("tool_name"), payload.get("tool_input") or {}
    if tool == "Bash":
        command = str(tool_input.get("command", ""))
        subs = git_subcommands(command)
        if any(sub == "worktree" and args[:1] == ["add"] for sub, args in subs):
            ledger.log(root, payload, "gate", point="worktree", decision="deny")
            return (f"No `git worktree add` here: one session, one checkout ({root}). The review gate and the ledger "
                    "only see this checkout. Switch branches in it; park uncommitted work with `git stash -u`.")
        return advisor_first(root, payload, "commit") if any(sub in _COMMIT_MAKING for sub, _ in subs) else None
    if tool in EDIT_TOOLS:
        path = tool_input.get("file_path") or tool_input.get("notebook_path")
        if inside(root, path) and session_tier(root, payload) == risk.SENSITIVE:
            return advisor_first(root, payload, "edit")
    return None


# --- PostToolUse: reassess the tier while working ----------------------------------------------------------------

def reassess(payload):
    """additionalContext text the first time this session's tier rises, else None. Cheap when nothing changed:
    the marker remembers the tier and the tree it was computed for."""
    root = ledger.repo_root(payload.get("cwd") or ".")
    if not root:
        return None
    marker = tier_marker(root, payload)
    try:
        with open(marker) as f:
            before, _, seen_tree = f.read().strip().partition(" ")
    except OSError:
        before, seen_tree = risk.ORDINARY, ""
    if before == risk.SENSITIVE:
        return None
    tree = ledger.snapshot_tree(root)
    if not tree or tree == seen_tree:
        return None
    res = risk.classify_files(diff_files(root, merge_base(root), tree))
    tier = res["tier"]
    if risk.RANK[tier] <= risk.RANK.get(before, 0):  # escalations can still raise it
        tier = risk.effective(tier, ledger.events(root), ledger._git(root, "rev-parse", "--abbrev-ref", "HEAD"))
    rose = risk.RANK[tier] > risk.RANK.get(before, 0)
    with open(marker, "w") as f:
        f.write(f"{tier if rose else before} {tree}")
    if not rose:
        return None
    ledger.log(root, payload, "risk", tier=tier, previous=before,
               reasons=[ledger.sanitize(r, 120) for r in res["reasons"][:6]])
    why = "; ".join(res["reasons"][:4]) or "escalated"
    if tier == risk.SENSITIVE:
        return (f"Risk is now SENSITIVE ({why}). Before implementing further, consult the `advisor` agent on your "
                "plan; it is required for this branch. Write the ## Risk section as you go. `reviewer` must review "
                "the finished diff before `gh pr create`, and the PR title starts with [sensitive]. See CLAUDE.md "
                "(Risk lifecycle). `ai-risk status` shows what is still missing.")
    return (f"Risk is now REVIEW ({why}). Have the `reviewer` agent review the finished diff before `gh pr create`, "
            "and give every finding a disposition in ## Review. `ai-risk status` shows what is still missing.")


# --- entry points ------------------------------------------------------------------------------------------------

def hook():
    if ledger.shadowed_by_image():
        return 0
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except ValueError:
        return 0
    event = payload.get("hook_event_name")
    try:
        ledger.handle(payload)  # selfcheck logging for Bash `make check` (PostToolUse and PostToolUseFailure)
    except Exception:
        pass
    if not enabled():
        return 0
    try:
        if event == "PreToolUse":
            reason = (pr_gate(payload) if payload.get("tool_name") == "Bash" else None) or work_gate(payload)
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


def cli(argv):
    ap = argparse.ArgumentParser(prog="ai-risk")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("plan").add_argument("paths", nargs="+")
    sub.add_parser("status")
    e = sub.add_parser("escalate")
    e.add_argument("tier", choices=[risk.REVIEW, risk.SENSITIVE])
    e.add_argument("--reason", required=True)
    a = ap.parse_args(argv)
    root = ledger.repo_root(".")
    if not root:
        print("not inside a git repository", file=sys.stderr)
        return 2
    if a.cmd == "escalate":
        ok = ledger.log(root, {}, "risk_escalation", tier=a.tier, reason=ledger.sanitize(a.reason))
        print(f"risk escalated to {a.tier}" + ("" if ok else " (WARNING: ledger write failed)"))
        return 0
    if a.cmd == "plan":
        rel = [os.path.relpath(os.path.abspath(p), root) for p in a.paths]
        res = risk.classify_files([{"path": p, "status": "M" if os.path.exists(os.path.join(root, p)) else "A"}
                                   for p in rel])
        tier = risk.effective(res["tier"], ledger.events(root), ledger._git(root, "rev-parse", "--abbrev-ref", "HEAD"))
        missing = []
    else:
        req = requirements(root)
        res, tier, missing = req["classification"], req["tier"], req["missing"]
    print(f"risk: {tier}" + (f" (escalated from {res['tier']})" if tier != res["tier"] else ""))
    for r in res["reasons"]:
        print(f"  - {r}")
    if a.cmd == "plan":
        print("  (path signals only; the diff can still raise the tier: added routes, Supabase queries in routers, "
              "deletions, environment loading, size, scope)")
    print("required:")
    for s in risk.required_steps(tier):
        print(f"  - {s}")
    for m in missing:
        print(f"still missing: {m}")
    return 0


if __name__ == "__main__":
    sys.exit(cli(sys.argv[1:]) if sys.argv[1:] else hook())
