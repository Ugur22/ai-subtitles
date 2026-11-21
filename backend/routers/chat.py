"""
Chat and RAG (Retrieval-Augmented Generation) endpoints
"""
import json
from typing import AsyncIterator, Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import StreamingResponse

from middleware.auth import require_auth
from models import (
    ChatRequest,
    ChatResponse,
    ComparisonSwapRequest,
    ErrorResponse,
    IndexImagesResponse,
    IndexVideoResponse,
    ProviderModelsResponse,
    TestLLMRequest,
    TestLLMResponse,
)
from services.image_embedding_service import image_embedding_service
from services.model_catalog import list_models, reasoning_effort_options
from services.transcript_embedding_service import transcript_embedding_service
from services.transcription_access import authenticated_user_id
from services.transcription_repository import transcription_repository
from services.chat.comparison.appearances import (
    _load_face_tag_appearances,
    _load_person_appearances_with_fallback,
    _video_duration_seconds,
)
from services.chat.comparison.handler import _run_person_comparison_llm, _select_timeline_candidates
from services.chat.comparison.state_pairs import _same_comparison_frame, _with_comparison_people
from services.chat.context import _chat_user_id, _hash_resources_allowed, _run_in_executor
from services.chat.pipeline import (
    ChatContext,
    ChatPipelineError,
    EarlyAnswer,
    early_answer_events,
    final_result,
    generate_answer,
    prepare_generation,
    provider_error_event,
    retrieve,
    stream_answer,
)
from services.chat.providers import (
    LLM_AVAILABLE,
    _classify_provider_error,
    _get_chat_provider,
    _get_saved_provider_key,
    _provider_error_message,
    _provider_http_status,
    _request_user_id,
    _stored_key_provider_name,
    llm_manager,
)
from services.chat.visual_refs import _load_speaker_reference_embedding


def _authorize_video(request: Request, video_hash: Optional[str]) -> tuple[str, Dict]:
    if not video_hash:
        raise HTTPException(status_code=400, detail="video_hash is required")
    user_id = authenticated_user_id(request)
    transcription = transcription_repository.get_transcription(video_hash, user_id)
    if not transcription:
        raise HTTPException(status_code=404, detail="Transcription not found")
    _chat_user_id.set(user_id)
    _hash_resources_allowed.set(True)
    return user_id, transcription


def _meter_chat_message(user_id: Optional[str], log_tag: str) -> None:
    # Best-effort: metering must never fail a chat answer.
    from services.usage_meter import record_chat_message
    try:
        record_chat_message(user_id, llm_tokens=0)
    except Exception as _meter_err:
        print(f"[{log_tag}] meter failed: {_meter_err}")


router = APIRouter(prefix="/api", tags=["Chat & RAG"])


@router.post(
    "/index_video/",
    response_model=IndexVideoResponse,
    summary="Index video for chat",
    description="Index a video's transcription for chat/Q&A using vector search",
    responses={
        503: {"model": ErrorResponse, "description": "LLM features not available"},
        404: {"model": ErrorResponse, "description": "Transcription not found"}
    }
)
@require_auth
async def index_video_for_chat(request: Request, video_hash: str = None) -> IndexVideoResponse:
    """
    Index a video's transcription for chat/Q&A

    Args:
        video_hash: Optional video hash. If not provided, uses last transcription
    """
    if not LLM_AVAILABLE:
        raise HTTPException(status_code=503, detail="LLM features not available. Install required dependencies.")

    try:
        user_id, transcription = _authorize_video(request, video_hash)

        # Get segments
        segments = transcription.get('transcription', {}).get('segments', [])
        if not segments:
            raise HTTPException(status_code=400, detail="No segments found in transcription")

        # Index in vector database (run in executor to avoid blocking)
        print(f"Indexing video {video_hash} with {len(segments)} segments...")
        num_chunks = await _run_in_executor(
            transcript_embedding_service.index_transcript_chunks, video_hash, segments, user_id
        )

        # Also index audio events if segments contain audio analysis data
        audio_indexed = 0
        try:
            audio_indexed = await _run_in_executor(
                transcript_embedding_service.index_audio_events, video_hash, segments, user_id
            )
            if audio_indexed > 0:
                print(f"Audio events indexed: {audio_indexed}")
        except Exception as e:
            print(f"Audio indexing during chat index failed (non-critical): {str(e)}")

        return IndexVideoResponse(
            success=True,
            video_hash=video_hash,
            segments_count=len(segments),
            chunks_indexed=num_chunks,
            message=f"Successfully indexed {num_chunks} chunks from {len(segments)} segments"
        )
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error indexing video: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Failed to index video: {str(e)}")


