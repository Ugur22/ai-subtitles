"""Endpoints are called through their registered wrapper so FastAPI's body validation (which runs before the
wrapper and would answer 422) doesn't hide the auth decision."""

import asyncio
import inspect
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent)]
import ratchet  # noqa: E402
import route_access  # noqa: E402

RULE = "route-access"
FIX = ("Protect the route with @require_auth or @require_admin (backend/middleware/auth.py). If it must be reachable "
       "without a session (a public flow, a share token, a signed webhook), the owner classifies it in the baseline.")
GRANTED = "granted"
INTERNAL_KEY = "internal-test-key"
DEFAULTS = {"job_id": "job-a", "format": "srt"}


class AccessGranted(Exception):
    pass



USERS = {
    "tok-user-a": {"id": "user-a", "email": "a@test", "email_confirmed_at": "2026-01-01T00:00:00Z"},
    "tok-user-b": {"id": "user-b", "email": "b@test", "email_confirmed_at": "2026-01-01T00:00:00Z"},
    "tok-admin": {"id": "admin", "email": "admin@test", "email_confirmed_at": "2026-01-01T00:00:00Z"},
    "tok-unverified": {"id": "user-u", "email": "u@test", "email_confirmed_at": None},
}
JOB = {"id": "job-a", "user_id": "user-a", "status": "completed"}
JOB_TOKEN = "tok-job-a"


@pytest.fixture(scope="module")
def app():
    return route_access.app()


@pytest.fixture(scope="module")
def table(app):
    return route_access.routes(app)


@pytest.fixture(autouse=True)
def fakes(monkeypatch):
    import middleware.auth as auth
    import routers.jobs as jobs
    import services.feature_flags as feature_flags
    from config import settings
    from services.job_queue_service import JobQueueService

    async def verify(token):
        return USERS.get(token)

    async def profile(user_id):
        return {"id": user_id, "email_verified": True, "is_admin": user_id == "admin"}

    async def no_refresh(token):
        return None

    def stop_after(check):
        def spy(*args, **kwargs):
            check(*args, **kwargs)
            raise AccessGranted()
        return spy

    monkeypatch.setattr(jobs, "require_token", stop_after(jobs.require_token))
    monkeypatch.setattr(jobs, "require_job_access", stop_after(jobs.require_job_access))
    auth.clear_all_token_cache()
    monkeypatch.setattr(auth, "_verify_supabase_token_async", verify)
    monkeypatch.setattr(auth, "_get_user_profile_async", profile)
    monkeypatch.setattr(auth, "_refresh_supabase_session_async", no_refresh)
    monkeypatch.setattr(settings, "INTERNAL_API_KEY", INTERNAL_KEY)
    monkeypatch.setattr(feature_flags, "is_enabled", every_flag_on)
    monkeypatch.setattr(JobQueueService, "verify_access", staticmethod(lambda j, t: (j, t) == ("job-a", JOB_TOKEN)))
    monkeypatch.setattr(JobQueueService, "get_job", staticmethod(lambda j: dict(JOB) if j == "job-a" else None))
    yield
    auth.clear_all_token_cache()


