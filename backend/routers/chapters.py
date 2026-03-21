"""
Auto Chapter Markers - Detect topic boundaries and generate YouTube-style chapter markers.

Uses semantic break detection via SentenceTransformer embeddings to find where topics
shift, then boosts scores at speaker/audio-event boundaries, and generates short titles
using the configured LLM provider.
"""

import asyncio
import logging
from typing import List, Optional, Dict, Any
from concurrent.futures import ThreadPoolExecutor

import numpy as np
from fastapi import APIRouter, HTTPException, Request, Query
from pydantic import BaseModel

from middleware.auth import require_auth

logger = logging.getLogger(__name__)

# Dedicated executor for CPU-bound embedding work - keeps the event loop unblocked
_chapters_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="chapters_embed")

# Lazily-loaded SentenceTransformer; shared across requests once initialised
_sentence_model = None
_sentence_model_lock = asyncio.Lock()


async def _get_sentence_model():
    """
    Return the SentenceTransformer model, loading it on first call.

    Loading is deferred to request time (not import time) so the application
    starts quickly and the model is only pulled into memory when actually needed.
    """
    global _sentence_model
    if _sentence_model is not None:
        return _sentence_model

    async with _sentence_model_lock:
        # Double-check after acquiring the lock
        if _sentence_model is not None:
            return _sentence_model

        logger.info("[Chapters] Loading SentenceTransformer model (all-MiniLM-L6-v2)...")
        from sentence_transformers import SentenceTransformer

        def _load():
            return SentenceTransformer('all-MiniLM-L6-v2')

        _sentence_model = await asyncio.to_thread(_load)
        logger.info("[Chapters] SentenceTransformer model loaded.")
        return _sentence_model


# ---------------------------------------------------------------------------
# Pydantic response models
# ---------------------------------------------------------------------------

class Chapter(BaseModel):
    start: float
    end: float
    start_time: str   # HH:MM:SS
    end_time: str     # HH:MM:SS
    title: str
    summary: str
    segment_count: int


class ChaptersResponse(BaseModel):
    chapters: List[Chapter]
    video_hash: str
    total_duration: float


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

