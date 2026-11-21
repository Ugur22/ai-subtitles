"""Shared chat pipeline behind /api/chat/ and /api/chat/stream.

Stages are async generators: they yield progress events (plain dicts shaped like
the SSE events) and end with exactly one result object. The stream endpoint
forwards the events; the JSON endpoint drains them via `final_result`.
"""
import asyncio
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Dict, List, Optional, Union

from fastapi import Request

from models import ChatRequest
from services.transcript_embedding_service import transcript_embedding_service
from services.chat.audio_retrieval import _retrieve_audio_context
from services.chat.comparison.handler import _handle_person_comparison
from services.chat.comparison.intent import _detect_comparison_intent
from services.chat.context import _run_in_executor
from services.chat.prompt import _build_chat_messages
from services.chat.providers import (
    _classify_provider_error,
    _generate_visual_observations_with_fallback,
    _get_chat_provider,
    _provider_error_message,
    llm_manager,
)
from services.chat.query import _resolve_contextual_visual_question, _user_visual_search_config
from services.chat.text_retrieval import _retrieve_text_context
from services.chat.visual_retrieval import _retrieve_visual_context

NO_RESULTS_ANSWER = "I couldn't find relevant information in the video to answer your question."
NOT_INDEXED_MESSAGE = "Video not indexed. Please index it first using /api/index_video/"
# Proxies drop idle SSE sockets, so long provider calls emit a phase event this often.
HEARTBEAT_SECONDS = 5.0


class ChatPipelineError(Exception):
    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.message = message


@dataclass
class ChatContext:
    request: Request
    chat_request: ChatRequest
    # Both endpoints must pass the owner-checked values from _authorize_video.
    user_id: str
    owned_transcription: Optional[Dict]
    # Only the stream shows progress; the JSON endpoint skips the extra lookups.
    report_progress: bool = False

    @property
    def provider_name(self) -> Optional[str]:
        return self.chat_request.provider

    @property
    def include_visuals(self) -> bool:
        return self.chat_request.include_visuals or False


@dataclass
class EarlyAnswer:
    """An answer produced without calling the chat LLM (comparison or no results)."""
    response: Dict[str, Any]
    metered: bool
    visual_query_used: Optional[str] = None
    visual_query_variants: List[str] = field(default_factory=list)


@dataclass
class Retrieved:
    question: str
    context: str
    sources: list
    image_paths: list
    visual_context: str
    visual_sources: list
    visual_query_used: Optional[str]
    visual_query_variants: list
    audio_context: str
    audio_sources: list

    @property
    def all_sources(self) -> list:
        return self.sources + self.visual_sources + self.audio_sources


@dataclass
class Prepared:
    provider: Any
    messages: list
    image_paths: list
    use_images: bool
    text_only_with_images: bool


def phase(name: str, label: str) -> Dict[str, str]:
    return {"type": "phase", "phase": name, "label": label}


def provider_error_event(err: BaseException, provider_name: Optional[str], detail: Optional[str] = None) -> Dict[str, str]:
    return {
        "type": "error",
        "message": _provider_error_message(err, provider_name),
        "detail": detail if detail is not None else str(err),
        "code": _classify_provider_error(err),
    }


async def final_result(stage: AsyncIterator[Union[dict, Any]]) -> Any:
    result = None
    async for item in stage:
        if not isinstance(item, dict):
            result = item
    return result


def _no_results(ctx: ChatContext) -> Dict[str, Any]:
    return {
        "answer": NO_RESULTS_ANSWER,
        "sources": [],
        "provider_used": ctx.provider_name or "none",
        "video_hash": ctx.chat_request.video_hash,
    }


def early_answer_events(early: EarlyAnswer, provider_name: Optional[str], video_hash: Optional[str]) -> List[Dict[str, Any]]:
    response = early.response
    return [
        {
            "type": "sources",
            "sources": response.get("sources") or [],
            "visual_query_used": early.visual_query_used,
            "visual_query_variants": early.visual_query_variants,
        },
        {"type": "token", "content": response.get("answer", "")},
        {
            "type": "done",
            "provider_used": response.get("provider_used") or provider_name or llm_manager.default_provider,
            "video_hash": video_hash,
        },
    ]


async def _await_with_heartbeat(task: asyncio.Task, event: dict) -> AsyncIterator[dict]:
    while not task.done():
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=HEARTBEAT_SECONDS)
        except asyncio.TimeoutError:
            yield event


