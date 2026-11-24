"""Owner tool for tools/ratchets/baseline.json (`make ratchet-tighten`).

  tighten.py                                   remove stale exceptions of every registered rule (never adds)
  tighten.py --rule R --add FP --reason TEXT   add one exception, with a reason (an explicit owner decision)

Rules register a collector in RULES (rule name -> module:function returning {fingerprint: detail}).
"""

import argparse
import importlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ratchet  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
RULES = {}  # rule name -> "module:function", filled as rules are added (D2, D3)


def collector(spec):
    module, func = spec.split(":")
    return getattr(importlib.import_module(module), func)


def save(rules, path):
    data = {"version": 1, "rules": {r: {"allow": dict(sorted(v.get("allow", {}).items()))} for r, v in sorted(rules.items())}}
    Path(path).write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def tighten(path=ratchet.BASELINE, registry=None, root=ROOT):
    registry = RULES if registry is None else registry
    rules = ratchet.load(path)
    removed = []
    for rule, spec in registry.items():
        current = collector(spec)(root) if isinstance(spec, str) else spec(root)
        _, stale = ratchet.compare(rule, current, path)
        for fp in stale:
            rules[rule]["allow"].pop(fp)
            removed.append(f"{rule}: {fp}")
    save(rules, path)
    return removed


def add(rule, fp, reason, path=ratchet.BASELINE):
    if len(reason.strip()) < 10:
        raise SystemExit("--reason must say why this exception is acceptable")
    rules = ratchet.load(path)
    rules.setdefault(rule, {"allow": {}})["allow"][fp] = reason.strip()
    save(rules, path)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--rule")
    ap.add_argument("--add")
    ap.add_argument("--reason", default="")
    a = ap.parse_args(argv)
    if a.add:
        if not a.rule:
            raise SystemExit("--add needs --rule")
        add(a.rule, a.add, a.reason)
        print(f"added to {a.rule}: {a.add}")
        return 0
    removed = tighten()
    print("\n".join(f"removed {r}" for r in removed) or "no stale exceptions")
    return 0


if __name__ == "__main__":
    sys.exit(main())