@router.post(
    "/chat/",
    response_model=ChatResponse,
    summary="Chat with video",
    description="Chat with a video using RAG (Retrieval-Augmented Generation)",
    responses={
        503: {"model": ErrorResponse, "description": "LLM features not available"},
        404: {"model": ErrorResponse, "description": "Video not found"},
        400: {"model": ErrorResponse, "description": "Invalid request"}
    }
)
@require_auth
async def chat_with_video(request: Request, chat_request: ChatRequest) -> Dict:
    """
    Chat with a video using RAG (Retrieval-Augmented Generation)
    """
    if not LLM_AVAILABLE:
        raise HTTPException(status_code=503, detail="LLM features not available")

    # Plan gate: free tier has chat disabled; admins always pass
    from middleware.quota import check_can_chat
    check_can_chat(getattr(request.state, "profile", None))
    _quota_user_id = (request.state.profile or {}).get("id") if hasattr(request.state, "profile") else None

    # Guard: wait for models to finish preloading on cold start
    from model_preloader import models_ready, wait_for_models
    if not models_ready():
        if not wait_for_models(timeout=5.0):
            # video_hash is required by ChatResponse — omitting it turns this
            # friendly cold-start message into a 500 ResponseValidationError.
            return {
                "answer": "The server just started and is still loading AI models. Please try again in about 30 seconds.",
                "sources": [],
                "video_hash": chat_request.video_hash,
                "provider_used": "none",
            }

    try:
        provider_name = chat_request.provider
        # Checked before authorization so a missing question stays a 400.
        if not chat_request.question:
            raise HTTPException(status_code=400, detail="Question is required")

        user_id, owned_transcription = _authorize_video(request, chat_request.video_hash)
        ctx = ChatContext(request, chat_request, user_id, owned_transcription)

        retrieved = await final_result(retrieve(ctx))
        if isinstance(retrieved, EarlyAnswer):
            if retrieved.metered:
                _meter_chat_message(_quota_user_id, "chat")
            return retrieved.response

        try:
            prepared = await final_result(prepare_generation(ctx, retrieved))
            answer = await generate_answer(prepared, provider_name)
        except HTTPException:
            raise
        except Exception as e:
            print(f"[chat] provider generation failed: {type(e).__name__}: {e}")
            raise HTTPException(
                status_code=_provider_http_status(e),
                detail=_provider_error_message(e, provider_name),
                headers={"X-LLM-Error-Code": _classify_provider_error(e)},
            )

        from config import settings
        if settings.CHAT_DEBUG_LOGS:
            print(f"DEBUG: text sources: {len(retrieved.sources)}, visual sources: {len(retrieved.visual_sources)}, audio sources: {len(retrieved.audio_sources)}")
            if retrieved.audio_sources:
                print(f"DEBUG: First audio source: {retrieved.audio_sources[0]}")

        response = {
            "answer": answer,
            "sources": retrieved.all_sources,
            "provider_used": provider_name or llm_manager.default_provider,
            "video_hash": chat_request.video_hash
        }

        if retrieved.visual_query_used:
            response["visual_query_used"] = retrieved.visual_query_used
        if retrieved.visual_query_variants:
            response["visual_query_variants"] = retrieved.visual_query_variants

        _meter_chat_message(_quota_user_id, "chat")
        return response

    except ChatPipelineError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error in chat: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Chat failed: {str(e)}")


