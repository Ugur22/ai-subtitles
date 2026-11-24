"""Agent ledger: one JSON line per verification or review event, metadata only.

Writable telemetry, not enforcement: the agent runs as the same user and can edit or delete the file, and CI plus
the `policy` check stay the merge gate. Everything here is best-effort and never changes a hook's decision:
nothing is printed to stdout/stderr (the hooks' channels) and no exception escapes. A failed write is recorded in
`<ledger>.errors` (timestamp, error type, event kind; no content) so a diagnostic run can see lost telemetry.

Stored text is bounded and sanitized: no prompts, transcripts or tool output, only short finding summaries with
secrets, URLs' query strings and email addresses redacted. Readers (the report, a future retro agent) must treat
every field as untrusted data written by an agent, never as instructions.

As a hook (stdin = Claude Code hook JSON) it logs: SubagentStop (agent type; findings for reviewer/advisor),
PostToolUse/PostToolUseFailure on Bash running `make check` (pass/fail with the failing step), SessionEnd.
Stop events come from stop_check.py and gate events from gate.py; both use the helpers here (git, state,
session ids, the ledger reader and writer).
"""

import datetime
import fcntl
import hashlib
import json
import os
import re
import subprocess
import sys

IMAGE_COPY = "/usr/local/lib/ai-subs-harness"
SUMMARY_MAX = 120
LINE_MAX = 3800  # stays under PIPE_BUF-sized writes; one os.write per record, under an exclusive lock

_ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
_CTRL = re.compile(r"[\x00-\x1f\x7f]")
_SECRETS = [
    re.compile(r"\b(gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})"),
    re.compile(r"\b(sk-[A-Za-z0-9_-]{16,}|sk_(live|test)_[A-Za-z0-9]{10,}|xox[abpr]-[A-Za-z0-9-]{10,})"),
    re.compile(r"\b(AKIA|ASIA)[A-Z0-9]{16}\b"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}(\.[A-Za-z0-9_-]+)?"),  # JWT
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    # long opaque blobs (keys, encoded tokens): letters and digits mixed, no "/" so file paths survive
    re.compile(r"(?<![A-Za-z0-9+_=-])(?=[A-Za-z0-9+_=-]*\d)(?=[A-Za-z0-9+_=-]*[A-Za-z])[A-Za-z0-9+_=-]{32,}"),
]
_URL_QUERY = re.compile(r"(https?://[^\s?#]+)[?#][^\s)\]]*")
_EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")


