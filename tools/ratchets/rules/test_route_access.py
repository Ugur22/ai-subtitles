"""Ratchet route-access (see route_access.py): every route is protected or classified, and each class behaves.

Authentication only: who may call a route at all. Whether user B can reach user A's data is the ownership
invariant (backend/tests/invariants/). Runs against the real app with Supabase verification and the job lookup
replaced by fakes: no network, no database. Endpoints are called through their registered wrapper so FastAPI's
body validation (which runs before the wrapper and would answer 422) doesn't hide the auth decision.
"""

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
REACHED = "reached"


class Reached(Exception):
    """Raised in place of the handler (or right after a successful token or ownership check)."""
INTERNAL_KEY = "internal-test-key"
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
    from config import settings
    from services.job_queue_service import JobQueueService

    async def verify(token):
        return USERS.get(token)

    async def profile(user_id):
        return {"id": user_id, "email_verified": True, "is_admin": user_id == "admin"}

    async def no_refresh(token):
        return None

    import routers.jobs as jobs

    def stop_after(check):
        def spy(*args, **kwargs):
            check(*args, **kwargs)
            raise Reached()  # the real check passed; the rest of the handler is not this test's business
        return spy

    monkeypatch.setattr(jobs, "require_token", stop_after(jobs.require_token))
    monkeypatch.setattr(jobs, "require_job_access", stop_after(jobs.require_job_access))
    auth.clear_all_token_cache()
    monkeypatch.setattr(auth, "_verify_supabase_token_async", verify)
    monkeypatch.setattr(auth, "_get_user_profile_async", profile)
    monkeypatch.setattr(auth, "_refresh_supabase_session_async", no_refresh)
    monkeypatch.setattr(settings, "INTERNAL_API_KEY", INTERNAL_KEY)
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


async def _handler_stub(*args, **kwargs):
    raise Reached()


def call(route, cookie=None, headers=None, **values):
    """The status the route answers with, or REACHED once access was granted. For decorator-protected routes the
    handler behind the wrapper is swapped for a stub (the wrapper's `func` closure cell, shared by require_admin's
    session and internal-key paths), so only the decorator decides. Anything else unexpected is returned as text."""
    from fastapi import HTTPException
    endpoint = route.endpoint
    code = endpoint.__code__
    cell = None
    if "func" in code.co_freevars and code in route_access.protection_codes():
        cell = endpoint.__closure__[code.co_freevars.index("func")]
        original = cell.cell_contents
        cell.cell_contents = _handler_stub
    inner = inspect.unwrap(endpoint)
    params = inspect.signature(inner).parameters
    defaults = {"job_id": "job-a", "format": "srt"}
    kwargs = {n: values.get(n, defaults.get(n, "x")) for n, p in params.items()
              if n != "request" and (n in values or p.default is inspect.Parameter.empty)}
    req = request(cookie=cookie, headers=headers)
    try:
        asyncio.run(endpoint(req, **kwargs) if "request" in params else endpoint(**kwargs))
        return "handler returned without the stub"
    except Reached:
        return REACHED
    except HTTPException as e:
        return e.status_code
    except Exception as e:  # noqa: BLE001 - reported, not swallowed
        return f"{type(e).__name__}: {e}"
    finally:
        if cell is not None:
            cell.cell_contents = original


def of_class(table, kind):
    return [(fp, r) for fp, k, r in table if k == kind]


def classified(kind):
    return {fp for fp, why in ratchet.allowed(RULE).items() if why.split(":", 1)[0] == kind}


# --- the ratchet --------------------------------------------------------------------------------------------

def test_every_route_is_protected_or_classified(app):
    ratchet.assert_no_new(RULE, route_access.collect(application=app), FIX)


def test_every_exception_names_a_known_class_and_a_reason():
    for fp, why in ratchet.allowed(RULE).items():
        kind, _, reason = why.partition(":")
        assert kind in route_access.CLASSES and len(reason.strip()) > 10, fp


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