@router.post(
    "/chat/comparison/swap",
    response_model=ChatResponse,
    summary="Swap a frame in an active Person Comparison",
    description=(
        "Re-run the vision LLM comparison with a specific Frame A + Frame B pair. "
        "Used by the timeline strip to swap Frame B (or A) while preserving the original "
        "question, custom instructions, and joint-frame enrichment for multi-person comparisons."
    ),
    responses={
        503: {"model": ErrorResponse, "description": "LLM features not available"},
        404: {"model": ErrorResponse, "description": "Person or frame not found"},
        422: {"model": ErrorResponse, "description": "No appearance found near requested timestamp"},
        400: {"model": ErrorResponse, "description": "Invalid request"},
    },
)
@require_auth
async def swap_comparison_frame(
    request: Request,
    swap_request: ComparisonSwapRequest,
) -> Dict:
    """Re-run a Person Comparison with a caller-specified pair of frames."""
    if not LLM_AVAILABLE:
        raise HTTPException(status_code=503, detail="LLM features not available")

    from middleware.quota import check_can_chat
    from services.usage_meter import record_chat_message
    check_can_chat(getattr(request.state, "profile", None))
    _quota_user_id = (request.state.profile or {}).get("id") if hasattr(request.state, "profile") else None

    from model_preloader import models_ready, wait_for_models
    if not models_ready():
        if not wait_for_models(timeout=5.0):
            raise HTTPException(
                status_code=503,
                detail="Models are still loading. Please try again in about 30 seconds.",
            )

    if not swap_request.question:
        raise HTTPException(status_code=400, detail="question is required")
    if not swap_request.person:
        raise HTTPException(status_code=400, detail="person is required")

    video_hash = swap_request.video_hash
    _authorize_video(request, video_hash)

    try:
        appearances = await _load_person_appearances_with_fallback(video_hash, swap_request.person)
        if not appearances:
            # Last-ditch fallback to manual face-tag appearances.
            reference_embedding = _load_speaker_reference_embedding(video_hash, swap_request.person)
            if reference_embedding:
                appearances = _load_face_tag_appearances(
                    video_hash, swap_request.person, reference_embedding
                )

        if not appearances:
            raise HTTPException(
                status_code=404,
                detail=f"No face appearances found for '{swap_request.person}'.",
            )

        def _nearest(target_seconds: float) -> Optional[dict]:
            best = None
            best_gap = float("inf")
            for row in appearances:
                t = float(row.get("start_time") or 0.0)
                gap = abs(t - target_seconds)
                if gap < best_gap:
                    best = row
                    best_gap = gap
            # Tolerance: within 2 seconds OR within one frame-sample window.
            if best is None or best_gap > 2.0:
                return None
            return best

        frame_a_appearance = _nearest(swap_request.frame_a_seconds)
        frame_b_appearance = _nearest(swap_request.frame_b_seconds)

        if frame_a_appearance is None:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"No appearance of '{swap_request.person}' within 2s of "
                    f"frame_a_seconds={swap_request.frame_a_seconds}."
                ),
            )
        if frame_b_appearance is None:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"No appearance of '{swap_request.person}' within 2s of "
                    f"frame_b_seconds={swap_request.frame_b_seconds}."
                ),
            )

        if _same_comparison_frame(frame_a_appearance, frame_b_appearance):
            raise HTTPException(
                status_code=400,
                detail="Frame A and Frame B resolve to the same appearance; pick a different moment.",
            )

        video_duration = _video_duration_seconds(video_hash, appearances)

        # For multi-person comparisons, recover joint-frame enrichment on Frame A if it
        # actually contains the secondary person too. Frame B stays primary-only by design.
        if swap_request.secondary_person:
            secondary_appearances = await _load_person_appearances_with_fallback(
                video_hash, swap_request.secondary_person
            )
            video_duration = _video_duration_seconds(
                video_hash, [*appearances, *secondary_appearances]
            )
            joint_match = None
            for secondary in secondary_appearances:
                if _same_comparison_frame(frame_a_appearance, secondary):
                    joint_match = secondary
                    break
            if joint_match is not None:
                frame_a_appearance = _with_comparison_people(
                    frame_a_appearance,
                    [
                        (swap_request.person, frame_a_appearance.get("bbox")),
                        (swap_request.secondary_person, joint_match.get("bbox")),
                    ],
                    f"{swap_request.person} with {swap_request.secondary_person}",
                )
            frame_b_appearance = _with_comparison_people(
                frame_b_appearance,
                [(swap_request.person, frame_b_appearance.get("bbox"))],
                f"{swap_request.person} later",
            )

        timeline_appearances = _select_timeline_candidates(
            appearances,
            (frame_a_appearance, frame_b_appearance),
            video_duration,
        )

        try:
            response = await _run_person_comparison_llm(
                request,
                person_name=swap_request.person,
                secondary_person_name=swap_request.secondary_person,
                frame_a_appearance=frame_a_appearance,
                frame_b_appearance=frame_b_appearance,
                question=swap_request.question,
                custom_instructions=swap_request.custom_instructions,
                provider_name=swap_request.provider,
                video_hash=video_hash,
                timeline_appearances=timeline_appearances,
                model=swap_request.model,
                reasoning_effort=swap_request.reasoning_effort,
            )
        except HTTPException:
            raise
        except Exception as e:
            print(f"[chat] comparison swap provider generation failed: {type(e).__name__}: {e}")
            raise HTTPException(
                status_code=_provider_http_status(e),
                detail=_provider_error_message(e, swap_request.provider),
                headers={"X-LLM-Error-Code": _classify_provider_error(e)},
            )

        try:
            record_chat_message(_quota_user_id, llm_tokens=0)
        except Exception as _meter_err:
            print(f"[chat] meter failed: {_meter_err}")

        return response

    except HTTPException:
        raise
    except Exception as e:
        print(f"Error in comparison swap: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Comparison swap failed: {str(e)}")


