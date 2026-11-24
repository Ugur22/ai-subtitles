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
Stop events come from stop_check.py, which imports this module.
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


def _git(root, *args):
    try:
        r = subprocess.run(["git", "-C", root, *args], capture_output=True, timeout=20)
        return r.stdout.decode("utf-8", "replace").strip() if r.returncode == 0 else ""
    except Exception:
        return ""


def repo_root(cwd):
    return _git(cwd or ".", "rev-parse", "--show-toplevel")


def state_hash(root):
    """The tree's whole git-visible state: HEAD (so commits count), every tracked change against HEAD (staged or
    not, deletions included, lockfiles and configs included) and every untracked file's name and content.
    Ignored files (node_modules, venvs, .env) are outside it by design."""
    h = hashlib.sha256()
    for args in (("rev-parse", "HEAD"), ("diff", "HEAD", "--binary", "--no-ext-diff", "--no-textconv")):
        r = subprocess.run(["git", "-C", root, *args], capture_output=True, timeout=60)
        h.update(r.stdout + b"\0" + str(r.returncode).encode() + b"\0")
    r = subprocess.run(["git", "-C", root, "ls-files", "-z", "-o", "--exclude-standard"], capture_output=True, timeout=60)
    for name in sorted(n for n in r.stdout.split(b"\0") if n):
        h.update(b"U\0" + name + b"\0")
        try:
            with open(os.path.join(root.encode(), name), "rb") as f:
                h.update(hashlib.sha256(f.read()).digest())
        except OSError:
            h.update(b"unreadable")
    return h.hexdigest()


def ledger_path(root):
    env = os.environ.get("AI_SUBS_LEDGER")
    if env:
        return env
    common = _git(root, "rev-parse", "--path-format=absolute", "--git-common-dir")
    base = os.path.dirname(common) if common else root
    return os.path.join(base, ".harness", "ledger.jsonl")


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
        "session": re.sub(r"[^A-Za-z0-9_-]", "", str(payload.get("session_id", "")))[:64],
        "branch": sanitize(_git(root, "rev-parse", "--abbrev-ref", "HEAD"), 100),
        "head": _git(root, "rev-parse", "--short=12", "HEAD"),
    }


def handle(payload):
    event = payload.get("hook_event_name", "")
    root = repo_root(payload.get("cwd") or os.environ.get("CLAUDE_PROJECT_DIR") or ".")
    if not root:
        return None
    rec = base_fields(payload, root)
    if event == "SubagentStop":
        agent = sanitize(payload.get("agent_type") or "unknown", 40)
        rec.update(event="subagent", agent=agent)
        if agent in ("reviewer", "advisor"):
            findings, parsed = parse_findings(payload.get("last_assistant_message", ""))
            rec.update(findings=findings, parsed=parsed, state=state_hash(root)[:16])
    elif event in ("PostToolUse", "PostToolUseFailure") and payload.get("tool_name") == "Bash":
        cmd = str((payload.get("tool_input") or {}).get("command", ""))
        if not MAKE_CHECK.search(cmd):
            return None
        failed = event == "PostToolUseFailure"
        result, text = check_result(cmd, payload.get("tool_response", payload.get("error")), failed)
        rec.update(event="selfcheck", result=result)
        if result == "fail":
            rec["step"], rec["pattern"] = check_failure(text)
    elif event == "SessionEnd":
        rec.update(event="session_end", reason=sanitize(payload.get("reason", ""), 40))
    else:
        return None
    return append(ledger_path(root), rec)


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
