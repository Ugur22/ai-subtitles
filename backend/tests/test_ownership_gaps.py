"""Known gaps in the ownership invariants, tracked as open follow-ups.

Each gap has two tests:
- a strict xfail stating the invariant. It starts passing once the gap is fixed,
  which fails the suite until the marker is removed.
- a companion that pins today's behaviour (no crash, the answer the gap
  describes), so a broken fake or a 500 can't pass for the known gap.

None of these leaks data to a caller without a capability: (a) needs a job id,
and (b) needs the job's random share token. The fakes and fixtures come from
tests/invariants/test_ownership.py, loaded under its own module name.
"""

import importlib.util
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location(
    "ownership_invariants_for_gaps",
    Path(__file__).parent / "invariants" / "test_ownership.py",
)
inv = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(inv)

app = inv.app
world = inv.world


def _gap(reason):
    return pytest.mark.xfail(strict=True, raises=AssertionError, reason=reason)


# (a) Existence oracle: these routes answer 403, not 404, for a job that exists but is not B's.
ORACLE = [
    pytest.param("/api/jobs/job-a", id="get", marks=_gap(
        "GET /api/jobs/{id} uses require_job_access, which answers 403 'Access denied' for "
        "another user's job and 404 only for a missing one, so a guessed id is confirmed")),
    pytest.param("/api/jobs/job-a/video_url", id="video-url", marks=_gap(
        "GET /api/jobs/{id}/video_url uses require_job_access: 403 for another user's job "
        "confirms that the id exists")),
    pytest.param("/api/jobs/job-a/video_url?token=tok-share-b", id="video-url-with-b-token", marks=_gap(
        "GET /api/jobs/{id}/video_url with a token of another job still answers 403 from "
        "require_job_access, confirming the id exists")),
    pytest.param(f"/api/jobs/job-a/screenshot_url?gcs_path={inv.A_SHOT}", id="screenshot-url", marks=_gap(
        "GET /api/jobs/{id}/screenshot_url uses require_job_access: 403 for another user's "
        "job confirms that the id exists")),
]


@pytest.mark.parametrize("path", ORACLE)
def test_gap_b_gets_404_for_a_job(app, world, path):
    assert inv.call(app, "GET", path, cookie="tok-user-b").status_code == 404


@pytest.mark.parametrize("path", [p.values[0] for p in ORACLE], ids=[p.id for p in ORACLE])
def test_gap_today_b_gets_403_for_a_job(app, world, path):
    response = inv.call(app, "GET", path, cookie="tok-user-b")

    assert response.status_code == 403, response.text
    assert inv.leaked(response, inv.A_SECRETS) == []


# (b) An ownerless job's share token still grants read access.
ORPHAN_TOKEN_REASON = (
    "{route} checks only the share token, not the owner, so the token of a job whose "
    "owner is null still {what}"
)
ORPHAN_TOKEN_ROUTES = [
    ("/api/jobs/job-orphan/download/srt?token=tok-share-orphan", "download",
     "GET /api/jobs/{id}/download/{format}", "returns its transcript"),
    ("/api/jobs/job-orphan/video?token=tok-share-orphan", "video",
     "GET /api/jobs/{id}/video", "redirects to a signed URL for its media"),
    ("/api/jobs/job-orphan/video_url?token=tok-share-orphan", "video-url",
     "GET /api/jobs/{id}/video_url", "returns a signed URL for its media"),
]
ORPHAN_TOKEN = [
    pytest.param(path, cookie, id=f"{name}-{who}", marks=_gap(
        ORPHAN_TOKEN_REASON.format(route=route, what=what) + f" ({who})"))
    for path, name, route, what in ORPHAN_TOKEN_ROUTES
    for cookie, who in ((None, "no session"), ("tok-user-b", "with B's session"))
]


@pytest.mark.parametrize("path,cookie", ORPHAN_TOKEN)
def test_gap_ownerless_job_share_token_grants_no_access(app, world, path, cookie):
    response = inv.call(app, "GET", path, cookie=cookie)

    assert 400 <= response.status_code < 500
    assert inv.leaked(response, inv.ORPHAN_SECRETS) == []
    assert world.storage.signed == []


@pytest.mark.parametrize("path,cookie", [p.values for p in ORPHAN_TOKEN], ids=[p.id for p in ORPHAN_TOKEN])
def test_gap_today_ownerless_job_share_token_works(app, world, path, cookie):
    response = inv.call(app, "GET", path, cookie=cookie)

    assert response.status_code in (200, 302), response.text
    assert world.storage.signed or "ORPHAN-SECRET-SRT" in response.text
