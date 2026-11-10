import asyncio

import httpx
import pytest

from services import model_catalog


@pytest.fixture(autouse=True)
def _clear_cache():
    model_catalog._cache.clear()


def _mock_client(monkeypatch, handler):
    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        model_catalog.httpx,
        "AsyncClient",
        lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw),
    )


def test_openai_listing_keeps_only_chat_models(monkeypatch):
    ids = ["gpt-5.6-terra", "text-embedding-3-small", "whisper-1", "gpt-image-1", "dall-e-3", "omni-moderation-latest", "babbage-002"]
    _mock_client(monkeypatch, lambda r: httpx.Response(200, json={"data": [{"id": i} for i in ids]}))

    assert asyncio.run(model_catalog.list_models("openai", "sk-test")) == ["gpt-5.6-terra"]


def test_anthropic_uses_its_own_auth_headers(monkeypatch):
    seen = {}

    def handler(request):
        seen.update(request.headers)
        return httpx.Response(200, json={"data": [{"id": "claude-sonnet-5-5"}]})

    _mock_client(monkeypatch, handler)

    assert asyncio.run(model_catalog.list_models("anthropic", "sk-ant")) == ["claude-sonnet-5-5"]
    assert seen["x-api-key"] == "sk-ant"
    assert "authorization" not in seen


def test_results_are_cached_per_key(monkeypatch):
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(200, json={"data": [{"id": "gpt-5.6-terra"}]})

    _mock_client(monkeypatch, handler)
    asyncio.run(model_catalog.list_models("openai", "key-a"))
    asyncio.run(model_catalog.list_models("openai", "key-a"))
    asyncio.run(model_catalog.list_models("openai", "key-b"))

    assert len(calls) == 2
    assert all("key-a" not in repr(k) for k in model_catalog._cache)


def test_upstream_error_raises_so_route_can_fall_back(monkeypatch):
    _mock_client(monkeypatch, lambda r: httpx.Response(401, json={"error": "bad key"}))

    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(model_catalog.list_models("openai", "sk-bad"))


def test_chat_request_rejects_malformed_model_id():
    from models.chat import ChatRequest

    assert ChatRequest(question="hi", model="gpt-5.6-terra").model == "gpt-5.6-terra"
    with pytest.raises(ValueError):
        ChatRequest(question="hi", model="gpt 5; drop table")


def test_model_override_does_not_mutate_shared_provider(monkeypatch):
    from llm_providers import LLMManager

    llm_manager = LLMManager()
    shared = llm_manager.providers["openai"]
    monkeypatch.setattr(shared, "api_key", "sk-test")
    original = shared.model

    picked = llm_manager.get_provider("openai", model_override="gpt-5.6-sol")
    default = llm_manager.get_provider("openai")

    assert picked.model == "gpt-5.6-sol"
    assert shared.model == original
    assert default is shared
