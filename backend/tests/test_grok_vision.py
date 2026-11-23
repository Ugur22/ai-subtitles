import asyncio
import os
import sys

import httpx
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import llm_providers  # noqa: E402
from llm_providers import GrokProvider  # noqa: E402
from services.provider_http import VisionTimeoutError  # noqa: E402
from services.chat.comparison import handler  # noqa: E402
from services.chat.providers import _classify_provider_error, _provider_error_message  # noqa: E402


def _grok(monkeypatch, handler_fn):
    monkeypatch.setenv("XAI_API_KEY", "xai-test")
    monkeypatch.setenv("XAI_VISION_TIMEOUT_SECONDS", "120")
    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        llm_providers.httpx,
        "AsyncClient",
        lambda **kw: real_client(transport=httpx.MockTransport(handler_fn), **kw),
    )
    monkeypatch.setattr(llm_providers, "_load_image_as_base64", lambda path: ("aW1n", "image/jpeg"))
    return GrokProvider(model_override="grok-4.6")


def test_vision_timeout_error_is_readable_and_classified(monkeypatch):
    def timeout_handler(request):
        raise httpx.ReadTimeout("", request=request)

    provider = _grok(monkeypatch, timeout_handler)
    with pytest.raises(Exception) as excinfo:
        asyncio.run(provider.generate_with_images(
            [{"role": "user", "content": "compare"}],
            image_paths=["a.jpg", "b.jpg", "c.jpg"],
        ))

    message = str(excinfo.value)
    assert message == "Grok vision request timed out after 120s (model grok-4.6, 3 images)"
    assert _classify_provider_error(excinfo.value) == "llm_unavailable"
    assert "took too long" in _provider_error_message(excinfo.value, "grok")


def test_http_error_is_not_double_wrapped(monkeypatch):
    provider = _grok(monkeypatch, lambda request: httpx.Response(400, text="bad image"))
    with pytest.raises(Exception) as excinfo:
        asyncio.run(provider.generate_with_images(
            [{"role": "user", "content": "compare"}], image_paths=["a.jpg"],
        ))

    message = str(excinfo.value)
    assert message.count("Grok vision generation failed") == 1
    assert "bad image" in message


class RecordingProvider:
    max_vision_images = 6

    def __init__(self):
        self.image_paths = None
        self.messages = None

    def supports_vision(self):
        return True

    async def generate_with_images(self, messages, image_paths, temperature, max_tokens):
        self.messages = messages
        self.image_paths = image_paths
        return "prose"


def _appearance(index):
    return {
        "screenshot_url": f"https://img/{index}.jpg",
        "start_time": float(index * 60),
        "similarity": 0.9,
        "face_id": f"f{index}",
    }


def test_comparison_prompt_matches_images_sent(monkeypatch):
    provider = RecordingProvider()

    async def fake_provider(*args, **kwargs):
        return provider

    monkeypatch.setattr(handler, "_get_chat_provider", fake_provider)
    monkeypatch.setattr(handler, "_transcript_window_context", lambda *a, **k: "none")

    frame_a, frame_b = _appearance(0), _appearance(9)
    intermediates = [_appearance(i) for i in range(1, 9)]
    asyncio.run(handler._run_person_comparison_llm(
        None,
        person_name="Alex",
        secondary_person_name=None,
        frame_a_appearance=frame_a,
        frame_b_appearance=frame_b,
        question="compare Alex before and after",
        custom_instructions=None,
        provider_name="grok",
        video_hash="v1",
        timeline_appearances=[frame_a, *intermediates, frame_b],
    ))

    assert len(provider.image_paths) == provider.max_vision_images
    sent_intermediates = provider.image_paths[2:]
    assert sent_intermediates[0] == "https://img/1.jpg"
    assert sent_intermediates[-1] == "https://img/8.jpg"

    user_prompt = provider.messages[1]["content"]
    assert "Image 6 →" in user_prompt
    assert "Image 7 →" not in user_prompt


def test_thin_evenly_keeps_ends():
    rows = [{"i": i} for i in range(8)]
    assert [r["i"] for r in handler._thin_evenly(rows, 4)] == [0, 2, 5, 7]
    assert handler._thin_evenly(rows[:3], 4) == rows[:3]
    assert handler._thin_evenly(rows, 0) == []


def test_cap_is_applied_before_images_are_loaded(monkeypatch):
    loaded = []
    provider = _grok(monkeypatch, lambda request: httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]}))
    monkeypatch.setattr(llm_providers, "_load_image_as_base64", lambda path: loaded.append(path) or ("aW1n", "image/jpeg"))

    out = asyncio.run(provider.generate_with_images(
        [{"role": "user", "content": "describe"}], image_paths=[f"{i}.jpg" for i in range(10)],
    ))

    assert out == "ok"
    assert sorted(loaded) == sorted(f"{i}.jpg" for i in range(provider.max_vision_images))


@pytest.mark.parametrize("provider_cls, env_key", [
    (llm_providers.OpenAIProvider, "OPENAI_API_KEY"),
    (llm_providers.AnthropicProvider, "ANTHROPIC_API_KEY"),
])
def test_other_vision_providers_raise_readable_timeouts(monkeypatch, provider_cls, env_key):
    monkeypatch.setenv(env_key, "test-key")
    real_client = httpx.AsyncClient

    def timeout_handler(request):
        raise httpx.ReadTimeout("", request=request)

    monkeypatch.setattr(
        llm_providers.httpx,
        "AsyncClient",
        lambda **kw: real_client(transport=httpx.MockTransport(timeout_handler), **kw),
    )
    monkeypatch.setattr(llm_providers, "_load_image_as_base64", lambda path: ("aW1n", "image/jpeg"))

    with pytest.raises(VisionTimeoutError, match=r"vision request timed out after \d+s \(model .+, 1 images\)"):
        asyncio.run(provider_cls().generate_with_images(
            [{"role": "user", "content": "describe"}], image_paths=["a.jpg"],
        ))
