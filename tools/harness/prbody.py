"""The two PR description sections agent PRs must get right, parsed the same way by the local PR gate (gate.py)
and by the trusted policy check (tools/policy/check_pr.py). Stdlib only; the input is untrusted text.

## Risk (sensitive changes), one line per field:
  - Impact: / - Verification: / - Rollback: / - Reversibility: / - Uncertainty:
  Reversibility starts with code-only, rollback migration, data repair or irreversible.

## Review, one line per reviewer/advisor finding, or the line `No findings.`:
  - R1 [should-fix] fixed: <commit or what changed>
  - R2 [nit] rejected: <evidence>
  - A1 [should-fix] deferred: <reason and follow-up>
  A blocker can't be deferred. Every disposition needs a justification after the colon.
"""

import re

RISK_FIELDS = ("Impact", "Verification", "Rollback", "Reversibility", "Uncertainty")
REVERSIBILITY = ("code-only", "rollback migration", "data repair", "irreversible")
SEVERITIES = ("blocker", "should-fix", "nit")
ACTIONABLE = ("blocker", "should-fix")
DISPOSITIONS = ("fixed", "rejected", "deferred")

_DISPOSITION = re.compile(
    rf"^\s*[-*]\s*\**([RA]\d{{1,3}})\**\s*\[({'|'.join(SEVERITIES)})\]\s*\**({'|'.join(DISPOSITIONS)})\**\s*:\s*(.*?)\s*$",
    re.I,
)
_ID_ITEM = re.compile(r"^\s*[-*]\s*\**[RA]\d{1,3}\b")
_NO_FINDINGS = re.compile(r"^\s*[-*]?\s*No findings\.?\s*$", re.I | re.M)
MIN_JUSTIFICATION = 8


def section(body, name):
    m = re.search(rf"^##[ \t]*{name}\b[^\n]*\n(.*?)(?=^##[ \t]|\Z)", body or "", re.M | re.S | re.I)
    return m.group(1) if m else None


def risk_problems(body):
    s = section(body, "Risk")
    if s is None:
        return ["## Risk section is missing"]
    out = []
    for field in RISK_FIELDS:
        m = re.search(rf"^\s*[-*]\s*\**{field}\**\s*:\**\s*(.+)$", s, re.M | re.I)
        value = m.group(1).strip() if m else ""
        if len(value) < 3:
            out.append(f"## Risk: '{field}:' is missing or empty")
        elif field == "Reversibility" and not value.lower().lstrip("*_` ").startswith(REVERSIBILITY):
            out.append(f"## Risk: Reversibility must start with one of: {', '.join(REVERSIBILITY)}")
    return out


def dispositions(body):
    """(id -> {severity, disposition, justification}, problems). None for the map when there is no section."""
    s = section(body, "Review")
    if s is None:
        return None, ["## Review section is missing"]
    found, problems = {}, []
    for line in s.splitlines():
        if not _ID_ITEM.match(line):
            continue
        m = _DISPOSITION.match(line)
        if not m:
            problems.append(f"## Review: not in the required form '- R1 [severity] fixed|rejected|deferred: why': "
                            f"{line.strip()[:80]}")
            continue
        fid, sev, disp, why = m.group(1).upper(), m.group(2).lower(), m.group(3).lower(), m.group(4)
        if fid in found:
            problems.append(f"## Review: {fid} is listed twice")
        found[fid] = {"severity": sev, "disposition": disp, "justification": why}
        if len(why.strip()) < MIN_JUSTIFICATION:
            problems.append(f"## Review: {fid} {disp} needs a justification after the colon")
        if sev == "blocker" and disp == "deferred":
            problems.append(f"## Review: {fid} is a blocker and can't be deferred; fix it or reject it with evidence")
    if not found and not _NO_FINDINGS.search(s):
        problems.append("## Review: list every finding with its disposition, or write 'No findings.'")
    return found, problems


def problems(tier, title, body):
    """What the description of an agent PR of this tier (risk.ORDINARY/REVIEW/SENSITIVE as strings) gets wrong.
    Ordinary PRs need nothing, but a ## Review they do have must be well-formed. Title None: not checked."""
    if tier == "ordinary":
        return [p for p in dispositions(body)[1] if "No findings" not in p] if section(body, "Review") is not None else []
    out = list(dispositions(body)[1])
    if tier == "sensitive":
        if title is not None and "[sensitive]" not in title.lower():
            out.append("the title must start with [sensitive]")
        out += risk_problems(body)
    return out