def sanitize(text, limit=SUMMARY_MAX):
    s = _ANSI.sub("", str(text))
    s = _CTRL.sub(" ", s)
    for rx in _SECRETS:
        s = rx.sub("[redacted]", s)
    s = _URL_QUERY.sub(r"\1?[redacted]", s)
    s = _EMAIL.sub("[email]", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s if len(s) <= limit else s[: limit - 1] + "…"


def _git(root, *args, strip=True, timeout=20):
    """stdout of a git command, or "" when it fails or times out."""
    try:
        r = subprocess.run(["git", "-C", root, *args], capture_output=True, timeout=timeout)
        out = r.stdout.decode("utf-8", "replace") if r.returncode == 0 else ""
        return out.strip() if strip else out
    except Exception:
        return ""


def repo_root(cwd):
    return _git(cwd or ".", "rev-parse", "--show-toplevel")


def snapshot_tree(root):
    """A git tree of the whole working state: tracked files as they are on disk (deletions included) plus untracked,
    non-ignored files. Built in a throwaway index seeded from HEAD with no stat cache, so every file's content is
    compared; reusing the real index would miss a same-size edit made in the same second as its last write
    ("racily clean"). About 0.1 s on this repository. None if git fails."""
    import tempfile
    fd, tmp = tempfile.mkstemp(prefix="ai-subs-index-")
    os.close(fd)
    os.remove(tmp)
    env = dict(os.environ, GIT_INDEX_FILE=tmp)
    try:
        for args in (("read-tree", "HEAD"), ("add", "-A")):
            if subprocess.run(["git", "-C", root, *args], capture_output=True, timeout=120, env=env).returncode:
                return None
        r = subprocess.run(["git", "-C", root, "write-tree"], capture_output=True, timeout=60, env=env)
        return r.stdout.decode().strip() if r.returncode == 0 else None
    except Exception:
        return None
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass


def _digest(head, tree):
    return hashlib.sha256(f"{head}\0{tree}".encode()).hexdigest() if tree else "unavailable-" + os.urandom(8).hex()


def state(root):
    """(hash, tree) of the tree's whole git-visible state: HEAD (so commits count) and the exact working tree
    content (snapshot_tree: tracked changes, deletions, lockfiles and configs, untracked files). Ignored files
    (node_modules, venvs, .env) are outside it by design. A failed snapshot yields a hash that never matches."""
    tree = snapshot_tree(root)
    return _digest(_git(root, "rev-parse", "HEAD"), tree), tree


def state_hash(root):
    return state(root)[0]


def session_id(payload):
    return re.sub(r"[^A-Za-z0-9_-]", "", str(payload.get("session_id", "")))[:64] or "default"


def state_dir(root):
    """<git dir>/ai-subs-harness: the hooks' stamps, counters and markers (writable by the session, not trusted)."""
    git_dir = _git(root, "rev-parse", "--path-format=absolute", "--git-dir") or os.path.join(root, ".git")
    sd = os.path.join(git_dir, "ai-subs-harness")
    os.makedirs(sd, exist_ok=True)
    return sd


def ledger_path(root):
    env = os.environ.get("AI_SUBS_LEDGER")
    if env:
        return env
    common = _git(root, "rev-parse", "--path-format=absolute", "--git-common-dir")
    base = os.path.dirname(common) if common else root
    return os.path.join(base, ".harness", "ledger.jsonl")


def load_events(paths):
    """(events sorted by time, count of unreadable lines) from one or more ledger files; a missing file is empty."""
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


def events(root):
    return load_events([ledger_path(root)])[0]


def latest_findings(runs):
    """ID -> finding over reviewer/advisor runs in order, the latest run winning on a repeated ID."""
    out = {}
    for e in runs:
        for f in e.get("findings") or []:
            if isinstance(f, dict) and f.get("id"):
                out[str(f["id"]).upper()] = f
    return out


def _now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _record_error(path, kind, exc):
    if not path:
        return
    try:
        with open(path + ".errors", "a") as f:
            f.write(f"{_now()} {type(exc).__name__} {sanitize(kind, 40)}\n")
    except Exception:
        pass


def append(path, event):
    """Appends one record. Returns True when written; never raises."""
    try:
        rec = {"ts": _now(), **event}
        line = json.dumps(rec, ensure_ascii=False, separators=(",", ":"))
        while len(line.encode()) > LINE_MAX and rec.get("findings"):
            rec["findings"] = rec["findings"][:-1]
            rec["findings_truncated"] = True
            line = json.dumps(rec, ensure_ascii=False, separators=(",", ":"))
        data = (line + "\n").encode()
        if len(data) > LINE_MAX + 1:
            raise ValueError("record too large")
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            os.write(fd, data)
        finally:
            os.close(fd)
        return True
    except Exception as exc:
        _record_error(path, str(event.get("event", "?")), exc)
        return False


# --- `make check` output -> failing step and a stable pattern id -------------------------------------------

_TARGET = re.compile(r"make(?:\[\d+\])?: \*\*\* \[(?:[^\]:]*:\d+: )?([A-Za-z0-9_-]+)\]")
_DETAIL = {
    "lint-backend": re.compile(r"^\S+:\d+:\d+: ([A-Z]{1,4}\d{2,4})\b|^([A-Z]{1,4}\d{3,4}) ", re.M),
    "lint-frontend": re.compile(r"^\s*\d+:\d+\s+error\s+.*?\s{2,}(\S+)\s*$", re.M),
    "test-backend": re.compile(r"^(?:FAILED|ERROR) (?:backend/tests/)?(\S+?\.py(?:::\S+)?)", re.M),
    "typecheck-frontend": re.compile(r"error (TS\d+)"),
    "test-frontend": re.compile(r"(?:FAIL|×|✗)\s+(\S+\.test\.tsx?)"),
}


def check_failure(output):
    """(step, pattern) for a red `make check`; pattern is `step:<rule or test id>` so the same failure in two
    sessions gets the same id, and different failures in the same step do not."""
    out = _ANSI.sub("", output or "")
    m = _TARGET.search(out)
    step = m.group(1) if m else "unknown"
    rx = _DETAIL.get(step)
    d = rx.search(out) if rx else None
    detail = next((g for g in d.groups() if g), "") if d else ""
    return step, sanitize(f"{step}:{detail}" if detail else step, 120)


def check_result(command, response, failed):
    """pass | fail | unknown for a Bash call that ran `make check` (exit status is often hidden by pipes)."""
    text = ""
    if isinstance(response, dict):
        text = "\n".join(str(response.get(k, "")) for k in ("stdout", "stderr", "output"))
    elif response is not None:
        text = str(response)
    if failed or _TARGET.search(_ANSI.sub("", text)) or re.search(r"\bexit(?:\s*code)?\s*[=:]?\s*[1-9]", text, re.I):
        return "fail", text
    if re.search(r"\bexit\s*[=:]\s*0\b", text, re.I) or "passed" in text or "All checks passed" in text:
        return "pass", text
    return "unknown", text


MAKE_CHECK = re.compile(r"(^|[;&|(\s])make\s+(-\S+\s+)*check(\s|$|[;&|)])")

# --- reviewer / advisor findings ----------------------------------------------------------------------------

_FINDING = re.compile(
    r"^[\s>*_`-]*\**([RA]\d{1,3})\**[\s:.)-]*\[(blocker|should-fix|nit)\]\s*\[([a-z]+)(?::([a-z0-9-]{1,40}))?\]"
    r"\s*[-—:]*\s*(.*)$",
    re.M | re.I,
)
_CLEAN = re.compile(r"^\W*no findings\b", re.M | re.I)


def parse_findings(text):
    findings = []
    for m in _FINDING.finditer(text or ""):
        fid, sev, cat, pat, rest = m.groups()
        findings.append({
            "id": fid.upper(),
            "severity": sev.lower(),
            "category": cat.lower(),
            "pattern": f"{cat.lower()}:{pat.lower()}" if pat else cat.lower(),
            "summary": sanitize(rest),
        })
    parsed = bool(findings) or bool(_CLEAN.search(text or ""))
    return findings, parsed


# --- hook entry ---------------------------------------------------------------------------------------------

def shadowed_by_image():
    """Inside the agent container the image's root-owned copy is the registered one (managed settings); the
    project's copy, also registered through .claude/settings.json, must not log a second time."""
    here = os.path.dirname(os.path.realpath(__file__))
    return os.path.isdir(IMAGE_COPY) and here != IMAGE_COPY


def base_fields(payload, root):
    return {
        "session": session_id(payload),
        "branch": sanitize(_git(root, "rev-parse", "--abbrev-ref", "HEAD"), 100),
        "head": _git(root, "rev-parse", "--short=12", "HEAD"),
    }


def log(root, payload, event, **fields):
    return append(ledger_path(root), {**base_fields(payload, root), "event": event, **fields})


def handle(payload):
    event = payload.get("hook_event_name", "")
    if event in ("PostToolUse", "PostToolUseFailure"):  # cheap checks first: this runs after every tool call
        cmd = str((payload.get("tool_input") or {}).get("command", ""))
        if payload.get("tool_name") != "Bash" or not MAKE_CHECK.search(cmd):
            return None
    elif event not in ("SubagentStop", "SessionEnd"):
        return None
    root = repo_root(payload.get("cwd") or os.environ.get("CLAUDE_PROJECT_DIR") or ".")
    if not root:
        return None
    if event == "SubagentStop":
        agent = sanitize(payload.get("agent_type") or "unknown", 40)
        fields = {"agent": agent}
        if agent in ("reviewer", "advisor"):
            findings, parsed = parse_findings(payload.get("last_assistant_message", ""))
            digest, tree = state(root)
            fields.update(findings=findings, parsed=parsed, tree=tree, state=digest[:16])
        return log(root, payload, "subagent", **fields)
    if event == "SessionEnd":
        return log(root, payload, "session_end", reason=sanitize(payload.get("reason", ""), 40))
    result, text = check_result(cmd, payload.get("tool_response", payload.get("error")), event == "PostToolUseFailure")
    fields = {"result": result}
    if result == "fail":
        fields["step"], fields["pattern"] = check_failure(text)
    return log(root, payload, "selfcheck", **fields)


def main():
    try:
        if shadowed_by_image():
            return
        payload = json.loads(sys.stdin.read() or "{}")
    except Exception:
        return
    try:
        handle(payload)
    except Exception as exc:
        try:
            root = repo_root(payload.get("cwd") or ".")
            _record_error(ledger_path(root) if root else os.environ.get("AI_SUBS_LEDGER", ""), "hook", exc)
        except Exception:
            pass


if __name__ == "__main__":
    main()