@router.post(
    "/chat/stream",
    summary="Chat with video (streaming)",
    description="Chat with a video using RAG with Server-Sent Events streaming",
    responses={
        503: {"model": ErrorResponse, "description": "LLM features not available"},
    }
)
@require_auth
async def chat_with_video_stream(request: Request, chat_request: ChatRequest) -> StreamingResponse:
    """
    Chat with a video using RAG with Server-Sent Events streaming.

    Emits one JSON object per SSE data line. Event types:
      phase   - pipeline stage progress
      sources - retrieved context metadata
      token   - LLM output chunk
      reset   - discard streamed tokens before a fallback answer
      done    - final completion signal
      error   - pipeline failure
    """
    if not LLM_AVAILABLE:
        raise HTTPException(status_code=503, detail="LLM features not available")

    # Plan gate: free tier has chat disabled; admins always pass
    from middleware.quota import check_can_chat
    check_can_chat(getattr(request.state, "profile", None))
    _stream_user_id = (request.state.profile or {}).get("id") if hasattr(request.state, "profile") else None
    user_id, owned_transcription = _authorize_video(request, chat_request.video_hash)
    ctx = ChatContext(request, chat_request, user_id, owned_transcription, report_progress=True)
    provider_name = chat_request.provider

    from model_preloader import models_ready, wait_for_models

    async def _event_stream() -> AsyncIterator[str]:
        def _sse(event: dict) -> str:
            return f"data: {json.dumps(event)}\n\n"

        # Model preload guard
        if not models_ready():
            if not wait_for_models(timeout=5.0):
                yield _sse({
                    "type": "error",
                    "message": "The server just started and is still loading AI models. Please try again in about 30 seconds."
                })
                return

        try:
            retrieved = None
            async for item in retrieve(ctx):
                if isinstance(item, dict):
                    yield _sse(item)
                else:
                    retrieved = item

            if isinstance(retrieved, EarlyAnswer):
                for event in early_answer_events(retrieved, provider_name, chat_request.video_hash):
                    yield _sse(event)
                if retrieved.metered:
                    _meter_chat_message(_stream_user_id, "chat/stream")
                return

            prepared = None
            async for item in prepare_generation(ctx, retrieved):
                if isinstance(item, dict):
                    yield _sse(item)
                else:
                    prepared = item

            yield _sse({
                "type": "sources",
                "sources": retrieved.all_sources,
                "visual_query_used": retrieved.visual_query_used,
                "visual_query_variants": retrieved.visual_query_variants,
            })

            async for event in stream_answer(prepared, provider_name):
                yield _sse(event)

            yield _sse({
                "type": "done",
                "provider_used": provider_name or llm_manager.default_provider,
                "video_hash": chat_request.video_hash
            })
            _meter_chat_message(_stream_user_id, "chat/stream")

        except ChatPipelineError as e:
            yield _sse({"type": "error", "message": e.message})
        except Exception as e:
            print(f"Error in streaming chat: {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()
            yield _sse(provider_error_event(e, provider_name, detail=f"{type(e).__name__}: {e}"))

    return StreamingResponse(
        _event_stream(),
        media_type="text/event-stream",
        headers={
            "X-Accel-Buffering": "no",
            "Cache-Control": "no-cache",
        }
    )


@router.get(
    "/llm/providers",
    response_model=Dict,
    summary="List LLM providers",
    description="List all available LLM providers and their status",
    responses={
        503: {"model": ErrorResponse, "description": "LLM features not available"}
    }
)
@require_auth
async def list_llm_providers(request: Request) -> Dict:
    """List all available LLM providers and their status"""
    if not LLM_AVAILABLE:
        raise HTTPException(status_code=503, detail="LLM features not available")

    try:
        providers = llm_manager.list_available_providers()

        user_id = _request_user_id(request)

        saved_key_providers = set()
        if user_id:
            try:
                from services.supabase_service import SupabaseService
                client = SupabaseService.get_client()
                response = (
                    client.table("user_api_keys")
                    .select("provider")
                    .eq("user_id", user_id)
                    .eq("is_valid", True)
                    .execute()
                )
                saved_key_providers = {row["provider"] for row in (response.data or [])}
            except Exception as key_err:
                print(f"[Chat] Could not load saved provider availability: {key_err}")

        for provider in providers:
            key_provider = _stored_key_provider_name(provider.get("name"))
            provider["available"] = key_provider is not None and key_provider in saved_key_providers
        return {
            "providers": providers,
            "default": llm_manager.default_provider
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/llm/providers/{provider_name}/models",
    response_model=ProviderModelsResponse,
    summary="List models for an LLM provider",
    description="Models the provider's own API currently offers; falls back to the configured default.",
)
@require_auth
async def list_provider_models(request: Request, provider_name: str) -> ProviderModelsResponse:
    if not LLM_AVAILABLE:
        raise HTTPException(status_code=503, detail="LLM features not available")

    saved_key = await _get_saved_provider_key(_request_user_id(request), provider_name)
    if not saved_key:
        return ProviderModelsResponse(models=[], source="fallback")
    try:
        provider = llm_manager.get_provider(provider_name, api_key_override=saved_key)
    except ValueError:
        raise HTTPException(status_code=404, detail=f"Unknown provider: {provider_name}")
    except Exception:
        # Known provider with no usable key: nothing to list, and chat will report it.
        return ProviderModelsResponse(models=[], source="fallback")

    default_model = getattr(provider, "model", None)
    catalog_name = _stored_key_provider_name(provider_name)
    models: List[str] = []
    source = "fallback"
    error: Optional[str] = None
    if catalog_name:
        try:
            models = await list_models(catalog_name, provider.api_key)
            source = "api"
        except Exception as e:
            # A picker must not break chat; the default model keeps working.
            error = str(e)[:300]
            print(f"[Chat] Model listing failed for {provider_name}: {error}")

    # Always offer the default so the UI never has to merge it in.
    if default_model and default_model not in models:
        models = [default_model, *models]
    return ProviderModelsResponse(
        models=models, default=default_model, source=source, error=error,
        reasoning_efforts={
            model: options for model in models
            if (options := reasoning_effort_options(catalog_name or provider_name, model))
        },
    )


@router.post(
    "/llm/test",
    response_model=TestLLMResponse,
    summary="Test LLM provider",
    description="Test an LLM provider with a simple prompt",
    responses={
        503: {"model": ErrorResponse, "description": "LLM features not available"}
    }
)
@require_auth
async def test_llm_provider(request: Request, test_request: TestLLMRequest) -> TestLLMResponse:
    """Test an LLM provider"""
    if not LLM_AVAILABLE:
        raise HTTPException(status_code=503, detail="LLM features not available")

    try:
        provider_name = test_request.provider
        test_prompt = test_request.prompt or "Hello! Please respond with 'OK' if you can read this."

        provider = await _get_chat_provider(request, provider_name)

        # Test with a simple message
        messages = [
            {"role": "user", "content": test_prompt}
        ]

        response = await provider.generate(messages, temperature=0.5, max_tokens=50)

        return TestLLMResponse(
            success=True,
            provider=provider_name or llm_manager.default_provider,
            response=response,
            error=None
        )
    except Exception as e:
        return TestLLMResponse(
            success=False,
            provider=test_request.provider,
            response=None,
            error=str(e)
        )


def _run_index_images_background(
    video_hash: str,
    segments: list,
    force_reindex: bool,
    user_id: str,
):
    """Background worker: run CLIP indexing synchronously (called from BackgroundTasks)."""
    try:
        print(f"[BG] Indexing images for video {video_hash} from {len(segments)} segments using Supabase pgvector...")
        num = image_embedding_service.index_video_images(
            video_hash,
            segments,
            force_reindex=force_reindex,
            user_id=user_id,
        )
        print(f"[BG] Indexing complete: {num} images indexed for video {video_hash}")
    except Exception as e:
        import traceback
        print(f"[BG] Indexing failed for video {video_hash}: {e}")
        traceback.print_exc()


@router.post(
    "/index_images/",
    response_model=IndexImagesResponse,
    summary="Index video images",
    description="Index video screenshots using CLIP embeddings for visual search",
    responses={
        503: {"model": ErrorResponse, "description": "LLM features not available"},
        404: {"model": ErrorResponse, "description": "Transcription not found"}
    }
)
@require_auth
async def index_video_images(request: Request, background_tasks: BackgroundTasks, video_hash: str = None, force_reindex: bool = False) -> IndexImagesResponse:
    """
    Index video screenshots using CLIP embeddings for visual search.
    Returns immediately; indexing runs in the background.

    Args:
        video_hash: Optional video hash. If not provided, uses last transcription
        force_reindex: If True, delete existing index and re-index all images
    """
    if not LLM_AVAILABLE:
        raise HTTPException(status_code=503, detail="LLM features not available. Install required dependencies.")

    try:
        user_id, transcription = _authorize_video(request, video_hash)
        if not _hash_resources_allowed.get():
            raise HTTPException(status_code=409, detail="Visual index is not owner-isolated for this video")

        # Get segments
        segments = transcription.get('transcription', {}).get('segments', [])
        if not segments:
            raise HTTPException(status_code=400, detail="No segments found in transcription")

        # Schedule CLIP indexing as a background task so the request returns immediately
        background_tasks.add_task(
            _run_index_images_background, video_hash, segments, force_reindex, user_id
        )

        return IndexImagesResponse(
            success=True,
            video_hash=video_hash,
            images_indexed=0,
            message=f"Re-indexing started in background ({len(segments)} segments, storage: Supabase pgvector). Visual search will update shortly."
        )
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error starting image indexing: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Failed to start image indexing: {str(e)}")