router = APIRouter(tags=["chapters"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _format_time(seconds: float) -> str:
    """Format a raw seconds value into HH:MM:SS."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Return cosine similarity between two 1-D numpy arrays."""
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(np.dot(a, b) / (norm_a * norm_b))


def _segment_text(segment: Dict[str, Any]) -> str:
    """Prefer translated text over raw ASR text for embedding quality."""
    return segment.get("translation") or segment.get("text", "")


def _make_single_chapter(segments: List[Dict]) -> Dict:
    """Build the raw chapter dict when the video is too short to split."""
    start = segments[0].get("start", 0.0)
    end = segments[-1].get("end", 0.0)
    return {
        "start": start,
        "end": end,
        "text": " ".join(_segment_text(s) for s in segments),
        "segment_count": len(segments),
    }


def _detect_chapter_boundaries(
    segments: List[Dict],
    embeddings: np.ndarray,
    windows: List[Dict],
    min_chapter_duration: int,
) -> List[float]:
    """
    Core algorithm: compute break scores between consecutive windows and select
    the best boundary timestamps while respecting the minimum chapter duration.

    Returns a sorted list of boundary timestamps (not including video start/end).
    """
    similarities = [
        _cosine_similarity(embeddings[i], embeddings[i + 1])
        for i in range(len(embeddings) - 1)
    ]

    break_scores = []
    for i, sim in enumerate(similarities):
        score = 1.0 - sim  # Low similarity -> likely topic change

        # Boost when the set of speakers changes across the window boundary
        curr_speakers = {s.get("speaker", "") for s in windows[i]["segments"]}
        next_speakers = {s.get("speaker", "") for s in windows[i + 1]["segments"]}
        if curr_speakers != next_speakers:
            score += 0.15

        # Boost when a silent segment sits at the boundary (scene cut / pause)
        boundary_segs = windows[i]["segments"][-1:] + windows[i + 1]["segments"][:1]
        if any(s.get("is_silent") for s in boundary_segs):
            score += 0.10

        # Boost when the ambient audio-event profile changes across the boundary
        curr_events = {
            e.get("event_type", "")
            for s in windows[i]["segments"]
            for e in (s.get("audio_events") or [])
        }
        next_events = {
            e.get("event_type", "")
            for s in windows[i + 1]["segments"]
            for e in (s.get("audio_events") or [])
        }
        if curr_events.symmetric_difference(next_events):
            score += 0.05

        break_scores.append({
            "index": i,
            "score": score,
            "time": windows[i + 1]["start"],
        })

    # Determine how many chapters we can fit
    total_duration = segments[-1].get("end", 0.0) - segments[0].get("start", 0.0)
    max_chapters = max(2, int(total_duration / min_chapter_duration))

    # Greedily pick highest-scoring breaks, enforcing minimum gap
    break_scores.sort(key=lambda x: x["score"], reverse=True)
    selected: List[Dict] = []
    for candidate in break_scores:
        if len(selected) >= max_chapters - 1:
            break
        too_close = any(
            abs(candidate["time"] - existing["time"]) < min_chapter_duration
            for existing in selected
        )
        if not too_close:
            selected.append(candidate)

    selected.sort(key=lambda x: x["time"])
    return [b["time"] for b in selected]


async def _generate_chapter_title(
    provider_name: str,
    chapter_text: str,
) -> str:
    """
    Ask the configured LLM to produce a very short (3-7 word) chapter title.

    Falls back to an empty string on any error so the caller can substitute
    a generic "Chapter N" label without crashing.
    """
    try:
        from llm_providers import llm_manager

        provider = llm_manager.get_provider(provider_name)
        truncated = chapter_text[:1000]
        messages = [
            {
                "role": "system",
                "content": (
                    "You are a chapter title generator. "
                    "Return ONLY a short, descriptive title - no explanation."
                ),
            },
            {
                "role": "user",
                "content": (
                    "Generate a very short title (3-7 words) for this section of a video "
                    "transcript. Return ONLY the title, nothing else.\n\n"
                    f"Transcript:\n{truncated}"
                ),
            },
        ]
        title = await provider.generate(messages, temperature=0.4, max_tokens=30)
        return title.strip().strip('"').strip("'")
    except Exception as exc:
        logger.warning("[Chapters] LLM title generation failed: %s", exc)
        return ""


async def _detect_chapters(
    segments: List[Dict],
    model,
    min_chapter_duration: int,
) -> List[Dict]:
    """
    Full chapter detection pipeline:
    1. Group segments into windows
    2. Embed windows
    3. Score window boundaries
    4. Select optimal break points
    5. Build chapter dicts (text only, no titles yet)
    """
    if len(segments) < 10:
        logger.info("[Chapters] Too few segments (%d) - returning single chapter.", len(segments))
        return [_make_single_chapter(segments)]

    # --- Step 1: group into windows of 5 segments ---
    window_size = 5
    windows = []
    for i in range(0, len(segments), window_size):
        chunk = segments[i: i + window_size]
        windows.append({
            "text": " ".join(_segment_text(s) for s in chunk),
            "segments": chunk,
            "start": chunk[0].get("start", 0.0),
            "end": chunk[-1].get("end", 0.0),
        })

    if len(windows) < 3:
        logger.info("[Chapters] Too few windows (%d) - returning single chapter.", len(windows))
        return [_make_single_chapter(segments)]

    # --- Step 2: compute embeddings (CPU-bound, off the event loop) ---
    texts = [w["text"] for w in windows]
    embeddings = await asyncio.to_thread(model.encode, texts)

    # --- Steps 3-4: detect breaks ---
    boundary_times = _detect_chapter_boundaries(
        segments, embeddings, windows, min_chapter_duration
    )

    logger.info(
        "[Chapters] Selected %d break points for %d windows.",
        len(boundary_times),
        len(windows),
    )

    # --- Step 5: build raw chapter dicts ---
    video_start = segments[0].get("start", 0.0)
    video_end = segments[-1].get("end", 0.0)

    chapter_boundaries = [video_start] + boundary_times + [video_end]

    chapters = []
    for i in range(len(chapter_boundaries) - 1):
        ch_start = chapter_boundaries[i]
        ch_end = chapter_boundaries[i + 1]
        ch_segs = [
            s for s in segments
            if s.get("start", 0.0) >= ch_start and s.get("start", 0.0) < ch_end
        ]
        if not ch_segs:
            continue
        chapters.append({
            "start": ch_start,
            "end": ch_end,
            "text": " ".join(_segment_text(s) for s in ch_segs),
            "segment_count": len(ch_segs),
        })

    return chapters


def _load_segments_from_supabase(video_hash: str) -> List[Dict]:
    """
    Synchronous helper that queries Supabase for the most recent completed job
    and extracts the transcription segments from result_json.

    Raises HTTPException with appropriate status codes on failure.
    This is a sync function so it can be called directly; awaiting is handled
    by the caller via asyncio.to_thread if needed.
    """
    from services.supabase_service import supabase

    client = supabase()
    response = (
        client.table("jobs")
        .select("result_json")
        .eq("video_hash", video_hash)
        .eq("status", "completed")
        .order("completed_at", desc=True)
        .limit(1)
        .execute()
    )

    if not response.data:
        raise HTTPException(
            status_code=404,
            detail=f"No completed transcription found for video_hash={video_hash}",
        )

    result_json = response.data[0].get("result_json")
    if not result_json:
        raise HTTPException(
            status_code=404,
            detail="Job found but result_json is empty.",
        )

    segments = (
        result_json.get("transcription", {}).get("segments")
        or result_json.get("segments")
    )
    if not segments:
        raise HTTPException(
            status_code=422,
            detail="No segments found in transcription result.",
        )

    return segments


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post(
    "/generate/{video_hash}",
    response_model=ChaptersResponse,
    summary="Generate chapter markers for a video",
    description=(
        "Detects topic boundaries in the transcription using semantic similarity, "
        "boosts scores at speaker/audio-event transitions, then generates a short "
        "LLM title for each chapter."
    ),
)
@require_auth
async def generate_chapters(
    request: Request,
    video_hash: str,
    provider: Optional[str] = Query(
        default=None,
        description="LLM provider for title generation (groq, grok, ollama, ...). "
                    "Defaults to the server-configured default.",
    ),
    min_chapter_duration: int = Query(
        default=120,
        ge=30,
        le=1800,
        description="Minimum chapter length in seconds (default 120 = 2 minutes).",
    ),
) -> ChaptersResponse:
    """
    Generate YouTube-style chapter markers for a transcribed video.

    The algorithm:
    1. Load segments from the Supabase jobs table
    2. Group into 5-segment windows and embed with SentenceTransformer
    3. Score window boundaries (cosine similarity valley detection)
    4. Boost scores at speaker / audio-event transitions
    5. Select breaks respecting min_chapter_duration
    6. Generate a short LLM title for each chapter
    """
    logger.info(
        "[Chapters] generate_chapters called: video_hash=%s provider=%s min_dur=%d",
        video_hash,
        provider,
        min_chapter_duration,
    )

    # --- Load segments ---
    # Supabase client is synchronous; run in thread to avoid blocking the loop.
    try:
        segments = await asyncio.to_thread(_load_segments_from_supabase, video_hash)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("[Chapters] Unexpected error loading segments: %s", exc)
        raise HTTPException(status_code=500, detail=f"Failed to load transcription: {exc}")

    logger.info("[Chapters] Loaded %d segments.", len(segments))

    # --- Load model ---
    try:
        model = await _get_sentence_model()
    except Exception as exc:
        logger.exception("[Chapters] Failed to load sentence model: %s", exc)
        raise HTTPException(status_code=500, detail="Embedding model unavailable.")

    # --- Detect chapter structure ---
    try:
        raw_chapters = await _detect_chapters(segments, model, min_chapter_duration)
    except Exception as exc:
        logger.exception("[Chapters] Chapter detection failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"Chapter detection failed: {exc}")

    # --- Resolve LLM provider name ---
    # Use what the caller specified; fall back to the manager's default.
    try:
        from llm_providers import llm_manager
        provider_name = provider or llm_manager.default_provider
    except Exception:
        provider_name = provider or "groq"

    # --- Generate titles concurrently ---
    title_tasks = [
        _generate_chapter_title(provider_name, ch["text"])
        for ch in raw_chapters
    ]
    titles = await asyncio.gather(*title_tasks)

    # --- Build final response ---
    chapters: List[Chapter] = []
    for i, (ch, title) in enumerate(zip(raw_chapters, titles), start=1):
        # Fallback title when the LLM returns empty / fails
        final_title = title if title else f"Chapter {i}"

        # Use first ~200 chars of the chapter text as summary
        summary_text = ch["text"][:200].strip()
        if len(ch["text"]) > 200:
            summary_text += "..."

        chapters.append(
            Chapter(
                start=ch["start"],
                end=ch["end"],
                start_time=_format_time(ch["start"]),
                end_time=_format_time(ch["end"]),
                title=final_title,
                summary=summary_text,
                segment_count=ch["segment_count"],
            )
        )

    total_duration = segments[-1].get("end", 0.0) - segments[0].get("start", 0.0)

    logger.info(
        "[Chapters] Returning %d chapters for video_hash=%s (total duration %.1fs).",
        len(chapters),
        video_hash,
        total_duration,
    )

    return ChaptersResponse(
        chapters=chapters,
        video_hash=video_hash,
        total_duration=total_duration,
    )


@router.get(
    "/{video_hash}",
    response_model=ChaptersResponse,
    summary="Get cached chapters for a video",
    description=(
        "Returns 404 until chapters are generated via POST /generate/{video_hash}. "
        "Caching is not yet implemented; use the POST endpoint to generate chapters."
    ),
)
@require_auth
async def get_chapters(request: Request, video_hash: str) -> ChaptersResponse:
    """
    Placeholder for cached chapter retrieval.

    Currently always returns 404. Clients should call POST /generate/{video_hash}
    to generate chapters on demand. A persistent cache (Supabase column or
    separate table) can be added in a future iteration without changing this
    endpoint's contract.
    """
    raise HTTPException(
        status_code=404,
        detail=(
            "No cached chapters found. "
            "Use POST /api/chapters/generate/{video_hash} to generate them."
        ),
    )
