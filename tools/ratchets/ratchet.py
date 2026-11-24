"""Ratchets: engineering rules that may not get worse. Owner-only (a guard path in tools/policy/check_pr.py).

A rule's collect(root) returns {fingerprint: detail} for every current violation. A fingerprint names one
violation, not a file: `path::enclosing function::normalised line` for Python, `path::normalised line` for
TypeScript. baseline.json lists the violations that existed when the rule was introduced, each with a reason.

- A violation not in the baseline fails the rule: an existing exception never covers a second one in the same
  file, because the second has its own fingerprint.
- A baseline entry that no longer matches anything is stale. It is reported, not failed, so a change that fixes a
  violation never has to edit this owner-only file. The owner removes stale entries with tighten.py, which can
  only remove; adding an exception is a separate, explicit owner action with a reason.

Local `make check` and CI run the same files; agent PRs can't change them (the policy check), so CI always
judges with main's rules.
"""

import json
import re
import warnings
from pathlib import Path

BASELINE = Path(__file__).with_name("baseline.json")


def normalise(line):
    return re.sub(r"\s+", " ", line).strip()


def fingerprint(path, line, function=None):
    parts = [str(path), function, normalise(line)] if function is not None else [str(path), normalise(line)]
    return "::".join(parts)


def load(path=BASELINE):
    data = json.loads(Path(path).read_text())
    return data.get("rules", {})


def allowed(rule, path=BASELINE):
    return dict(load(path).get(rule, {}).get("allow", {}))


def compare(rule, current, path=BASELINE):
    """(new violations, stale exceptions) for a rule, both sorted."""
    allow = allowed(rule, path)
    return sorted(set(current) - set(allow)), sorted(set(allow) - set(current))


def assert_no_new(rule, current, how_to_fix, path=BASELINE):
    """For a rule's test: fail on new violations, warn on stale exceptions."""
    new, stale = compare(rule, current, path)
    if stale:
        warnings.warn(f"ratchet {rule}: {len(stale)} stale exception(s), the owner can remove them with "
                      f"`make ratchet-tighten`: " + "; ".join(stale[:5]), stacklevel=2)
    if new:
        details = "\n".join(f"  - {fp}: {current[fp]}" for fp in new)
        raise AssertionError(f"ratchet {rule}: {len(new)} new violation(s)\n{details}\n{how_to_fix}\n"
                             "The baseline (tools/ratchets/baseline.json) is the owner's; don't edit it to pass.")
