import ast
import asyncio
from pathlib import Path

import httpx
import pytest
from fastapi import Depends, FastAPI

from config import settings
from services import feature_flags
from services.feature_flags import KNOWN_FLAGS, all_flags, is_enabled, require_feature

BACKEND = Path(__file__).parents[1]


class _Flags:
    def __init__(self, enabled):
        self.enabled = enabled

    def is_feature_enabled(self, name):
        return name in self.enabled


class _FakeClient:
    def __init__(self, enabled=(), error=None):
        self.enabled = set(enabled)
        self.error = error

    def get_environment_flags(self):
        if self.error:
            raise self.error
        return _Flags(self.enabled)


@pytest.fixture(autouse=True)
def reset_client(monkeypatch):
    monkeypatch.setattr(settings, "FLAGSMITH_SERVER_KEY", "ser.test")
    feature_flags._reset_for_tests()
    yield
    feature_flags._reset_for_tests()


def _get(app, url):
    async def send():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            return await client.get(url)
    return asyncio.run(send())


def _guarded_app():
    app = FastAPI()

    @app.get("/guarded", dependencies=[Depends(require_feature("summary"))])
    def guarded():
        return {"ok": True}

    return app


def test_disabled_flag_returns_404_and_never_runs_handler():
    feature_flags._reset_for_tests(_FakeClient(enabled=()))
    assert _get(_guarded_app(), "/guarded").status_code == 404


def test_enabled_flag_passes_through():
    feature_flags._reset_for_tests(_FakeClient(enabled={"summary"}))
    response = _get(_guarded_app(), "/guarded")
    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_missing_key_disables_everything(monkeypatch):
    monkeypatch.setattr(settings, "FLAGSMITH_SERVER_KEY", None)
    assert all_flags() == {name: False for name in KNOWN_FLAGS}


def test_sdk_error_fails_closed():
    feature_flags._reset_for_tests(_FakeClient(enabled={"summary"}, error=RuntimeError("down")))
    assert is_enabled("summary") is False


def test_sdk_init_failure_fails_closed(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def broken_import(name, *args, **kwargs):
        if name == "flagsmith":
            raise ImportError("not installed")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", broken_import)
    assert is_enabled("chapters") is False


def test_unknown_flag_is_disabled_even_if_flagsmith_enables_it():
    feature_flags._reset_for_tests(_FakeClient(enabled={"secret_admin_thing"}))
    assert is_enabled("secret_admin_thing") is False
    assert set(all_flags()) == set(KNOWN_FLAGS)


def test_require_feature_rejects_unknown_names_at_import_time():
    with pytest.raises(ValueError):
        require_feature("typo")


def _calls_require_feature(node, flag):
    return any(
        isinstance(call, ast.Call)
        and isinstance(call.func, ast.Name)
        and call.func.id == "require_feature"
        and call.args
        and ast.literal_eval(call.args[0]) == flag
        for call in ast.walk(node)
    )


def test_chapters_router_is_guarded():
    tree = ast.parse((BACKEND / "routers" / "chapters.py").read_text())
    router_assign = next(
        node for node in tree.body
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == "router" for t in node.targets)
    )
    assert _calls_require_feature(router_assign.value, "chapters")


def test_generate_summary_route_is_guarded():
    tree = ast.parse((BACKEND / "routers" / "transcription.py").read_text())
    func = next(
        node for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "generate_summary"
    )
    assert any(_calls_require_feature(decorator, "summary") for decorator in func.decorator_list)


def test_failed_init_is_retried_after_the_cooldown(monkeypatch):
    import sys
    import types

    now = [1000.0]
    monkeypatch.setattr(feature_flags.time, "monotonic", lambda: now[0])
    attempts = []

    def flagsmith(**_kwargs):
        attempts.append(now[0])
        if len(attempts) == 1:
            raise RuntimeError("Flagsmith unreachable")
        return _FakeClient(enabled={"summary"})

    monkeypatch.setitem(sys.modules, "flagsmith", types.SimpleNamespace(Flagsmith=flagsmith))

    assert is_enabled("summary") is False
    now[0] += feature_flags.INIT_RETRY_COOLDOWN_SECONDS - 1
    assert is_enabled("summary") is False
    assert len(attempts) == 1

    now[0] += 1
    assert is_enabled("summary") is True
    assert len(attempts) == 2
    assert is_enabled("summary") is True
    assert len(attempts) == 2
