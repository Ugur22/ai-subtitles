import asyncio

import httpx
import pytest

from services import model_catalog


@pytest.fixture(autouse=True)
def _clear_cache():
    model_catalog._cache.clear()
    model_catalog._failures.clear()


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

    with pytest.raises(model_catalog.ModelListError, match="HTTP 401"):
        asyncio.run(model_catalog.list_models("openai", "sk-bad"))


def test_listing_error_carries_provider_message(monkeypatch):
    body = {"code": "permission-denied", "error": "Your team has used all available credits"}
    _mock_client(monkeypatch, lambda r: httpx.Response(403, json=body))

    with pytest.raises(model_catalog.ModelListError, match="used all available credits"):
        asyncio.run(model_catalog.list_models("xai", "xai-key"))


def test_key_errors_skip_second_endpoint_and_are_cached_briefly(monkeypatch):
    calls = []

    def handler(request):
        calls.append(request.url.path)
        return httpx.Response(403, json={"error": "out of credits"})

    _mock_client(monkeypatch, handler)
    for _ in range(2):
        with pytest.raises(model_catalog.ModelListError, match="out of credits"):
            asyncio.run(model_catalog.list_models("xai", "xai-key"))

    assert calls == ["/v1/language-models"]


def test_xai_prefers_language_models_then_falls_back(monkeypatch):
    seen = []

    def handler(request):
        seen.append(request.url.path)
        if request.url.path.endswith("language-models"):
            return httpx.Response(404, json={"error": "nope"})
        return httpx.Response(200, json={"data": [{"id": "grok-4.3"}, {"id": "grok-2-image"}]})

    _mock_client(monkeypatch, handler)

    assert asyncio.run(model_catalog.list_models("xai", "xai-key")) == ["grok-4.3"]
    assert seen == ["/v1/language-models", "/v1/models"]


def test_xai_accepts_models_key_in_language_models_payload(monkeypatch):
    _mock_client(monkeypatch, lambda r: httpx.Response(200, json={"models": [{"id": "grok-4.3"}, {"id": "grok-4-fast"}]}))

    assert asyncio.run(model_catalog.list_models("xai", "xai-key")) == ["grok-4-fast", "grok-4.3"]


def test_xai_validator_reports_exhausted_credits_not_permissions(monkeypatch):
    from services import key_validator

    body = {"code": "permission-denied", "error": "Your team has either used all available credits or reached its monthly spending limit."}
    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        key_validator.httpx,
        "AsyncClient",
        lambda **kw: real_client(transport=httpx.MockTransport(lambda r: httpx.Response(403, json=body)), **kw),
    )

    ok, message = asyncio.run(key_validator._test_xai("xai-key", httpx.Timeout(5.0)))

    assert ok is False
    assert "out of credits" in message and "permissions" not in message


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


@pytest.mark.parametrize("model,expected", [
    ("grok-4.5", ["low", "medium", "high"]),
    ("grok-4.6", ["low", "medium", "high", "xhigh"]),
    ("grok-4.7", ["low", "medium", "high", "xhigh"]),
    ("grok-4.20-0309-reasoning", []),
    ("grok-4.20-0309-non-reasoning", []),
    ("grok-unknown", []),
])
def test_reasoning_capabilities_are_model_specific(model, expected):
    assert model_catalog.reasoning_effort_options("xai", model) == expected
    assert model_catalog.reasoning_effort_options("grok", model) == expected
    assert model_catalog.reasoning_effort_options("openai", model) == []


def test_reasoning_override_is_request_scoped_and_validated(monkeypatch):
    from llm_providers import LLMManager

    manager = LLMManager()
    shared = manager.providers["grok"]
    monkeypatch.setattr(shared, "api_key", "xai-test")
    monkeypatch.setattr(shared, "model", "grok-4.7")
    picked = manager.get_provider("xai", reasoning_effort="low")

    assert picked.reasoning_effort == "low"
    assert manager.get_provider("grok").reasoning_effort is None
    assert shared.model == "grok-4.7"
    with pytest.raises(ValueError, match="not supported"):
        manager.get_provider("grok", model_override="grok-4.5", reasoning_effort="xhigh")
    with pytest.raises(ValueError, match="not supported"):
        manager.get_provider("openai", reasoning_effort="low")


