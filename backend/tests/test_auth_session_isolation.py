import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException, Response
from starlette.requests import Request

from config import settings
from middleware import auth as auth_middleware
from routers import auth_new
from services.supabase_service import SupabaseService


class _Env:
    """Records every call made on the shared client and on each fresh client."""

    def __init__(self):
        self.calls = []
        self.invalid_tokens = set()
        self.fresh_clients = 0

    def calls_named(self, name):
        return [call for call in self.calls if call[1] == name]


class _Admin:
    def __init__(self, env, client_name):
        self.env, self.client_name = env, client_name

    def sign_out(self, jwt, scope="global"):
        self.env.calls.append((self.client_name, "admin.sign_out", jwt, scope))
        if jwt in self.env.invalid_tokens:
            raise RuntimeError("invalid or expired jwt")

    def update_user_by_id(self, user_id, attributes):
        self.env.calls.append((self.client_name, "admin.update_user_by_id", user_id, attributes))


class _Auth:
    def __init__(self, env, client_name):
        self.env, self.client_name = env, client_name
        self.admin = _Admin(env, client_name)

    # These act on whichever session the client holds. The code under test
    # swallows exceptions, so record the attempt as well as raising.
    def sign_out(self, *_args, **_kwargs):
        self.env.calls.append((self.client_name, "BARE sign_out"))
        raise AssertionError("sign_out() without a token")

    def update_user(self, *_args, **_kwargs):
        self.env.calls.append((self.client_name, "BARE update_user"))
        raise AssertionError("update_user() without a token")

    def verify_otp(self, params):
        self.env.calls.append((self.client_name, "verify_otp", params["type"]))
        if params["token"] != "123456":
            raise RuntimeError("bad otp")
        return SimpleNamespace(user=SimpleNamespace(id="user-1"),
                               session=SimpleNamespace(access_token="recovery-access"))

    def refresh_session(self, refresh_token):
        self.env.calls.append((self.client_name, "refresh_session", refresh_token))
        if refresh_token != "refresh-ok":
            raise RuntimeError("bad refresh token")
        return SimpleNamespace(
            session=SimpleNamespace(access_token="fresh-access", refresh_token="refresh-next"),
            user=SimpleNamespace(id="user-1", email="a@example.com", email_confirmed_at="t", created_at="t"),
        )

    def sign_in_with_password(self, _credentials):
        self.env.calls.append((self.client_name, "sign_in_with_password"))
        return SimpleNamespace()


class _Client:
    def __init__(self, env, name):
        self.auth = _Auth(env, name)


@pytest.fixture
def env(monkeypatch):
    environment = _Env()
    shared = _Client(environment, "shared")

    def fresh():
        environment.fresh_clients += 1
        return _Client(environment, f"fresh-{environment.fresh_clients}")

    monkeypatch.setattr(SupabaseService, "get_auth_client", staticmethod(lambda: shared))
    monkeypatch.setattr(SupabaseService, "new_auth_client", staticmethod(fresh))
    return environment


def _logout(**cookies):
    header = "; ".join(f"{name}={value}" for name, value in cookies.items()).encode()
    request = Request({"type": "http", "method": "POST", "path": "/api/auth/logout",
                       "headers": [(b"cookie", header)] if cookies else [], "query_string": b""})
    return asyncio.run(auth_new.logout(request, Response()))


def test_logout_revokes_only_the_callers_own_session(env):
    response = _logout(auth_token="token-1", auth_refresh_token="refresh-1")

    assert response.success
    assert env.calls == [("shared", "admin.sign_out", "token-1", "local")]


def test_logout_falls_back_to_the_refresh_token_when_the_access_token_expired(env):
    env.invalid_tokens.add("expired")

    _logout(auth_token="expired", auth_refresh_token="refresh-ok")

    assert env.calls == [
        ("shared", "admin.sign_out", "expired", "local"),
        ("fresh-1", "refresh_session", "refresh-ok"),
        ("shared", "admin.sign_out", "fresh-access", "local"),
    ]


def test_logout_with_only_a_refresh_cookie_still_revokes(env):
    _logout(auth_refresh_token="refresh-ok")

    assert env.calls[-1] == ("shared", "admin.sign_out", "fresh-access", "local")


def test_logout_without_cookies_touches_nothing(env):
    assert _logout().success
    assert env.calls == []


def test_logout_with_forged_tokens_cannot_affect_another_user(env):
    env.invalid_tokens.add("forged")

    response = _logout(auth_token="forged", auth_refresh_token="not-a-real-token")

    assert response.success
    assert not env.calls_named("BARE sign_out")
    assert [call[1] for call in env.calls] == ["admin.sign_out", "refresh_session"]


def _reset(code):
    return asyncio.run(auth_new.reset_password(auth_new.ResetPasswordRequest(
        email="user@example.com", code=code, new_password="long-enough-password")))


def test_reset_password_updates_by_user_id_and_ends_all_sessions(env):
    assert _reset("123456").success

    assert env.calls == [
        ("fresh-1", "verify_otp", "recovery"),
        ("fresh-1", "admin.update_user_by_id", "user-1", {"password": "long-enough-password"}),
        ("shared", "admin.sign_out", "recovery-access", "global"),
    ]


def test_reset_password_with_a_wrong_code_changes_nothing(env):
    with pytest.raises(HTTPException) as error:
        _reset("000000")

    assert error.value.status_code == 400
    assert not env.calls_named("admin.update_user_by_id")


def test_sign_in_uses_a_fresh_client_each_time(env):
    auth_new._sign_in_with_password("a@example.com", "pw")
    auth_new._sign_in_with_password("b@example.com", "pw")

    assert [call[0] for call in env.calls] == ["fresh-1", "fresh-2"]


def test_session_refresh_uses_a_fresh_client(env):
    result = auth_middleware._refresh_supabase_session("refresh-ok")

    assert result["access_token"] == "fresh-access"
    assert env.calls == [("fresh-1", "refresh_session", "refresh-ok")]


def test_new_auth_client_is_never_shared(monkeypatch):
    monkeypatch.setattr(settings, "SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setattr(settings, "SUPABASE_SERVICE_KEY", "eyJhbGciOiJIUzI1NiJ9.eyJyb2xlIjoic2VydmljZV9yb2xlIn0.c2lnbmF0dXJl")
    monkeypatch.setattr(SupabaseService, "_auth_client", None)

    assert SupabaseService.new_auth_client() is not SupabaseService.new_auth_client()
    assert SupabaseService.get_auth_client() is SupabaseService.get_auth_client()
    assert SupabaseService.new_auth_client() is not SupabaseService.get_auth_client()
