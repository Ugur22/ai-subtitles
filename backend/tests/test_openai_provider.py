import asyncio

import httpx
import pytest

import llm_providers
from llm_providers import OpenAIProvider


def _provider(monkeypatch, handler):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        llm_providers.httpx,
        "AsyncClient",
        lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw),
    )
    return OpenAIProvider()


def test_payload_uses_gpt5_compatible_params(monkeypatch):
    seen = {}

    def handler(request):
        seen.update(__import__("json").loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    provider = _provider(monkeypatch, handler)
    out = asyncio.run(provider.generate([{"role": "user", "content": "hi"}], temperature=0.7, max_tokens=123))

    assert out == "ok"
    assert seen["model"] == "gpt-5.6-terra"
    assert seen["max_completion_tokens"] == 123
    assert "max_tokens" not in seen
    assert "temperature" not in seen


def test_error_includes_openai_body(monkeypatch):
    def handler(request):
        return httpx.Response(404, json={"error": {"code": "model_not_found", "message": "gone"}})

    provider = _provider(monkeypatch, handler)
    with pytest.raises(Exception, match="model_not_found"):
        asyncio.run(provider.generate([{"role": "user", "content": "hi"}]))