@pytest.mark.parametrize("model,effort", [
    ("grok-4.7", "low"),
    ("grok-4.6", "xhigh"),
    ("grok-4.5", None),
    ("grok-4.20-0309-reasoning", None),
    ("grok-4.20-0309-non-reasoning", None),
])
def test_grok_sends_selected_model_and_effort_in_text_vision_and_stream(monkeypatch, tmp_path, model, effort):
    import json
    from PIL import Image
    from llm_providers import LLMManager

    payloads = []

    def handler(request):
        payload = json.loads(request.content)
        payloads.append(payload)
        if payload.get("stream"):
            return httpx.Response(200, text='data: {"choices":[{"delta":{"content":"answer"}}]}\n\ndata: [DONE]\n\n')
        return httpx.Response(200, json={"choices": [{"message": {"content": "answer"}}]})

    _mock_client(monkeypatch, handler)
    manager = LLMManager()
    provider = manager.get_provider("grok", api_key_override="test-key", model_override=model, reasoning_effort=effort)
    image = tmp_path / "frame.jpg"
    Image.new("RGB", (16, 16)).save(image)
    messages = [{"role": "user", "content": "Describe the frame"}]

    async def run():
        assert await provider.generate(messages) == "answer"
        assert await provider.generate_with_images(messages, [str(image)]) == "answer"
        assert "".join([chunk async for chunk in provider.generate_stream(messages)]) == "answer"

    asyncio.run(run())

    assert len(payloads) == 3
    for payload in payloads:
        assert payload["model"] == model
        if effort:
            assert payload["reasoning_effort"] == effort
        else:
            assert "reasoning_effort" not in payload


def test_models_endpoint_advertises_only_supported_efforts(monkeypatch):
    from types import SimpleNamespace
    from llm_providers import LLMManager
    from routers import chat

    async def saved_key(*_args):
        return "test-key"

    async def listed_models(*_args):
        return ["grok-4.5", "grok-4.7", "grok-4.20-0309-non-reasoning"]

    monkeypatch.setattr(chat, "_get_saved_provider_key", saved_key)
    monkeypatch.setattr(chat, "list_models", listed_models)
    monkeypatch.setattr(chat, "llm_manager", LLMManager())
    monkeypatch.setattr(chat, "LLM_AVAILABLE", True)
    request = SimpleNamespace(state=SimpleNamespace(user={"id": "test-user"}))
    result = asyncio.run(chat.list_provider_models.__wrapped__(request, "grok"))

    assert result.reasoning_efforts == {
        "grok-4.5": ["low", "medium", "high"],
        "grok-4.7": ["low", "medium", "high", "xhigh"],
    }
    picked = asyncio.run(chat._get_chat_provider(request, "grok", "grok-4.7", "low"))
    assert picked.model == "grok-4.7"
    assert picked.reasoning_effort == "low"

    from fastapi import HTTPException
    with pytest.raises(HTTPException) as error:
        asyncio.run(chat._get_chat_provider(request, "grok", "grok-4.5", "xhigh"))
    assert error.value.status_code == 400


def test_chat_rejects_missing_personal_key_even_with_server_key(monkeypatch):
    from types import SimpleNamespace
    from fastapi import HTTPException
    from llm_providers import LLMManager
    from routers import chat

    async def no_saved_key(*_args):
        return None

    monkeypatch.setenv("XAI_API_KEY", "server-key")
    monkeypatch.setattr(chat, "llm_manager", LLMManager())
    monkeypatch.setattr(chat, "_get_saved_provider_key", no_saved_key)
    request = SimpleNamespace(state=SimpleNamespace(user={"id": "test-user"}))

    with pytest.raises(HTTPException) as error:
        asyncio.run(chat._get_chat_provider(request, "grok"))
    assert error.value.status_code == 400
    assert "No valid API key saved" in error.value.detail


def test_chat_request_rejects_invalid_effort():
    from models.chat import ChatRequest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        ChatRequest(question="Describe the frame", reasoning_effort="turbo")
