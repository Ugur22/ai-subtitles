"""Tests of the ratchet machinery itself (the rules come with their own tests)."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import ratchet  # noqa: E402
import run_mutations  # noqa: E402
import tighten  # noqa: E402


def baseline(tmp_path, rules):
    p = tmp_path / "baseline.json"
    p.write_text(json.dumps({"version": 1, "rules": rules}))
    return p


def test_fingerprints_name_one_violation_not_a_file():
    a = ratchet.fingerprint("backend/x.py", "  import   torch ", "load")
    assert a == "backend/x.py::load::import torch"
    assert ratchet.fingerprint("frontend/src/a.ts", "setInterval(f,  1000)") == "frontend/src/a.ts::setInterval(f, 1000)"
    assert a != ratchet.fingerprint("backend/x.py", "import torch", "other")


def test_a_known_exception_does_not_cover_a_second_violation_in_the_same_file(tmp_path):
    p = baseline(tmp_path, {"heavy": {"allow": {"x.py::f::import torch": "legacy loader"}}})
    current = {"x.py::f::import torch": "ok", "x.py::g::import torch": "new"}
    with pytest.raises(AssertionError, match=r"(?s)1 new violation.*x\.py::g::import torch"):
        ratchet.assert_no_new("heavy", current, "Import it inside the function.", p)
    ratchet.assert_no_new("heavy", {"x.py::f::import torch": "ok"}, "", p)


def test_stale_exceptions_warn_but_never_fail(tmp_path):
    p = baseline(tmp_path, {"heavy": {"allow": {"x.py::f::import torch": "legacy loader"}}})
    with pytest.warns(UserWarning, match="1 stale exception"):
        ratchet.assert_no_new("heavy", {}, "", p)


def test_tighten_only_removes_and_add_needs_a_reason(tmp_path):
    p = baseline(tmp_path, {"r": {"allow": {"keep": "still there", "gone": "fixed since"}}})
    removed = tighten.tighten(p, {"r": lambda root: {"keep": "x", "brand-new": "x"}}, tmp_path)
    assert removed == ["r: gone"]
    assert ratchet.allowed("r", p) == {"keep": "still there"}, "a new violation is never added by tightening"
    with pytest.raises(SystemExit):
        tighten.add("r", "fp", "ok", p)
    tighten.add("r", "fp", "the webhook verifies a signature instead", p)
    assert ratchet.allowed("r", p)["fp"] == "the webhook verifies a signature instead"


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "repo"
    r.mkdir()
    (r / "guard.py").write_text("def allowed(user, owner):\n    return user == owner\n")
    (r / "test_guard.py").write_text(
        "from guard import allowed\n\ndef test_other_user_denied():\n    assert not allowed('b', 'a')\n")
    env = dict(os.environ, GIT_CONFIG_GLOBAL="/dev/null", GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
               GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
    for args in (["init", "-q"], ["add", "."], ["commit", "-qm", "i"]):
        subprocess.run(["git", "-C", str(r), *args], check=True, capture_output=True, env=env)
    return r


def mutation(**kw):
    m = {"id": "m", "file": "guard.py", "find": "user == owner", "replace": "True",
         "test": ["{python}", "-m", "pytest", "-q", "-p", "no:cacheprovider", "test_guard.py"]}
    m.update(kw)
    return m


def test_mutation_killed_survived_stale_broken_and_restored(repo):
    original = (repo / "guard.py").read_text()
    assert run_mutations.check(mutation(), repo) == ("killed", "")
    assert (repo / "guard.py").read_text() == original, "the file is restored"
    assert run_mutations.check(mutation(replace="user == owner or False"), repo)[0] == "survived"
    assert run_mutations.check(mutation(find="user != owner"), repo)[0] == "stale"
    (repo / "test_guard.py").write_text("def test_broken():\n    assert False\n")
    subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qam", "b"],
                   check=True, capture_output=True)
    assert run_mutations.check(mutation(), repo)[0] == "broken"


def test_mutation_refuses_a_file_with_local_changes(repo):
    (repo / "guard.py").write_text("def allowed(user, owner):\n    return user == owner  # wip\n")
    assert run_mutations.check(mutation(), repo)[0] == "dirty"
    assert "wip" in (repo / "guard.py").read_text()


def test_runner_exit_code(repo, tmp_path, capsys):
    good = tmp_path / "good.json"
    good.write_text(json.dumps({"mutations": [mutation()]}))
    assert run_mutations.main(["--file", str(good), "--root", str(repo)]) == 0
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"mutations": [mutation(), mutation(id="weak", replace="user == owner or False")]}))
    assert run_mutations.main(["--file", str(bad), "--root", str(repo)]) == 1
    assert "FAIL weak: survived" in capsys.readouterr().out


def test_shipped_files_are_well_formed():
    assert isinstance(ratchet.load(), dict)
    for m in json.loads((HERE / "mutations.json").read_text())["mutations"]:
        assert {"id", "file", "find", "replace", "test", "why"} <= set(m), m.get("id")