def request(method="GET", path="/", cookie=None, headers=None):
    from starlette.requests import Request
    raw = [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
    if cookie:
        raw.append((b"cookie", f"auth_token={cookie}".encode()))
    return Request({"type": "http", "method": method, "path": path, "headers": raw, "query_string": b""})


def every_flag_on(name):
    return True


async def _handler_stub(*args, **kwargs):
    raise AccessGranted()


def call(route, cookie=None, headers=None, **values):
    from fastapi import HTTPException
    endpoint = route.endpoint
    code = endpoint.__code__
    cell = None
    if code in route_access.protection_codes():
        cell = endpoint.__closure__[code.co_freevars.index("func")]
        original = cell.cell_contents
        cell.cell_contents = _handler_stub
    inner = inspect.unwrap(endpoint)
    params = inspect.signature(inner).parameters
    kwargs = {n: values.get(n, DEFAULTS.get(n, "x")) for n, p in params.items()
              if n != "request" and (n in values or p.default is inspect.Parameter.empty)}
    req = request(cookie=cookie, headers=headers)
    try:
        asyncio.run(endpoint(req, **kwargs) if "request" in params else endpoint(**kwargs))
        return "handler returned without the stub"
    except AccessGranted:
        return GRANTED
    except HTTPException as e:
        return e.status_code
    except Exception as e:
        return f"{type(e).__name__}: {e}"
    finally:
        if cell is not None:
            cell.cell_contents = original


def protected_by(table, protection):
    return [(fp, r) for fp, p, r in table if p == protection]


def classified(table, entry_class):
    names = {fp for fp, why in ratchet.allowed(RULE).items() if route_access.entry_class(why) == entry_class}
    routes = [(fp, r) for fp, protection, r in table if protection is None and fp in names]
    assert len(routes) == len(names), f"baseline {entry_class} entries without a route: {names - {fp for fp, _ in routes}}"
    return routes


def http(app, *requests):
    import httpx

    async def run():
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return [(await client.request(m, p, **kw)).status_code for m, p, kw in requests]
    return asyncio.run(run())


def test_every_route_is_protected_or_classified(app):
    ratchet.assert_no_new(RULE, route_access.collect(application=app), FIX)


def test_every_exception_names_a_known_class_and_a_reason():
    assert {fp: p for fp, why in ratchet.allowed(RULE).items() if (p := route_access.reason_problem(why))} == {}


def test_a_new_unprotected_route_fails_and_a_protected_one_passes(tmp_path):
    from fastapi import FastAPI, Request
    from middleware.auth import require_auth
    probe = FastAPI()

    @probe.get("/api/probe/open")
    async def open_route(request: Request):
        return {}

    @probe.get("/api/probe/closed")
    @require_auth
    async def closed_route(request: Request):
        return {}

    current = route_access.collect(application=probe)
    assert "GET /api/probe/open" in current and "GET /api/probe/closed" not in current
    empty = tmp_path / "baseline.json"
    empty.write_text('{"version": 1, "rules": {}}')
    with pytest.raises(AssertionError, match="GET /api/probe/open"):
        ratchet.assert_no_new(RULE, current, FIX, empty)


def test_user_routes_need_a_valid_verified_session(table):
    routes = protected_by(table, "user")
    assert len(routes) >= 50
    for fp, r in routes:
        assert call(r) == 401, f"{fp}: no session"
        assert call(r, cookie="forged") == 401, f"{fp}: invalid token"
        assert call(r, cookie="tok-unverified") == 403, f"{fp}: unverified email"
        assert call(r, cookie="tok-user-a") == GRANTED, f"{fp}: valid session"


def test_admin_routes_refuse_users_and_wrong_internal_keys(table):
    routes = protected_by(table, "admin")
    assert len(routes) >= 10
    for fp, r in routes:
        assert call(r) == 401, f"{fp}: no session"
        assert call(r, cookie="tok-user-a") == 403, f"{fp}: a normal user"
        assert call(r, headers={"X-Internal-Key": "wrong"}) == 401, f"{fp}: wrong internal key"
        assert call(r, cookie="tok-admin") == GRANTED, f"{fp}: admin"
        assert call(r, headers={"X-Internal-Key": INTERNAL_KEY}) == GRANTED, f"{fp}: internal key"


def test_job_token_routes_need_this_jobs_token(table):
    for fp, r in classified(table, "job-token"):
        assert call(r, token=None) == 400, f"{fp}: no token"
        assert call(r, token="tok-other-job") == 403, f"{fp}: another job's token"
        assert call(r, cookie="tok-user-a", token=None) == 400, f"{fp}: a session is not a share token"
        assert call(r, token=JOB_TOKEN) == GRANTED, f"{fp}: this job's token"


def test_job_token_or_owner_routes(table):
    for fp, r in classified(table, "job-token-or-owner"):
        assert call(r, token=None) == 403, f"{fp}: anonymous, no token"
        assert call(r, cookie="tok-user-b", token=None) == 403, f"{fp}: another user, no token"
        assert call(r, cookie="tok-user-b", token="tok-other-job") == 403, f"{fp}: another job's token"
        assert call(r, cookie="tok-user-b", token=JOB_TOKEN) == GRANTED, f"{fp}: share token"
        assert call(r, cookie="tok-user-a", token=None) == GRANTED, f"{fp}: owner"


def test_webhook_rejects_an_invalid_signature(app, table, monkeypatch):
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_dummy")
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_test")
    ((fp, _),) = classified(table, "webhook")
    method, path = fp.split(" ", 1)
    forged = {"content": b'{"type": "checkout.session.completed"}',
              "headers": {"stripe-signature": "t=1,v1=forged", "content-type": "application/json"}}
    assert http(app, (method, path, forged)) == [400]


def test_get_routes_answer_401_over_http_without_a_session(app, table):
    picks = [r for fp, p, r in table if p in ("user", "admin") and fp.startswith("GET ")
             and not any(p.required for p in r.dependant.query_params)]
    assert len(picks) >= 15
    codes = http(app, *[("GET", r.path.replace("{", "").replace("}", ""), {}) for r in picks])
    assert [(r.path, c) for r, c in zip(picks, codes) if c != 401] == []