async def retrieve(ctx: ChatContext) -> AsyncIterator[Union[dict, EarlyAnswer, Retrieved]]:
    req = ctx.chat_request
    question = req.question
    video_hash = req.video_hash
    if not question:
        raise ChatPipelineError(400, "Question is required")

    user_visual_terms, user_visual_phrases = _user_visual_search_config(
        getattr(ctx.request.state, "profile", None)
    )
    retrieval_question = _resolve_contextual_visual_question(
        question,
        req.conversation_history,
        user_visual_terms,
        user_visual_phrases,
        video_hash,
    )

    if not transcript_embedding_service.transcript_chunks_exist(video_hash, ctx.user_id):
        if not ctx.owned_transcription:
            raise ChatPipelineError(404, NOT_INDEXED_MESSAGE)
        segments = ctx.owned_transcription.get('transcription', {}).get('segments', [])
        print(f"Auto-indexing video {video_hash}...")
        await _run_in_executor(
            transcript_embedding_service.index_transcript_chunks, video_hash, segments, ctx.user_id
        )

    comparison_intent = _detect_comparison_intent(question, video_hash)
    if comparison_intent:
        if ctx.report_progress:
            yield phase("comparing", "Comparing person states")
        comparison_request = req.copy(update={"video_hash": video_hash})
        response = await _handle_person_comparison(ctx.request, comparison_request, comparison_intent)
        yield EarlyAnswer(response=response, metered=True)
        return

    if ctx.report_progress:
        yield phase("searching", "Searching transcript")
    search_results, context, sources = await _retrieve_text_context(
        video_hash, retrieval_question, req.n_results or 8
    )
    if not search_results and not ctx.include_visuals:
        yield EarlyAnswer(response=_no_results(ctx), metered=False)
        return

    image_paths: list = []
    visual_context = ""
    visual_sources: list = []
    visual_query_used = None
    visual_query_variants: list = []
    image_results: list = []

    if ctx.include_visuals:
        # yield is unavailable inside the callback, so phases are queued and drained after.
        pending: list = []
        visual_kwargs: Dict[str, Any] = {}
        if ctx.report_progress:
            async def _phase_cb(name: str, label: str) -> None:
                pending.append(phase(name, label))
            visual_kwargs["phase_cb"] = _phase_cb

        vis = await _retrieve_visual_context(
            video_hash,
            retrieval_question,
            req.n_images or 6,
            user_visual_terms=user_visual_terms,
            user_visual_phrases=user_visual_phrases,
            **visual_kwargs,
        )
        for event in pending:
            yield event
        if vis.get("images_indexed"):
            image_paths = vis["image_paths"]
            visual_context = vis["visual_context"]
            visual_sources = vis["visual_sources"]
            visual_query_used = vis["visual_query_used"]
            visual_query_variants = vis.get("visual_query_variants", [])
            image_results = vis["image_results"]

    if ctx.report_progress and transcript_embedding_service.audio_events_exist(video_hash, ctx.user_id):
        yield phase("analyzing_audio", "Scanning audio events")
    audio_context, audio_sources, _ = await _retrieve_audio_context(
        video_hash, retrieval_question, search_results, image_results
    )

    retrieved = Retrieved(
        question=question,
        context=context,
        sources=sources,
        image_paths=image_paths,
        visual_context=visual_context,
        visual_sources=visual_sources,
        visual_query_used=visual_query_used,
        visual_query_variants=visual_query_variants,
        audio_context=audio_context,
        audio_sources=audio_sources,
    )
    if not retrieved.all_sources:
        yield EarlyAnswer(
            response=_no_results(ctx),
            metered=False,
            visual_query_used=visual_query_used,
            visual_query_variants=visual_query_variants,
        )
        return
    yield retrieved


async def prepare_generation(ctx: ChatContext, retrieved: Retrieved) -> AsyncIterator[Union[dict, Prepared]]:
    req = ctx.chat_request
    provider = await _get_chat_provider(ctx.request, ctx.provider_name, req.model, req.reasoning_effort)
    provider_supports_vision = provider.supports_vision()
    has_screenshots = ctx.include_visuals and bool(retrieved.image_paths)

    visual_context = retrieved.visual_context
    if has_screenshots and not provider_supports_vision:
        observations = _generate_visual_observations_with_fallback(
            request=ctx.request,
            question=retrieved.question,
            image_paths=retrieved.image_paths,
            visual_context=visual_context,
            final_provider_name=ctx.provider_name,
        )
        if ctx.report_progress:
            inspecting = phase("analyzing_visuals", "Inspecting screenshots")
            yield inspecting
            task = asyncio.create_task(observations)
            async for beat in _await_with_heartbeat(task, inspecting):
                yield beat
            fallback_visual_context = task.result()
        else:
            fallback_visual_context = await observations
        if fallback_visual_context:
            visual_context = fallback_visual_context

    # Built after provider resolution so non-vision providers get the
    # observations as text instead of image payloads.
    use_images = has_screenshots and provider_supports_vision
    messages = _build_chat_messages(
        question=retrieved.question,
        context=retrieved.context,
        visual_context=visual_context,
        audio_context=retrieved.audio_context,
        has_images=use_images,
        custom_instructions=req.custom_instructions,
        conversation_history=req.conversation_history,
    )
    yield Prepared(
        provider=provider,
        messages=messages,
        image_paths=retrieved.image_paths,
        use_images=use_images,
        text_only_with_images=has_screenshots and not provider_supports_vision,
    )


