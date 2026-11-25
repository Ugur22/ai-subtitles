"""Mutation controls: proof that a critical test catches the bug it exists for (`make mutation-check`, CI job
`mutation-controls`). Owner-only, like the rest of tools/ratchets.

mutations.json lists named mutations: {id, file, find, replace, test: [argv...], cwd?, why}. For each one:
1. the test must pass on the unmodified code (otherwise it's broken, not protective);
2. `find` must occur exactly once in `file` (otherwise the control is stale and must be updated);
3. with `find` replaced by `replace`, the test must FAIL. A mutation the test survives means the test does not
   prove what it claims.
The file is restored afterwards, also on errors and Ctrl-C; the run refuses to touch a file with local changes.
`{python}` in a test command is this interpreter. Exit 1 when any control is stale, broken or survived.
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MUTATIONS = Path(__file__).with_name("mutations.json")
TIMEOUT = 600


def run(cmd, cwd):
    argv = [sys.executable if a == "{python}" else a for a in cmd]
    try:
        r = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, timeout=TIMEOUT)
        return r.returncode, (r.stdout + r.stderr)[-2000:]
    except subprocess.TimeoutExpired:
        return 124, f"timed out after {TIMEOUT}s"


def dirty(root, rel):
    r = subprocess.run(["git", "-C", str(root), "status", "--porcelain", "--", rel], capture_output=True, text=True)
    return bool(r.stdout.strip())


def check(m, root, unmutated_results=None):
    """(status, detail): killed | survived | stale | broken | dirty."""
    path = root / m["file"]
    cwd = root / m.get("cwd", ".")
    if dirty(root, m["file"]):
        return "dirty", f"{m['file']} has local changes; commit or stash them first"
    original = path.read_text() if path.exists() else None
    if original is None or original.count(m["find"]) != 1:
        n = 0 if original is None else original.count(m["find"])
        return "stale", f"`find` occurs {n} times in {m['file']} (needs exactly 1)"
    cache = {} if unmutated_results is None else unmutated_results
    key = (tuple(m["test"]), str(cwd))
    if key not in cache:
        cache[key] = run(m["test"], cwd)
    code, out = cache[key]
    if code != 0:
        return "broken", f"the test fails without the mutation:\n{out}"
    try:
        path.write_text(original.replace(m["find"], m["replace"], 1))
        code, out = run(m["test"], cwd)
    finally:
        path.write_text(original)
    return ("killed", "") if code != 0 else ("survived", "the test still passes with the protection removed")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", default=str(MUTATIONS))
    ap.add_argument("--root", default=str(ROOT))
    ap.add_argument("--only", help="run one mutation by id")
    a = ap.parse_args(argv)
    mutations = json.loads(Path(a.file).read_text()).get("mutations", [])
    if a.only:
        mutations = [m for m in mutations if m["id"] == a.only]
    root, bad, unmutated_results = Path(a.root), 0, {}
    for m in mutations:
        status, detail = check(m, root, unmutated_results)
        ok = status == "killed"
        bad += not ok
        print(f"{'PASS' if ok else 'FAIL'} {m['id']}: {status}" + (f" - {detail}" if detail else ""))
    print(f"mutation controls: {len(mutations)} run, {bad} failed")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
