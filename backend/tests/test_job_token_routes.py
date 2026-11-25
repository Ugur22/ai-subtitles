"""The share-token routes' designed answers to a caller without A's token.

/download/{format} and /video authorize by share token only: 400 when no token
is given, 403 for a token of another job. This is the current contract, not an
ownership invariant (a later change may answer 404 instead), so it lives outside
tests/invariants/. That nothing of A's leaks is guaranteed there.
"""

import importlib.util
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location(
    "ownership_invariants_for_token_routes",
    Path(__file__).parent / "invariants" / "test_ownership.py",
)
inv = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(inv)

app = inv.app
world = inv.world


@pytest.mark.parametrize("cookie", ["tok-user-b", None], ids=["b", "anonymous"])
@pytest.mark.parametrize("path,status", [
    ("/api/jobs/job-a/download/srt", 400),
    ("/api/jobs/job-a/download/json", 400),
    ("/api/jobs/job-a/video", 400),
    ("/api/jobs/job-a/download/srt?token=tok-share-b", 403),
    ("/api/jobs/job-a/download/json?token=tok-share-b", 403),
    ("/api/jobs/job-a/video?token=tok-share-b", 403),
])
def test_token_routes_answer_400_without_token_and_403_with_another_jobs_token(app, world, cookie, path, status):
    response = inv.call(app, "GET", path, cookie=cookie)

    assert response.status_code == status, response.text
    assert inv.leaked(response, inv.A_SECRETS) == []
    assert world.storage.signed == []