async def generate_answer(prepared: Prepared, provider_name: Optional[str]) -> str:
    provider = prepared.provider
    if prepared.use_images:
        print(f"Using vision-capable model for analysis with {len(prepared.image_paths)} images")
        return await provider.generate_with_images(
            prepared.messages,
            prepared.image_paths,
            temperature=0.7,
            max_tokens=2000
        )
    if prepared.text_only_with_images:
        print(f"Provider {provider_name} is text-only; using text prompt with vision fallback observations when available.")
    return await provider.generate(prepared.messages, temperature=0.7, max_tokens=2000)


async def stream_answer(prepared: Prepared, provider_name: Optional[str]) -> AsyncIterator[Dict[str, Any]]:
    provider = prepared.provider
    messages = prepared.messages
    yield phase("generating", "Writing answer")

    if prepared.use_images:
        print(f"Using vision-capable model for analysis with {len(prepared.image_paths)} images")
        # Vision providers don't stream, so the call blocks for ~10s with no
        # bytes on the socket; heartbeats keep proxies from dropping it.
        vision_task = asyncio.create_task(
            provider.generate_with_images(
                messages,
                prepared.image_paths,
                temperature=0.7,
                max_tokens=2000,
            )
        )
        while not vision_task.done():
            try:
                await asyncio.wait_for(
                    asyncio.shield(vision_task), timeout=HEARTBEAT_SECONDS
                )
            except asyncio.TimeoutError:
                yield phase("generating", "Writing answer")
            except BaseException as e:
                print(f"[chat/stream] vision task interrupted before completion: {type(e).__name__}: {e}")
                break
        vision_err: Optional[BaseException] = None
        text_err: Optional[Exception] = None
        try:
            answer = vision_task.result()
        except BaseException as e:
            vision_err = e
            print(f"[chat/stream] generate_with_images failed: {type(e).__name__}: {e}")
            answer = ""
        answer = (answer or "").strip()
        print(f"[chat/stream] vision answer length: {len(answer)}")
        if answer:
            _has_direct = "## direct answer" in answer.lower()
            _has_visual = "## visual observation" in answer.lower()
            print(
                f"[chat/stream] headings present — direct_answer={_has_direct} "
                f"visual_observations={_has_visual} "
                f"preview={answer[:160]!r}"
            )
        if len(answer) < 20:
            print("[chat/stream] Vision returned empty/short; falling back to text-only generate()")
            try:
                answer = await provider.generate(messages, temperature=0.7, max_tokens=2000)
            except Exception as e:
                text_err = e
                print(f"[chat/stream] text fallback after vision failed: {e}")
                answer = ""
            print(f"[chat/stream] text fallback returned {len(answer or '')} chars")
        if answer:
            yield {"type": "token", "content": answer}
        elif vision_err or text_err:
            # Surface the provider error instead of pretending the model returned nothing.
            yield provider_error_event(text_err or vision_err, provider_name)
        else:
            yield {
                "type": "token",
                "content": "The model did not return an answer for this query. Try rephrasing, or turn off visual analysis."
            }
        return

    if prepared.text_only_with_images:
        print(f"Provider {provider_name} is text-only; using text prompt with vision fallback observations when available.")
    streamed_chunks: list[str] = []
    chunk_count = 0
    stream_err: Optional[Exception] = None
    gen_err: Optional[Exception] = None
    try:
        async for chunk in provider.generate_stream(messages, temperature=0.7, max_tokens=2000):
            chunk_count += 1
            streamed_chunks.append(chunk)
            yield {"type": "token", "content": chunk}
    except Exception as e:
        stream_err = e
        print(f"[chat/stream] generate_stream raised: {e}")
    total_streamed = "".join(streamed_chunks).strip()
    print(
        f"[chat/stream] provider={provider_name or llm_manager.default_provider} "
        f"chunks={chunk_count} total_chars={len(total_streamed)}"
    )
    # Some providers (e.g. xAI reasoning models) emit no delta.content, so a
    # near-empty stream falls back to one non-streaming call.
    if len(total_streamed) < 20:
        print("[chat/stream] Streaming output too short; falling back to generate()")
        try:
            answer = await provider.generate(messages, temperature=0.7, max_tokens=2000)
        except Exception as e:
            gen_err = e
            print(f"[chat/stream] generate() fallback failed: {e}")
            answer = ""
        print(f"[chat/stream] fallback generate() returned {len(answer or '')} chars")
        if chunk_count > 0:
            yield {"type": "reset"}
        if answer:
            yield {"type": "token", "content": answer}
        elif stream_err or gen_err:
            yield provider_error_event(gen_err or stream_err, provider_name)