# --- behaviour per class ------------------------------------------------------------------------------------

def test_user_routes_need_a_valid_verified_session(table):
    routes = of_class(table, "user")
    assert len(routes) >= 50
    for fp, r in routes:
        assert call(r) == 401, f"{fp}: no session"
        assert call(r, cookie="forged") == 401, f"{fp}: invalid token"
        assert call(r, cookie="tok-unverified") == 403, f"{fp}: unverified email"
        assert call(r, cookie="tok-user-a") == REACHED, f"{fp}: valid session"


def test_admin_routes_refuse_users_and_wrong_internal_keys(table):
    routes = of_class(table, "admin")
    assert len(routes) >= 10
    for fp, r in routes:
        assert call(r) == 401, f"{fp}: no session"
        assert call(r, cookie="tok-user-a") == 403, f"{fp}: a normal user"
        assert call(r, headers={"X-Internal-Key": "wrong"}) == 401, f"{fp}: wrong internal key"
        assert call(r, cookie="tok-admin") == REACHED, f"{fp}: admin"
        assert call(r, headers={"X-Internal-Key": INTERNAL_KEY}) == REACHED, f"{fp}: internal key"


def test_job_token_routes_need_this_jobs_token(table):
    routes = [(fp, r) for fp, r in of_class(table, None) if fp in classified("job-token")]
    assert len(routes) == len(classified("job-token"))
    for fp, r in routes:
        assert call(r, token=None) == 400, f"{fp}: no token"
        assert call(r, token="tok-other-job") == 403, f"{fp}: another job's token"
        assert call(r, cookie="tok-user-a", token=None) == 400, f"{fp}: a session is not a share token"
        assert call(r, token=JOB_TOKEN) == REACHED, f"{fp}: this job's token"


def test_job_token_or_owner_routes(table):
    routes = [(fp, r) for fp, r in of_class(table, None) if fp in classified("job-token-or-owner")]
    assert len(routes) == len(classified("job-token-or-owner"))
    for fp, r in routes:
        assert call(r, token=None) == 403, f"{fp}: anonymous, no token"
        assert call(r, cookie="tok-user-b", token=None) == 403, f"{fp}: another user, no token"
        assert call(r, cookie="tok-user-b", token="tok-other-job") == 403, f"{fp}: another job's token"
        assert call(r, cookie="tok-user-b", token=JOB_TOKEN) == REACHED, f"{fp}: share token"
        assert call(r, cookie="tok-user-a", token=None) == REACHED, f"{fp}: owner"


def test_webhook_rejects_an_invalid_signature(app, monkeypatch):
    import httpx
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_dummy")
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_test")
    (fp,) = classified("webhook")
    method, path = fp.split(" ", 1)

    async def post():
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
            return await http.request(method, path, content=b'{"type": "checkout.session.completed"}',
                                      headers={"stripe-signature": "t=1,v1=forged", "content-type": "application/json"})
    assert asyncio.run(post()).status_code == 400


def test_get_routes_answer_401_over_http_without_a_session(app, table):
    """Through the middleware stack, for every protected GET route without required query parameters."""
    import httpx
    picks = [r for fp, k, r in table if k in ("user", "admin") and fp.startswith("GET ")
             and not any(p.required for p in r.dependant.query_params)]
    assert len(picks) >= 15

    # Feature-flag gates answer 404 before auth when a flag is off (by design); switch them on so auth decides.
    gates = {d.call for r in picks for d in r.dependant.dependencies
             if getattr(d.call, "__qualname__", "").startswith("require_feature")}
    for gate in gates:
        app.dependency_overrides[gate] = lambda: None

    async def run():
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
            return [(r.path, (await http.get(r.path.replace("{", "").replace("}", ""))).status_code) for r in picks]
    try:
        bad = [(p, s) for p, s in asyncio.run(run()) if s != 401]
    finally:
        for gate in gates:
            app.dependency_overrides.pop(gate, None)
    assert bad == []
