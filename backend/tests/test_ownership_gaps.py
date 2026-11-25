"""Known gaps in the ownership invariants, tracked as open follow-ups.

Each open gap has two tests:
- a strict xfail stating the invariant. It starts passing once the gap is fixed,
  which fails the suite until the marker is removed.
- a companion that pins today's behaviour (no crash, the answer the gap
  describes), so a broken fake or a 500 can't pass for the known gap.

Gap (a), the existence oracle, is fixed; its tests stay below as regular tests.
Gap (b) leaks nothing to a caller without a capability: it needs the job's random
share token. The fakes and fixtures come from
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


# (a) Existence oracle, fixed: require_job_access answers a caller who is neither the
# owner nor holding the job's share token with the same 404 as for a missing job.
# Kept here next to gap (b) so the fixed gap stays visible; the cases are the former
# strict xfails plus anonymous callers and foreign tokens.
SHOT = f"gcs_path={inv.A_SHOT}"
DENIED = [
    pytest.param("/api/jobs/job-a", "tok-user-b", id="get"),
    pytest.param("/api/jobs/job-a?token=tok-share-b", "tok-user-b", id="get-with-b-token"),
    pytest.param("/api/jobs/job-a/video_url", "tok-user-b", id="video-url"),
    pytest.param("/api/jobs/job-a/video_url", None, id="video-url-anonymous"),
    pytest.param("/api/jobs/job-a/video_url?token=tok-share-b", "tok-user-b", id="video-url-with-b-token"),
    pytest.param("/api/jobs/job-a/video_url?token=tok-share-b", None, id="video-url-with-b-token-anonymous"),
    pytest.param(f"/api/jobs/job-a/screenshot_url?{SHOT}", "tok-user-b", id="screenshot-url"),
    pytest.param(f"/api/jobs/job-a/screenshot_url?{SHOT}", None, id="screenshot-url-anonymous"),
    pytest.param(f"/api/jobs/job-a/screenshot_url?{SHOT}&token=tok-share-b", None,
                 id="screenshot-url-with-b-token-anonymous"),
]


@pytest.mark.parametrize("path,cookie", DENIED)
def test_denied_job_is_404(app, world, path, cookie):
    response = inv.call(app, "GET", path, cookie=cookie)

    assert response.status_code == 404, response.text
    assert inv.leaked(response, inv.A_SECRETS) == []
    assert world.storage.signed == []


@pytest.mark.parametrize("path,cookie", DENIED)
def test_denied_job_answers_exactly_like_a_missing_job(app, world, path, cookie):
    denied = inv.call(app, "GET", path, cookie=cookie)
    missing = inv.call(app, "GET", path.replace("/api/jobs/job-a", "/api/jobs/job-missing", 1), cookie=cookie)

    assert missing.status_code == 404, missing.text
    assert (denied.status_code, denied.json()) == (missing.status_code, missing.json())


# Positive controls: the same routes still answer 200 to the owner and to a valid share
# token, so the 404s above can't come from a broken fake or an unmatched route.
ALLOWED = [
    pytest.param("/api/jobs/job-a", "tok-user-a", id="get-owner"),
    pytest.param("/api/jobs/job-a?token=tok-share-a", "tok-user-b", id="get-share-token"),
    pytest.param("/api/jobs/job-a/video_url", "tok-user-a", id="video-url-owner"),
    pytest.param("/api/jobs/job-a/video_url?token=tok-share-a", None, id="video-url-share-token"),
    pytest.param(f"/api/jobs/job-a/screenshot_url?{SHOT}", "tok-user-a", id="screenshot-url-owner"),
    pytest.param(f"/api/jobs/job-a/screenshot_url?{SHOT}&token=tok-share-a", None,
                 id="screenshot-url-share-token"),
]


@pytest.mark.parametrize("path,cookie", ALLOWED)
def test_owner_and_share_token_still_get_a_job(app, world, path, cookie):
    response = inv.call(app, "GET", path, cookie=cookie)

    assert response.status_code == 200, response.text


@pytest.mark.parametrize("job_id", ["job-a", "job-missing"])
def test_get_job_without_session_is_401_whether_or_not_the_job_exists(app, world, job_id):
    response = inv.call(app, "GET", f"/api/jobs/{job_id}?token=tok-share-a")

    assert response.status_code == 401, response.text


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
