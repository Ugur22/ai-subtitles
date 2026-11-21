"""Both chat endpoints run the shared pipeline in services/chat/pipeline.py.

Retrieval and the provider are faked; the tests pin that /api/chat/ and
/api/chat/stream agree, and that the stream only ever indexes the
owner-checked transcription.
"""
import asyncio
import json
import os
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import HTTPException  # noqa: E402

from models import ChatRequest  # noqa: E402
from routers import chat  # noqa: E402
from services.chat import pipeline  # noqa: E402

ANSWER = "The speaker explains the plan in detail."
OWNED = {"transcription": {"segments": [{"start": 0.0, "end": 1.0, "text": "owned segment"}]}}
TEXT_SOURCES = [{"type": "text", "text": "hit", "start": 0.0, "end": 1.0}]


class FakeProvider:
    def supports_vision(self):
        return False

    async def generate(self, messages, **_kwargs):
        return ANSWER

    async def generate_stream(self, messages, **_kwargs):
        for word in ANSWER.split(" "):
            yield word + " "


@pytest.fixture
def chat_env(monkeypatch):
    state = SimpleNamespace(indexed=[], metered=[], chunks_exist=True, search_hits=["hit"], comparison=None)

    async def run_inline(func, *args, **kwargs):
        return func(*args, **kwargs)

    async def text_context(_video, _question, _n):
        return state.search_hits, "context", list(TEXT_SOURCES) if state.search_hits else []

    async def no_audio(*_args):
        return "", [], None

    async def provider(*_args):
        return FakeProvider()

    async def comparison(_request, _req, _intent):
        return {"answer": "Comparison answer", "sources": [{"type": "comparison"}], "video_hash": "vh", "provider_used": "grok"}

    embedding_service = SimpleNamespace(
        transcript_chunks_exist=lambda _video, _user: state.chunks_exist,
        audio_events_exist=lambda _video, _user: False,
        index_transcript_chunks=lambda video, segments, user: state.indexed.append((video, segments, user)),
    )

    import middleware.quota
    import model_preloader
    import services.usage_meter

    monkeypatch.setattr(chat, "LLM_AVAILABLE", True)
    monkeypatch.setattr(chat, "_authorize_video", lambda _request, _video: ("owner-1", state.owned))
    monkeypatch.setattr(middleware.quota, "check_can_chat", lambda _profile: None)
    monkeypatch.setattr(model_preloader, "models_ready", lambda: True)
    monkeypatch.setattr(services.usage_meter, "record_chat_message", lambda user, llm_tokens: state.metered.append(user))
    monkeypatch.setattr(pipeline, "transcript_embedding_service", embedding_service)
    monkeypatch.setattr(pipeline, "_run_in_executor", run_inline)
    monkeypatch.setattr(pipeline, "_resolve_contextual_visual_question", lambda question, *_args: question)
    monkeypatch.setattr(pipeline, "_detect_comparison_intent", lambda _q, _v: state.comparison)
    monkeypatch.setattr(pipeline, "_handle_person_comparison", comparison)
    monkeypatch.setattr(pipeline, "_retrieve_text_context", text_context)
    monkeypatch.setattr(pipeline, "_retrieve_audio_context", no_audio)
    monkeypatch.setattr(pipeline, "_get_chat_provider", provider)
    state.owned = OWNED
    return state


def _request():
    return SimpleNamespace(state=SimpleNamespace(profile={"id": "owner-1"}, user={"id": "owner-1"}))


def _chat_request(question="What is the plan?"):
    return ChatRequest(question=question, video_hash="vh", include_visuals=False, provider="grok")


def _run_json(question="What is the plan?"):
    return asyncio.run(chat.chat_with_video.__wrapped__(_request(), _chat_request(question)))


def _run_stream(question="What is the plan?"):
    async def collect():
        response = await chat.chat_with_video_stream.__wrapped__(_request(), _chat_request(question))
        return [json.loads(chunk[len("data: "):]) async for chunk in response.body_iterator]

    return asyncio.run(collect())


def _of_type(events, kind):
    return [event for event in events if event["type"] == kind]


def test_both_endpoints_return_the_same_answer_and_sources(chat_env):
    body = _run_json()
    events = _run_stream()

    streamed = "".join(event["content"] for event in _of_type(events, "token")).strip()
    assert body["answer"] == ANSWER == streamed
    assert body["sources"] == _of_type(events, "sources")[0]["sources"] == TEXT_SOURCES
    assert body["provider_used"] == _of_type(events, "done")[0]["provider_used"] == "grok"
    assert [event["phase"] for event in _of_type(events, "phase")] == ["searching", "generating"]
    assert chat_env.metered == ["owner-1", "owner-1"]


def test_stream_auto_indexes_the_owner_checked_transcription(chat_env):
    chat_env.chunks_exist = False

    events = _run_stream()

    assert not _of_type(events, "error")
    assert chat_env.indexed == [("vh", OWNED["transcription"]["segments"], "owner-1")]


@pytest.mark.parametrize(
    "question, owned, status, message",
    [
        ("", OWNED, 400, "Question is required"),
        ("What is the plan?", {}, 404, pipeline.NOT_INDEXED_MESSAGE),
    ],
)
def test_pipeline_errors_map_to_http_status_and_stream_error_event(chat_env, question, owned, status, message):
    chat_env.chunks_exist = False
    chat_env.owned = owned

    with pytest.raises(HTTPException) as error:
        _run_json(question)
    assert (error.value.status_code, error.value.detail) == (status, message)

    assert _run_stream(question) == [{"type": "error", "message": message}]


def test_comparison_answers_are_metered_on_both_endpoints(chat_env):
    chat_env.comparison = object()

    body = _run_json()
    events = _run_stream()

    assert body["answer"] == "Comparison answer"
    assert _of_type(events, "token") == [{"type": "token", "content": "Comparison answer"}]
    assert _of_type(events, "sources")[0]["sources"] == [{"type": "comparison"}]
    assert _of_type(events, "phase") == [pipeline.phase("comparing", "Comparing person states")]
    assert chat_env.metered == ["owner-1", "owner-1"]


def test_no_results_answer_is_not_metered(chat_env):
    chat_env.search_hits = []

    body = _run_json()
    events = _run_stream()

    assert body == {"answer": pipeline.NO_RESULTS_ANSWER, "sources": [], "provider_used": "grok", "video_hash": "vh"}
    assert _of_type(events, "done") == [{"type": "done", "provider_used": "grok", "video_hash": "vh"}]
    assert chat_env.metered == []
