"""
Chat and RAG (Retrieval-Augmented Generation) endpoints
"""
import asyncio
import json
import re
from dataclasses import dataclass
from typing import AsyncIterator, Dict, Optional, List, Callable, Any, Awaitable
from concurrent.futures import ThreadPoolExecutor
from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import StreamingResponse

# Executor for CPU/GPU-bound operations (CLIP, embeddings, ChromaDB)
# This prevents blocking the event loop during visual search and chat operations
_chat_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="chat_embed")


async def _run_in_executor(func: Callable, *args, **kwargs) -> Any:
    """Run blocking function in executor to avoid blocking event loop."""
    loop = asyncio.get_event_loop()
    if kwargs:
        return await loop.run_in_executor(_chat_executor, lambda: func(*args, **kwargs))
    return await loop.run_in_executor(_chat_executor, func, *args)

from database import get_transcription
from dependencies import _last_transcription_data
from middleware.auth import require_auth


def _classify_provider_error(err: Optional[BaseException]) -> str:
    """Map a provider exception to a short error code the frontend can switch on.

    Codes:
      - llm_config: API key missing/invalid
      - llm_provider_quota: provider account credits/quota exhausted
      - llm_rate_limited: 429 from provider
      - llm_unavailable: 5xx, timeout, connection refused
      - llm_image_403: vision pipeline could not load screenshots (stale URLs)
      - llm_unknown: anything else
    """
    if err is None:
        return "llm_unknown"
    msg = (str(err) or "").lower()
    if "api key" in msg or "unauthorized" in msg or "401" in msg or "xai_api_key_missing" in msg:
        return "llm_config"
    if (
        "credit" in msg
        or "insufficient balance" in msg
        or "insufficient_quota" in msg
        or "payment required" in msg
        or "billing" in msg
        or "usage limit" in msg
    ):
        return "llm_provider_quota"
    if "429" in msg or "rate limit" in msg or "quota" in msg:
        return "llm_rate_limited"
    if "timeout" in msg or "timed out" in msg or "connecterror" in msg or "5xx" in msg:
        return "llm_unavailable"
    for code in ("500", "502", "503", "504"):
        if code in msg:
            return "llm_unavailable"
    if "403" in msg and ("storage.googleapis" in msg or "screenshot" in msg or "image" in msg):
        return "llm_image_403"
    return "llm_unknown"


def _provider_error_message(err: Optional[BaseException], provider_name: Optional[str]) -> str:
    """Return a concise user-facing message for provider failures."""
    provider_label = provider_name or llm_manager.default_provider
    code = _classify_provider_error(err)
    if code == "llm_provider_quota":
        return (
            f"{provider_label} could not generate a response because the provider account "
            "appears to be out of credits or over its billing quota. Add credits or switch models, then retry."
        )
    if code == "llm_rate_limited":
        return f"{provider_label} is rate-limiting requests right now. Wait a moment or switch models, then retry."
    if code == "llm_config":
        return f"{provider_label} is not configured correctly. Check the API key for this provider."
    if code == "llm_unavailable":
        return f"{provider_label} is temporarily unavailable. Please retry in a few moments."
    if code == "llm_image_403":
        return "The screenshots needed for visual chat are no longer accessible. Re-index images and retry."
    return f"{provider_label} failed to generate a response. Please retry or switch models."


def _provider_http_status(err: Optional[BaseException]) -> int:
    """Choose an HTTP status that lets clients distinguish provider quota from server bugs."""
    code = _classify_provider_error(err)
    if code == "llm_provider_quota":
        return 402
    if code == "llm_rate_limited":
        return 429
    if code == "llm_config":
        return 400
    if code == "llm_unavailable":
        return 503
    return 502


def _stored_key_provider_name(provider_name: Optional[str]) -> Optional[str]:
    """Map chat provider ids to the provider ids used in user_api_keys."""
    if provider_name == "grok":
        return "xai"
    if provider_name in ("groq", "openai", "anthropic", "deepseek"):
        return provider_name
    return None


async def _get_saved_provider_key(user_id: Optional[str], provider_name: Optional[str]) -> Optional[str]:
    """Return a user's validated saved API key for a chat provider, if present."""
    key_provider = _stored_key_provider_name(provider_name)
    if not user_id or not key_provider:
        return None

    try:
        from services.supabase_service import SupabaseService
        from services.encryption import get_encryption_key, decrypt_api_key

        client = SupabaseService.get_client()
        response = (
            client.table("user_api_keys")
            .select("encrypted_key,is_valid")
            .eq("user_id", user_id)
            .eq("provider", key_provider)
            .limit(1)
            .execute()
        )

        if not response.data:
            return None

        row = response.data[0]
        if row.get("is_valid") is not True:
            return None

        encryption_key = await get_encryption_key()
        return decrypt_api_key(row["encrypted_key"], encryption_key)
    except Exception as e:
        print(f"[Chat] Could not load saved key for provider {provider_name}: {e}")
        return None


async def _get_chat_provider(request: Request, provider_name: Optional[str]):
    """Resolve an LLM provider, preferring a validated user-saved key over env keys."""
    user_id = None
    if hasattr(request.state, "profile") and request.state.profile:
        user_id = request.state.profile.get("id")
    if not user_id and hasattr(request.state, "user") and request.state.user:
        user_id = request.state.user.get("id")

    saved_key = await _get_saved_provider_key(user_id, provider_name)
    return llm_manager.get_provider(provider_name, api_key_override=saved_key)


async def _generate_visual_observations_with_fallback(
    request: Request,
    question: str,
    image_paths: List[str],
    visual_context: str,
    final_provider_name: Optional[str],
) -> str:
    """Use a real vision provider to turn screenshots into text for non-vision LLMs."""
    if not image_paths:
        return ""

    for candidate in ("grok", "openai", "anthropic"):
        if candidate == final_provider_name:
            continue
        try:
            vision_provider = await _get_chat_provider(request, candidate)
        except Exception as e:
            print(f"[Chat] Vision fallback provider {candidate} unavailable: {e}")
            continue

        if not vision_provider.supports_vision():
            continue

        messages = [
            {
                "role": "system",
                "content": (
                    "You inspect video screenshots and return concise factual observations. "
                    "Describe visible people, actions, setting, and anything relevant to the user's question. "
                    "Use the supplied screenshot/timestamp labels when referring to images. "
                    "Do not infer identities unless the metadata names a speaker/person."
                ),
            },
            {
                "role": "user",
                "content": (
                    "Question:\n"
                    f"{question}\n\n"
                    "Screenshot/timestamp metadata:\n"
                    f"{visual_context}\n\n"
                    "Return concise observations that a text-only model can use to answer the question."
                ),
            },
        ]

        try:
            print(f"[Chat] Using {candidate} as vision fallback for {len(image_paths)} images")
            observations = await vision_provider.generate_with_images(
                messages,
                image_paths,
                temperature=0.2,
                max_tokens=900,
            )
            observations = (observations or "").strip()
            if observations:
                return (
                    f"{visual_context}\n\n"
                    f"VISION MODEL OBSERVATIONS ({candidate}):\n{observations}"
                )
        except Exception as e:
            print(f"[Chat] Vision fallback provider {candidate} failed: {e}")

    return ""


def get_transcription_from_any_source(
    video_hash: str,
    refresh_screenshot_urls: bool = False,
) -> Optional[Dict]:
    """
    Get transcription from any available source:
    1. First check legacy database (SQLite/Firestore)
    2. If not found, check Supabase jobs table

    Args:
        video_hash: The video hash to look up

    Returns:
        Transcription data dict or None if not found
    """
    # Try legacy database first
    transcription = get_transcription(video_hash)
    if transcription:
        return transcription

    # Try Supabase jobs table
    try:
        from services.supabase_service import supabase
        client = supabase()

        # Look for completed job with this video_hash
        response = (
            client.table("jobs")
            .select("result_json, filename, gcs_path, user_id")
            .eq("video_hash", video_hash)
            .eq("status", "completed")
            .limit(1)
            .execute()
        )

        if response.data and len(response.data) > 0:
            job = response.data[0]
            result_json = job.get("result_json")

            if result_json:
                # The result_json from jobs already has the right structure
                # It contains: filename, gcs_path, video_hash, transcription (with segments)
                # Add user_id from job record for RLS compliance
                if job.get("user_id"):
                    result_json["user_id"] = job["user_id"]
                # Refresh only for callers that are about to return full
                # transcript segments. Chat retrieval does not need every
                # segment URL, and refreshing all of them can create hundreds
                # of IAM SignBlob calls per chat request.
                if refresh_screenshot_urls:
                    try:
                        from services.gcs_service import maybe_refresh_segment_urls
                        maybe_refresh_segment_urls(result_json)
                    except Exception as refresh_err:
                        print(f"[Chat] Screenshot URL refresh skipped: {refresh_err}")
                print(f"[Chat] Found transcription in Supabase job for video_hash={video_hash}")
                return result_json

    except Exception as e:
        print(f"[Chat] Error checking Supabase for transcription: {e}")

    return None


from models import (
    IndexVideoResponse,
    IndexImagesResponse,
    ChatRequest,
    ChatResponse,
    ComparisonSwapRequest,
    TestLLMRequest,
    TestLLMResponse,
    SearchImagesRequest,
    SearchImagesResponse,
    ImageSearchResult,
    ErrorResponse
)

# Import LLM and vector store modules
try:
    from llm_providers import llm_manager
    from vector_store import vector_store
    LLM_AVAILABLE = True
except ImportError as e:
    print(f"Warning: LLM features not available: {str(e)}")
    LLM_AVAILABLE = False

# Import Supabase image embedding service (new persistent storage)
try:
    from services.image_embedding_service import image_embedding_service
    SUPABASE_IMAGES_AVAILABLE = True
except Exception as e:
    print(f"Warning: Supabase image embeddings not available: {e}")
    SUPABASE_IMAGES_AVAILABLE = False

router = APIRouter(prefix="/api", tags=["Chat & RAG"])


@dataclass
class ComparisonIntent:
    person_name: Optional[str]
    unmatched_name: Optional[str] = None
    secondary_person_name: Optional[str] = None


def _use_supabase_for_images() -> bool:
    """
    Determine whether to use Supabase for image embeddings.
    Uses Supabase when:
    1. ENABLE_GCS_UPLOADS is true (production/Cloud Run)
    2. Supabase image service is available
    """
    from config import settings
    return SUPABASE_IMAGES_AVAILABLE and settings.ENABLE_GCS_UPLOADS


def _extract_speaker_from_query(query: str, video_hash: str) -> Optional[str]:
    """
    Extract speaker name from query by checking against enrolled speakers
    and segment speaker labels.

    Args:
        query: User's question/query
        video_hash: Video hash to get segments from

    Returns:
        Speaker name/label if found in query, None otherwise
    """
    speakers = _extract_all_speakers_from_query(query, video_hash)
    return speakers[0] if speakers else None


def _extract_all_speakers_from_query(query: str, video_hash: str) -> List[str]:
    """
    Extract ALL speaker names from query by checking against enrolled speakers
    and segment speaker labels.

    Args:
        query: User's question/query
        video_hash: Video hash to get segments from

    Returns:
        List of speaker names/labels found in query
    """
    if not query:
        return []

    query_lower = query.lower()
    found_speakers = []

    def add_if_mentioned(name: Optional[str], source: str) -> None:
        if not name:
            return
        if name.lower() in query_lower and not any(
            existing.lower() == name.lower() for existing in found_speakers
        ):
            print(f"Found {source} in query: {name}")
            found_speakers.append(name)

    # First, check enrolled speakers (e.g., "Alex", "John")
    try:
        from speaker_recognition import get_speaker_recognition_system
        sr_system = get_speaker_recognition_system()
        enrolled_speakers = sr_system.list_speakers()

        for speaker_name in enrolled_speakers:
            add_if_mentioned(speaker_name, "enrolled speaker")
    except Exception as e:
        print(f"Could not load speaker recognition system: {e}")

    # Check manually tagged face/person names. The frontend exposes these names
    # in @mention autocomplete, so chat retrieval must recognize them too.
    try:
        from services.supabase_service import supabase as get_supabase
        client = get_supabase()
        result = (
            client.table("face_tags")
            .select("speaker_name")
            .eq("video_hash", video_hash)
            .execute()
        )
        for row in result.data or []:
            add_if_mentioned(row.get("speaker_name"), "face-tagged speaker")
    except Exception as e:
        print(f"Could not check face-tagged speakers: {e}")

    # Also check for SPEAKER_XX labels in segments
    # This handles cases where segments use labels like "SPEAKER_19"
    try:
        transcription = get_transcription_from_any_source(video_hash)
        if transcription:
            segments = transcription.get('transcription', {}).get('segments', [])

            # Build a set of unique speaker labels
            speaker_labels = set()
            for segment in segments:
                speaker = segment.get('speaker')
                if speaker:
                    speaker_labels.add(speaker)

            # Check if any speaker label is mentioned in the query
            for speaker_label in speaker_labels:
                add_if_mentioned(speaker_label, "speaker label")
    except Exception as e:
        print(f"Could not check segment speakers: {e}")

    return found_speakers


def _load_face_tag_names(video_hash: str) -> list[str]:
    """Return unique manually tagged person names for a video."""
    try:
        from services.supabase_service import supabase as get_supabase

        client = get_supabase()
        result = (
            client.table("face_tags")
            .select("speaker_name")
            .eq("video_hash", video_hash)
            .execute()
        )
        names = []
        for row in result.data or []:
            name = (row.get("speaker_name") or "").strip()
            if name and not any(existing.lower() == name.lower() for existing in names):
                names.append(name)
        return names
    except Exception as e:
        print(f"Could not load face-tag names: {e}")
        return []


def _detect_comparison_intent(query: str, video_hash: str) -> Optional[ComparisonIntent]:
    """
    Detect person state comparison questions without stealing unrelated
    comparison queries from normal RAG.
    """
    if not query:
        return None

    cleaned = _clean_query_for_retrieval(query)
    query_lower = cleaned.lower()
    has_comparison_phrase = bool(re.search(
        r"\b(compare|compared|comparing|contrast|versus|vs\.?|different|change(?:d)?|before and after)\b",
        query_lower,
    )) or bool(re.search(r"\bhow\s+did\b.+\bchange\b", query_lower)) or bool(re.search(
        r"\b(?:start|beginning|early)\b.+\b(?:end|ending|late|after)\b",
        query_lower,
    )) or bool(re.search(
        r"\bbefore\b.+\b(?:after|during|then|later)\b",
        query_lower,
    ))
    if not has_comparison_phrase:
        return None

    known_names = _load_face_tag_names(video_hash)
    normalized_query = re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", query_lower.replace("'s", ""))).strip()
    matched_names: list[tuple[int, str]] = []
    for name in known_names:
        direct_match = re.search(rf"(?<!\w){re.escape(name.lower())}(?:'s)?(?!\w)", query_lower)
        if direct_match:
            matched_names.append((direct_match.start(), name))
            continue
        normalized_name = re.sub(
            r"\s+",
            " ",
            re.sub(r"[^\w\s]", " ", name.lower().replace("'s", "")),
        ).strip()
        normalized_index = f" {normalized_query} ".find(f" {normalized_name} ") if normalized_name else -1
        if normalized_index >= 0:
            matched_names.append((normalized_index, name))

    if matched_names:
        names_by_mention = [
            name for _, name in sorted(matched_names, key=lambda item: item[0])
        ]
        return ComparisonIntent(
            person_name=names_by_mention[0],
            secondary_person_name=names_by_mention[1] if len(names_by_mention) > 1 else None,
        )

    candidate_patterns = [
        r"\b(?:compare|compared|comparing|contrast)\s+([A-Z][\w'-]*(?:\s+(?:[A-Z][\w'-]*|mom|mother|dad|father|wife|husband|son|daughter)){0,3})\b",
        r"\bhow\s+(?:did|does)\s+([A-Z][\w'-]*(?:\s+(?:[A-Z][\w'-]*|mom|mother|dad|father|wife|husband|son|daughter)){0,3})\s+(?:change|start|begin)\b",
        r"\b([A-Z][\w'-]*(?:\s+(?:[A-Z][\w'-]*|mom|mother|dad|father|wife|husband|son|daughter)){0,3})\s+(?:early|beginning|before|start)\s+(?:vs\.?|versus|and|compared|towards?)\s+(?:late|end|after)\b",
    ]
    stop_targets = {"the", "this", "that", "with", "against", "between", "book", "version", "video", "movie", "scene"}
    for pattern in candidate_patterns:
        match = re.search(pattern, cleaned)
        if not match:
            continue
        candidate = re.sub(r"\s+", " ", match.group(1)).strip(" ?.,:;!\"'")
        if not candidate:
            continue
        first = candidate.split()[0].lower()
        if first in stop_targets:
            continue
        return ComparisonIntent(person_name=None, unmatched_name=candidate)

    return None


def _clean_query_for_retrieval(query: str) -> str:
    """Normalize UI mention syntax before embedding/search providers see it."""
    return (query or "").replace("@", " ").strip()


def _split_user_visual_lines(value: Optional[str]) -> list[str]:
    """Parse user-owned visual search settings from comma/newline text."""
    import re

    if not value:
        return []
    items = []
    for item in re.split(r"[\n,]+", value):
        item = re.sub(r"\s+", " ", item).strip().lower()
        if item and item not in items:
            items.append(item)
    return items


def _user_visual_search_config(profile: Optional[dict]) -> tuple[set[str], list[str]]:
    """Return private per-user visual search trigger terms and CLIP phrases."""
    terms = set(_split_user_visual_lines((profile or {}).get("visual_search_terms")))
    phrases = _split_user_visual_lines((profile or {}).get("visual_search_phrases"))
    return terms, phrases


def _query_matches_user_visual_terms(query: str, user_terms: set[str]) -> bool:
    """Return True when the query contains a user-configured visual trigger."""
    import re

    if not user_terms:
        return False
    cleaned = _clean_query_for_retrieval(query).lower()
    cleaned = re.sub(r"[^\w\s-]+", " ", cleaned)
    words = set(cleaned.split())
    return any(term in cleaned or term in words for term in user_terms)


def _resolve_contextual_visual_question(
    question: str,
    conversation_history: Optional[list],
    user_visual_terms: Optional[set[str]] = None,
    user_visual_phrases: Optional[list[str]] = None,
    video_hash: Optional[str] = None,
) -> str:
    """
    Expand short follow-up questions for retrieval.

    Users often ask "while doing it" or "that scene" after a previous visual
    question. CLIP/text retrieval needs the implied action repeated explicitly.
    """
    import re

    if not conversation_history:
        return question

    q = question or ""
    q_lower = q.lower()
    has_followup_reference = bool(re.search(
        r"\b(doing it|that|this|there|those|them|same scene|while doing)\b",
        q_lower,
    ))
    if not has_followup_reference:
        return question

    recent_user_text = " ".join(
        str(msg.get("content", ""))
        for msg in conversation_history[-6:]
        if msg.get("role") == "user"
    ).lower()

    additions = []
    user_visual_terms = user_visual_terms or set()
    user_visual_phrases = user_visual_phrases or []
    if _query_matches_user_visual_terms(recent_user_text, user_visual_terms):
        additions.extend(user_visual_phrases[:3])
    # If a recent message named a person tagged in this video but the current
    # question doesn't, anchor retrieval to them so follow-ups keep the subject.
    if video_hash:
        for name in _load_face_tag_names(video_hash):
            name_lower = name.lower()
            if re.search(rf"\b{re.escape(name_lower)}\b", recent_user_text) and name_lower not in q_lower:
                additions.append(f"involving {name_lower}")
                break

    if not additions:
        return question

    resolved = f"{question} {' '.join(additions)}"
    print(f"Resolved contextual visual question: '{question}' -> '{resolved}'")
    return resolved


def _visual_query_variants(
    query: str,
    user_visual_terms: Optional[set[str]] = None,
    user_visual_phrases: Optional[list[str]] = None,
) -> list[str]:
    """
    Build CLIP-friendly visual queries from chatty natural-language questions.

    CLIP image search is sensitive to filler words. A question like
    "is person swimming in this film?" can return fewer results than the
    shorter scene phrase "person swimming". For common movie-scene intents,
    add concrete visual phrases because CLIP performs better on descriptions
    of what appears in a frame than on conversational questions.
    """
    import re

    cleaned = _clean_query_for_retrieval(query).lower()
    cleaned = re.sub(r"[^\w\s-]+", " ", cleaned)
    cleaned = re.sub(r"\b(in|from|during|inside|within)\s+(this|the|a|an)?\s*(film|movie|video|scene|clip)\b", " ", cleaned)
    cleaned = re.sub(r"\b(this|the|a|an)\s+(film|movie|video|scene|clip)\b", " ", cleaned)

    stop_words = {
        "is", "are", "was", "were", "does", "do", "did", "can", "could",
        "would", "should", "show", "find", "search", "look", "see", "tell",
        "me", "about", "whether", "if", "there", "any", "images", "image",
        "screenshots", "screenshot", "picture", "pictures", "of", "in",
        "looks", "looking", "amazing", "beautiful", "hot",
    }
    tokens = [tok for tok in cleaned.split() if tok and tok not in stop_words]
    compact = " ".join(tokens)

    intent_phrases: list[str] = []
    user_visual_terms = user_visual_terms or set()
    user_visual_phrases = user_visual_phrases or []
    if _query_matches_user_visual_terms(cleaned, user_visual_terms):
        intent_phrases.extend(user_visual_phrases)

    variants = []
    for candidate in (*intent_phrases, compact, _clean_query_for_retrieval(query)):
        candidate = re.sub(r"\s+", " ", candidate).strip()
        if candidate and candidate.lower() not in {v.lower() for v in variants}:
            variants.append(candidate)
    if len(variants) > 1:
        print(f"Visual query variants for '{query}': {variants[:6]}")
    return variants


def _image_result_key(result: dict) -> str:
    url = result.get('screenshot_url') or result.get('screenshot_path', '')
    try:
        from services.gcs_service import gcs_service
        return gcs_service.extract_gcs_path_from_signed_url(url) or url.split("?", 1)[0]
    except Exception:
        return url.split("?", 1)[0]


def _format_segment_time(seconds: float) -> str:
    seconds = max(0, int(seconds or 0))
    return f"{seconds // 3600:02d}:{(seconds % 3600) // 60:02d}:{seconds % 60:02d}"


def _segment_text(segment: dict) -> str:
    """Return the transcript text used for chat context."""
    return (segment.get("translation") or segment.get("text") or "").strip()


def _segment_bounds(segment: dict) -> tuple[float, float, str, str]:
    start = float(segment.get("start", 0) or 0)
    end = float(segment.get("end", start) or start)
    return (
        start,
        end,
        segment.get("start_time") or _format_segment_time(start),
        segment.get("end_time") or _format_segment_time(end),
    )


def _segment_key(segment: dict) -> tuple[float, float, str]:
    start, end, _, _ = _segment_bounds(segment)
    return (round(start, 3), round(end, 3), _segment_text(segment)[:80])


def _segment_as_search_result(video_hash: str, segment: dict) -> dict:
    text = _segment_text(segment)
    start, end, start_time, end_time = _segment_bounds(segment)
    speaker = segment.get("speaker") or "SPEAKER_00"
    return {
        "text": text,
        "metadata": {
            "video_hash": video_hash,
            "start": start,
            "end": end,
            "start_time": start_time,
            "end_time": end_time,
            "speaker": speaker,
        },
        "distance": None,
    }


def _format_text_context(video_hash: str, search_results: list) -> tuple[str, list]:
    context_parts = []
    sources = []

    for result in search_results:
        metadata = result["metadata"]
        text = result["text"]
        context_parts.append(
            f"[Timestamp: {metadata['start_time']} - {metadata['end_time']}] "
            f"[Speaker: {metadata['speaker']}]\n{text}"
        )
        sources.append({
            "start_time": metadata["start_time"],
            "end_time": metadata["end_time"],
            "start": metadata["start"],
            "end": metadata["end"],
            "speaker": metadata["speaker"],
            "text": text[:200] + "..." if len(text) > 200 else text,
        })

    return "\n\n".join(context_parts), sources


def _expand_text_hits_with_neighbors(
    video_hash: str,
    search_results: list,
    segments: list,
    neighbor_count: int = 1,
    max_results: int = 24,
) -> list:
    """
    Add nearby transcript segments around vector hits.

    Vector hits are indexed as small chunks. For movie/chat questions the
    surrounding line or two often carries the setup, referent, or resolution,
    so we include adjacent transcript segments before prompting the LLM.
    """
    if not search_results or not segments:
        return search_results

    selected_indexes: set[int] = set()

    for result in search_results:
        metadata = result.get("metadata") or {}
        hit_start = float(metadata.get("start", 0) or 0)
        hit_end = float(metadata.get("end", hit_start) or hit_start)

        overlapping = []
        for idx, segment in enumerate(segments):
            text = _segment_text(segment)
            if not text:
                continue
            seg_start, seg_end, _, _ = _segment_bounds(segment)
            if seg_start <= hit_end and seg_end >= hit_start:
                overlapping.append(idx)

        if not overlapping:
            continue

        start_idx = max(0, min(overlapping) - neighbor_count)
        end_idx = min(len(segments) - 1, max(overlapping) + neighbor_count)
        selected_indexes.update(range(start_idx, end_idx + 1))

    expanded = []
    seen = set()
    for idx in sorted(selected_indexes):
        segment = segments[idx]
        text = _segment_text(segment)
        if not text:
            continue
        key = _segment_key(segment)
        if key in seen:
            continue
        seen.add(key)
        expanded.append(_segment_as_search_result(video_hash, segment))
        if len(expanded) >= max_results:
            break

    return expanded or search_results


def _lexical_segment_matches(
    video_hash: str,
    question: str,
    segments: list,
    limit: int,
) -> list:
    """Find transcript segments with exact query term/phrase overlap."""
    import re

    query = _clean_query_for_retrieval(question).lower()
    if not query or not segments:
        return []

    quoted_phrases = []
    for double_quoted, single_quoted in re.findall(r'"([^"]+)"|\'([^\']+)\'', query):
        phrase = (double_quoted or single_quoted).strip().lower()
        if phrase:
            quoted_phrases.append(phrase)
    stop_words = {
        "a", "an", "and", "are", "about", "at", "can", "could", "did", "do",
        "does", "for", "from", "happen", "happened", "how", "i", "in", "is",
        "it", "me", "movie", "of", "on", "or", "scene", "show", "tell",
        "the", "this", "to", "video", "was", "what", "when", "where", "who",
        "why", "with", "would",
    }
    tokens = [
        token
        for token in re.findall(r"[a-z0-9_'-]+", query)
        if len(token) > 2 and token not in stop_words
    ]
    if not tokens and not quoted_phrases:
        return []

    scored: list[tuple[int, int, dict]] = []
    for idx, segment in enumerate(segments):
        text = _segment_text(segment)
        if not text:
            continue
        haystack = f"{segment.get('speaker', '')} {text}".lower()
        haystack_tokens = set(re.findall(r"[a-z0-9_'-]+", haystack))
        score = 0

        for phrase in quoted_phrases:
            if phrase in haystack:
                score += 8 + len(phrase.split())

        token_hits = len(set(tokens) & haystack_tokens)
        score += token_hits

        if score > 0:
            scored.append((score, idx, segment))

    if not scored:
        return []

    scored.sort(key=lambda item: (-item[0], item[1]))
    selected_indexes: set[int] = set()
    for _, idx, _ in scored[:limit]:
        selected_indexes.update(range(max(0, idx - 1), min(len(segments), idx + 2)))

    results = []
    seen = set()
    for idx in sorted(selected_indexes):
        segment = segments[idx]
        text = _segment_text(segment)
        if not text:
            continue
        key = _segment_key(segment)
        if key in seen:
            continue
        seen.add(key)
        results.append(_segment_as_search_result(video_hash, segment))
        if len(results) >= max(limit * 3, limit):
            break

    print(f"Lexical transcript matches: {len(results)} context segments")
    return results


def _merge_text_results(primary: list, supplemental: list, max_results: int) -> list:
    merged = []
    seen = set()

    for result in primary + supplemental:
        metadata = result.get("metadata") or {}
        key = (
            round(float(metadata.get("start", 0) or 0), 3),
            round(float(metadata.get("end", 0) or 0), 3),
            (result.get("text") or "")[:80],
        )
        if key in seen:
            continue
        seen.add(key)
        merged.append(result)
        if len(merged) >= max_results:
            break

    return merged


def _speaker_segment_context(video_hash: str, question: str, limit: int) -> tuple[list, str, list]:
    """
    Build deterministic transcript context for speaker/person mention queries.

    Semantic search can miss short mention-only prompts like "tell me about
    @alex". When the query names a known transcript speaker, use that
    speaker's segments directly instead of returning no context.
    """
    speaker_names = _extract_all_speakers_from_query(question, video_hash)
    if not speaker_names:
        return [], "", []

    transcription = get_transcription_from_any_source(video_hash)
    if not transcription:
        return [], "", []

    segments = transcription.get("transcription", {}).get("segments", [])
    speaker_lowers = {name.lower() for name in speaker_names}
    matching_segments = [
        seg for seg in segments
        if (seg.get("speaker") or "").lower() in speaker_lowers
    ]
    if not matching_segments:
        return [], "", []

    selected = matching_segments[:max(1, limit)]
    context_parts = []
    sources = []
    search_results = []

    for seg in selected:
        text = (seg.get("translation") or seg.get("text") or "").strip()
        if not text:
            continue
        start = float(seg.get("start", 0) or 0)
        end = float(seg.get("end", start) or start)
        start_time = seg.get("start_time") or _format_segment_time(start)
        end_time = seg.get("end_time") or _format_segment_time(end)
        speaker = seg.get("speaker") or speaker_names[0]
        metadata = {
            "video_hash": video_hash,
            "start": start,
            "end": end,
            "start_time": start_time,
            "end_time": end_time,
            "speaker": speaker,
        }
        search_results.append({"text": text, "metadata": metadata, "distance": None})
        context_parts.append(
            f"[Timestamp: {start_time} - {end_time}] "
            f"[Speaker: {speaker}]\n{text}"
        )
        sources.append({
            "start_time": start_time,
            "end_time": end_time,
            "start": start,
            "end": end,
            "speaker": speaker,
            "text": text[:200] + "..." if len(text) > 200 else text,
        })

    if not search_results:
        return [], "", []

    print(
        f"Speaker fallback context: {len(search_results)} segments for "
        f"{', '.join(speaker_names)}"
    )
    return search_results, "\n\n".join(context_parts), sources


def _timestamp_from_screenshot_url(url: str) -> float:
    """Extract screenshot timestamp from .../<seconds>.jpg URLs."""
    try:
        import os
        path = url.split("?", 1)[0]
        filename = os.path.basename(path)
        stem = filename.rsplit(".", 1)[0]
        return float(stem)
    except Exception:
        return 0.0


def _fresh_screenshot_url(url: str) -> str:
    """Return a fresh signed URL when the input is a GCS signed URL."""
    try:
        from services.gcs_service import gcs_service
        from config import settings as _settings
        if not _settings.ENABLE_GCS_UPLOADS:
            return url
        gcs_path = gcs_service.extract_gcs_path_from_signed_url(url)
        if not gcs_path:
            return url
        return gcs_service.generate_download_signed_url(
            gcs_path,
            expiry_seconds=_settings.GCS_SCREENSHOT_URL_EXPIRY,
        )
    except Exception as e:
        print(f"[Chat] Face-tag screenshot URL refresh skipped: {e}")
        return url


async def _face_tag_image_results(
    video_hash: str,
    speaker_names: list[str],
    limit: int,
) -> list[dict]:
    """Use manually tagged faces as visual candidates for named-person queries."""
    if not speaker_names:
        return []

    try:
        from services.supabase_service import supabase as get_supabase
        face_client = get_supabase()
        rows = []
        for speaker_name in speaker_names:
            response = (
                face_client.table("face_tags")
                .select("speaker_name, screenshot_url")
                .eq("video_hash", video_hash)
                .eq("speaker_name", speaker_name)
                .limit(max(limit * 2, limit))
                .execute()
            )
            for row in response.data or []:
                rows.append(row)

        results = []
        seen_paths = set()
        for row in rows:
            screenshot_url = row.get("screenshot_url")
            if not screenshot_url:
                continue
            try:
                from services.gcs_service import gcs_service
                dedupe_key = gcs_service.extract_gcs_path_from_signed_url(screenshot_url) or screenshot_url.split("?", 1)[0]
            except Exception:
                dedupe_key = screenshot_url.split("?", 1)[0]
            if dedupe_key in seen_paths:
                continue
            seen_paths.add(dedupe_key)

            start = _timestamp_from_screenshot_url(screenshot_url)
            results.append({
                "screenshot_url": _fresh_screenshot_url(screenshot_url),
                "metadata": {
                    "video_hash": video_hash,
                    "segment_id": f"face_tag_{len(results)}",
                    "start": start,
                    "end": start + 1.0,
                    "speaker": row.get("speaker_name") or speaker_names[0],
                },
                # A manual face tag is strong identity evidence, but it is
                # not evidence that the frame matches the requested action or
                # object. Keep it below CLIP scene matches so named-person
                # action queries do not get flooded by face-only examples.
                "similarity": 0.25,
                "face_score": 1.0,
                "overlap_score": 0,
                "likely_speakers": [row.get("speaker_name") or speaker_names[0]],
                "source": "face_tag",
            })
            if len(results) >= limit:
                break

        if results:
            print(
                f"Face-tag visual candidates: {len(results)} screenshots for "
                f"{', '.join(speaker_names)}"
            )
        return results
    except Exception as e:
        print(f"Face-tag visual candidate lookup failed (non-critical): {e}")
        return []


def _load_speaker_reference_embedding(video_hash: str, speaker_name: str) -> Optional[list[float]]:
    """Load the normalized average manual face-tag embedding for one person."""
    try:
        import numpy as np
        import json as _json
        from services.supabase_service import supabase as get_supabase

        face_client = get_supabase()
        face_result = face_client.table("face_tags").select(
            "embedding"
        ).eq("video_hash", video_hash).eq(
            "speaker_name", speaker_name
        ).execute()
        if not face_result.data:
            return None

        raw_embeddings = []
        for row in face_result.data:
            emb = row.get("embedding")
            if not emb:
                continue
            if isinstance(emb, str):
                emb = _json.loads(emb)
            raw_embeddings.append(emb)
        if not raw_embeddings:
            return None

        embeddings = [np.array(e, dtype=np.float32) for e in raw_embeddings]
        avg_emb = np.mean(embeddings, axis=0)
        norm = np.linalg.norm(avg_emb)
        if norm > 0:
            avg_emb = avg_emb / norm
        print(f"  Face tags for '{speaker_name}': {len(embeddings)} embeddings loaded")
        return avg_emb.tolist()
    except Exception as e:
        print(f"  Face tags lookup failed (non-critical): {e}")
        return None


def _load_speaker_face_embeddings(video_hash: str, speaker_names: list[str]) -> dict[str, list[float]]:
    """Load averaged manual face-tag embeddings for named speakers."""
    speaker_face_embeddings: dict[str, list[float]] = {}
    if not speaker_names:
        return speaker_face_embeddings

    for name in speaker_names:
        embedding = _load_speaker_reference_embedding(video_hash, name)
        if embedding:
            speaker_face_embeddings[name] = embedding

    return speaker_face_embeddings


async def _load_face_presence(
    video_hash: str,
    speaker_face_embeddings: dict[str, list[float]],
) -> tuple[dict[str, dict[str, float]], dict[str, list[tuple[float, float]]]]:
    """
    Load pre-indexed face-presence matches for named speakers.

    Returns:
      - face_presence_by_image: image_embedding_id -> speaker_name -> similarity
      - presence_timelines: speaker_name -> [(start, end), ...]
    """
    face_presence_by_image: dict[str, dict[str, float]] = {}
    presence_timelines: dict[str, list[tuple[float, float]]] = {
        speaker: [] for speaker in speaker_face_embeddings
    }
    if not speaker_face_embeddings:
        return face_presence_by_image, presence_timelines

    try:
        from config import settings
        from services.supabase_service import supabase as get_supabase

        face_client = get_supabase()
        for speaker, embedding in speaker_face_embeddings.items():
            response = await _run_in_executor(
                lambda emb=embedding: face_client.rpc(
                    "match_faces_by_embedding",
                    {
                        "target_video_hash": video_hash,
                        "query_embedding": emb,
                        "similarity_threshold": settings.FACE_PRESENCE_SIMILARITY_THRESHOLD,
                    },
                ).execute()
            )
            for row in response.data or []:
                image_id = str(row.get("image_embedding_id") or "")
                if not image_id:
                    continue
                similarity = float(row.get("similarity") or 0.0)
                face_presence_by_image.setdefault(image_id, {})[speaker] = max(
                    similarity,
                    face_presence_by_image.get(image_id, {}).get(speaker, 0.0),
                )
                presence_timelines.setdefault(speaker, []).append((
                    float(row.get("start_time") or 0.0),
                    float(row.get("end_time") or 0.0),
                ))
    except Exception as e:
        print(f"  Face presence lookup failed (non-critical): {e}")
        return {}, {speaker: [] for speaker in speaker_face_embeddings}

    for speaker, timeline in presence_timelines.items():
        if timeline:
            print(f"  Face presence for '{speaker}': {len(timeline)} matched screenshots")

    return face_presence_by_image, presence_timelines


def _parse_vector(value: Any) -> Optional[list[float]]:
    """Parse pgvector/list values returned by Supabase into a float list."""
    if value is None:
        return None
    if isinstance(value, list):
        return [float(v) for v in value]
    if isinstance(value, str):
        text = value.strip()
        if text.startswith("[") and text.endswith("]"):
            return [float(v) for v in text.strip("[]").split(",") if v.strip()]
        try:
            parsed = json.loads(text)
            if isinstance(parsed, list):
                return [float(v) for v in parsed]
        except Exception:
            return None
    return None


def _cosine_similarity(a: Any, b: Any) -> float:
    import numpy as np

    va = np.array(a, dtype=np.float32)
    vb = np.array(b, dtype=np.float32)
    denom = float(np.linalg.norm(va) * np.linalg.norm(vb))
    if denom <= 0:
        return 0.0
    return float(np.dot(va, vb) / denom)


def _video_duration_seconds(video_hash: str, appearances: list[dict]) -> float:
    transcription = get_transcription_from_any_source(video_hash)
    segments = (transcription or {}).get("transcription", {}).get("segments", [])
    duration = 0.0
    for segment in segments:
        try:
            duration = max(duration, float(segment.get("end") or segment.get("start") or 0))
        except Exception:
            continue
    for appearance in appearances:
        duration = max(duration, float(appearance.get("end_time") or appearance.get("start_time") or 0))
    return max(duration, 1.0)


def _chunks(values: list[Any], size: int) -> list[list[Any]]:
    return [values[i:i + size] for i in range(0, len(values), size)]


async def _load_comparison_presence_rows(client, video_hash: str, image_ids: list[str]) -> tuple[list[dict], list[dict]]:
    """
    Load face/image rows for comparison matches in small batches.
    Keep batches small: each face row carries a large embedding, and Supabase/Cloudflare
    can reject or terminate larger PostgREST responses.
    """
    face_rows: list[dict] = []
    image_rows: list[dict] = []
    for batch in _chunks(image_ids, 8):
        try:
            image_response = await _run_in_executor(
                lambda ids=batch: client.table("image_embeddings")
                .select("id,start_time,end_time,speaker,screenshot_url,embedding")
                .eq("video_hash", video_hash)
                .in_("id", ids)
                .execute()
            )
            image_rows.extend(image_response.data or [])
        except Exception as e:
            print(f"[Chat] Face comparison image batch skipped ({len(batch)} ids): {e}")
            continue

        try:
            face_response = await _run_in_executor(
                lambda ids=batch: client.table("image_face_presence")
                .select("image_embedding_id,face_embedding,bbox,start_time,end_time")
                .eq("video_hash", video_hash)
                .in_("image_embedding_id", ids)
                .execute()
            )
            face_rows.extend(face_response.data or [])
        except Exception as e:
            print(f"[Chat] Face comparison face batch skipped ({len(batch)} ids): {e}")
    return face_rows, image_rows


async def _load_person_appearances(
    video_hash: str,
    person_name: str,
    *,
    threshold: Optional[float] = None,
) -> list[dict]:
    """Find indexed face appearances for a manually tagged person.

    `threshold` gates which faces qualify (cosine similarity). Defaults to the
    relaxed comparison threshold so faint faces (dim/profile/distant scenes)
    still surface; pass an explicit value to override.
    """
    from config import settings
    from services.supabase_service import supabase as get_supabase

    if threshold is None:
        threshold = settings.FACE_PRESENCE_COMPARISON_THRESHOLD

    reference_embedding = _load_speaker_reference_embedding(video_hash, person_name)
    if not reference_embedding:
        return []

    client = get_supabase()
    response = await _run_in_executor(
        lambda: client.rpc(
            "match_faces_by_embedding",
            {
                "target_video_hash": video_hash,
                "query_embedding": reference_embedding,
                "similarity_threshold": threshold,
                "match_limit": 500,
            },
        ).execute()
    )
    matches = response.data or []
    image_ids = list(dict.fromkeys(
        str(row.get("image_embedding_id"))
        for row in matches
        if row.get("image_embedding_id")
    ))
    if not image_ids:
        return []

    try:
        face_rows, image_rows = await _load_comparison_presence_rows(
            client,
            video_hash,
            image_ids,
        )
    except Exception as e:
        print(
            f"[Chat] Face comparison presence row lookup failed for "
            f"'{person_name}' ({len(image_ids)} ids): {e}"
        )
        return []

    match_similarity = {
        str(row.get("image_embedding_id")): float(row.get("similarity") or 0.0)
        for row in matches
    }
    images_by_id = {
        str(row.get("id")): row
        for row in image_rows
        if row.get("id")
    }

    best_faces: dict[str, dict] = {}
    for row in face_rows:
        image_id = str(row.get("image_embedding_id") or "")
        face_embedding = _parse_vector(row.get("face_embedding"))
        if not image_id:
            continue
        similarity = (
            _cosine_similarity(reference_embedding, face_embedding)
            if face_embedding
            else match_similarity.get(image_id, 0.0)
        )
        if similarity < threshold:
            continue
        current = best_faces.get(image_id)
        if current is None or similarity > current["similarity"]:
            best_faces[image_id] = {
                "face_embedding": face_embedding,
                "bbox": row.get("bbox"),
                "similarity": similarity,
                "start_time": float(row.get("start_time") or 0.0),
                "end_time": float(row.get("end_time") or row.get("start_time") or 0.0),
            }

    appearances = []
    for image_id, face in best_faces.items():
        image = images_by_id.get(image_id)
        if not image:
            continue
        scene_embedding = _parse_vector(image.get("embedding"))
        screenshot_url = image.get("screenshot_url")
        if not screenshot_url:
            continue
        start = float(image.get("start_time") or face["start_time"])
        end = float(image.get("end_time") or face["end_time"] or start)
        similarity = max(face["similarity"], match_similarity.get(image_id, 0.0))
        appearances.append({
            "image_embedding_id": image_id,
            "start_time": start,
            "end_time": end,
            "speaker": image.get("speaker") or person_name,
            "screenshot_url": _fresh_screenshot_url(screenshot_url),
            "bbox": face.get("bbox"),
            "face_embedding": face["face_embedding"],
            "scene_embedding": scene_embedding,
            "similarity": similarity,
            # Faint match: surfaced only because of the relaxed comparison
            # threshold. Below the global 0.5 confidence bar -> badge in the UI.
            "low_confidence": similarity < settings.FACE_PRESENCE_SIMILARITY_THRESHOLD,
        })

    appearances.sort(key=lambda row: row.get("similarity", 0.0), reverse=True)

    # Guardrail: keep all confident frames (>= global threshold) plus at most the
    # top N faint frames, so relaxing the gate widens the pool without flooding
    # the timeline strip with low-similarity noise.
    confident = [a for a in appearances if not a.get("low_confidence")]
    faint = [a for a in appearances if a.get("low_confidence")]
    FAINT_FRAME_CAP = 15
    appearances = confident + faint[:FAINT_FRAME_CAP]

    if len(appearances) < 2:
        print(
            f"[Chat] Face comparison presence matches for '{person_name}' yielded "
            f"{len(appearances)} usable appearances; falling back to manual face tags"
        )
        appearances = _merge_comparison_appearances(
            appearances,
            _load_face_tag_appearances(video_hash, person_name, reference_embedding),
        )
    return appearances


async def _load_person_appearances_with_fallback(video_hash: str, person_name: str) -> list[dict]:
    """Load automatic face-presence appearances, then merge manual tags as a fallback."""
    appearances = await _load_person_appearances(video_hash, person_name)
    reference_embedding = _load_speaker_reference_embedding(video_hash, person_name)
    tagged_appearances = (
        _load_face_tag_appearances(video_hash, person_name, reference_embedding)
        if reference_embedding
        else []
    )
    return _merge_comparison_appearances(appearances, tagged_appearances)


def _comparison_appearance_key(appearance: dict) -> str:
    url = appearance.get("screenshot_url") or ""
    try:
        from services.gcs_service import gcs_service
        return gcs_service.extract_gcs_path_from_signed_url(url) or url.split("?", 1)[0]
    except Exception:
        return url.split("?", 1)[0]


def _merge_comparison_appearances(primary: list[dict], fallback: list[dict]) -> list[dict]:
    merged = []
    seen = set()
    for appearance in [*primary, *fallback]:
        key = _comparison_appearance_key(appearance)
        if not key or key in seen:
            continue
        seen.add(key)
        merged.append(appearance)
    merged.sort(key=lambda row: row.get("similarity", 0.0), reverse=True)
    return merged


def _load_face_tag_appearances(
    video_hash: str,
    person_name: str,
    reference_embedding: Optional[list[float]],
) -> list[dict]:
    """Fallback appearances from manually tagged screenshots."""
    try:
        from services.supabase_service import supabase as get_supabase

        client = get_supabase()
        result = (
            client.table("face_tags")
            .select("screenshot_url,bbox_x,bbox_y,bbox_w,bbox_h,embedding")
            .eq("video_hash", video_hash)
            .eq("speaker_name", person_name)
            .execute()
        )
        appearances = []
        for idx, row in enumerate(result.data or []):
            screenshot_url = row.get("screenshot_url")
            if not screenshot_url:
                continue
            face_embedding = _parse_vector(row.get("embedding"))
            start = _timestamp_from_screenshot_url(screenshot_url)
            bbox = None
            if all(row.get(key) is not None for key in ("bbox_x", "bbox_y", "bbox_w", "bbox_h")):
                bbox = {
                    "x": float(row.get("bbox_x")),
                    "y": float(row.get("bbox_y")),
                    "w": float(row.get("bbox_w")),
                    "h": float(row.get("bbox_h")),
                }
            appearances.append({
                "image_embedding_id": f"face_tag_{idx}",
                "start_time": start,
                "end_time": start + 1.0,
                "speaker": person_name,
                "screenshot_url": _fresh_screenshot_url(screenshot_url),
                "bbox": bbox,
                "face_embedding": face_embedding,
                "scene_embedding": None,
                "similarity": (
                    _cosine_similarity(reference_embedding, face_embedding)
                    if reference_embedding and face_embedding
                    else 1.0
                ),
            })
        appearances.sort(key=lambda row: row.get("similarity", 0.0), reverse=True)
        return appearances
    except Exception as e:
        print(f"[Chat] Face-tag comparison fallback failed: {e}")
        return []


def _comparison_query_mode(query: str) -> str:
    """Return how strongly the user's wording should steer pair selection."""
    query_lower = (query or "").lower()
    has_early = bool(re.search(r"\b(start|starts|begin|beginning|early|opening|first)\b", query_lower))
    has_late = bool(re.search(r"\b(end|ends|ending|late|later|final|towards?\s+the\s+end|after)\b", query_lower))
    if has_early and has_late:
        return "early_late"
    if bool(re.search(r"\b(before\s+and\s+after|before.+(?:after|during|then|later)|compared|change(?:d)?)\b", query_lower)):
        return "temporal"
    return "contrast"


def _state_pair_score(first: dict, second: dict, video_duration: float, mode: str) -> float:
    face_a = first.get("face_embedding")
    face_b = second.get("face_embedding")
    scene_a = first.get("scene_embedding")
    scene_b = second.get("scene_embedding")
    d_face = 1.0 - _cosine_similarity(face_a, face_b) if face_a and face_b else 0.0
    d_scene = 1.0 - _cosine_similarity(scene_a, scene_b) if scene_a and scene_b else 0.0
    d_time = min(
        1.0,
        abs(float(first.get("start_time") or 0.0) - float(second.get("start_time") or 0.0)) / max(video_duration, 1.0),
    )
    avg_identity = (
        float(first.get("similarity") or 0.0) + float(second.get("similarity") or 0.0)
    ) / 2.0

    if mode == "early_late":
        return 0.42 * d_face + 0.28 * d_scene + 0.25 * d_time + 0.05 * avg_identity
    if mode == "temporal":
        return 0.40 * d_face + 0.25 * d_scene + 0.30 * d_time + 0.05 * avg_identity
    # Weights emphasize visible person-state change, then context, with time as a tie-breaker toward early/late moments.
    return 0.50 * d_face + 0.30 * d_scene + 0.15 * d_time + 0.05 * avg_identity


def _select_best_state_pair(
    candidates: list[dict],
    video_duration: float,
    mode: str,
) -> Optional[tuple[dict, dict]]:
    best_pair = None
    best_score = -1.0
    for i, first in enumerate(candidates):
        for second in candidates[i + 1:]:
            score = _state_pair_score(first, second, video_duration, mode)
            if score > best_score:
                best_score = score
                best_pair = (first, second)

    if not best_pair:
        return None
    return tuple(sorted(best_pair, key=lambda row: float(row.get("start_time") or 0.0)))


def _select_cross_state_pair(
    first_group: list[dict],
    second_group: list[dict],
    video_duration: float,
    mode: str,
) -> Optional[tuple[dict, dict]]:
    best_pair = None
    best_score = -1.0
    for first in first_group:
        for second in second_group:
            if first is second:
                continue
            score = _state_pair_score(first, second, video_duration, mode)
            if score > best_score:
                best_score = score
                best_pair = (first, second)

    if not best_pair:
        return None
    return tuple(sorted(best_pair, key=lambda row: float(row.get("start_time") or 0.0)))


def _select_boundary_state_pair(
    appearances: list[dict],
    video_duration: float,
) -> Optional[tuple[dict, dict]]:
    """For explicit beginning/end wording, use earliest/latest reliable appearances."""
    reliable = sorted(
        appearances,
        key=lambda row: row.get("similarity", 0.0),
        reverse=True,
    )[:200]
    by_time = sorted(reliable, key=lambda row: float(row.get("start_time") or 0.0))
    if len(by_time) < 2:
        return None

    earliest_time = float(by_time[0].get("start_time") or 0.0)
    latest_time = float(by_time[-1].get("start_time") or 0.0)
    boundary_window = max(180.0, video_duration * 0.05)
    early = [
        row for row in by_time
        if float(row.get("start_time") or 0.0) <= earliest_time + boundary_window
    ]
    late = [
        row for row in by_time
        if float(row.get("start_time") or 0.0) >= latest_time - boundary_window
    ]
    if not early or not late:
        group_size = min(12, max(2, len(by_time) // 5))
        early = by_time[:group_size]
        late = by_time[-group_size:]

    first = max(early, key=lambda row: row.get("similarity", 0.0))
    second = max(late, key=lambda row: row.get("similarity", 0.0))
    if first is second:
        return None
    print(
        "[Chat] Face comparison selected boundary state pair "
        f"early={float(first.get('start_time') or 0.0):.2f}s "
        f"late={float(second.get('start_time') or 0.0):.2f}s"
    )
    return tuple(sorted((first, second), key=lambda row: float(row.get("start_time") or 0.0)))


# Words that mean "a moment in time" rather than a visible state — these belong
# to the early/late path, not query-aware visual matching.
_TEMPORAL_PHRASE_WORDS = {
    "start", "starts", "beginning", "begin", "early", "earlier", "opening",
    "first", "end", "ends", "ending", "late", "later", "latest", "final",
    "finally", "before", "after", "then", "during", "now", "younger", "older",
}
# Filler/structural words to drop when isolating the descriptive state phrase.
_STATE_PHRASE_STOPWORDS = {
    "the", "a", "an", "her", "his", "their", "him", "she", "he", "them", "it",
    "is", "was", "are", "were", "being", "been", "get", "gets", "got",
    "looks", "look", "looking", "appears", "appear", "appearing",
    "scene", "scenes", "version", "shot", "frame", "frames", "moment", "part",
    "state", "states", "when", "where", "while", "with", "and", "of", "in",
    "on", "at", "to", "compare", "compared", "comparing", "contrast",
    "contrasted", "show", "see", "versus", "vs", "person",
}


def _extract_state_phrases(
    query: str,
    person_names: Optional[list[str]] = None,
) -> Optional[tuple[str, str]]:
    """Pull two contrasting *visual-state* phrases from a comparison query.

    'compare <person> calm vs angry' -> ('calm', 'angry'). Returns None for
    temporal wording (beginning/end) or when no clear visual pair is present, so
    those queries fall through to the existing early/late + difference logic.
    """
    if not query:
        return None
    q = " " + query.lower().replace("'s", " ") + " "
    for name in (person_names or []):
        if name:
            q = re.sub(rf"\b{re.escape(name.lower())}\b", " ", q)

    m = re.search(r"(.+?)\b(?:versus|vs\.?|compared to|against|or|rather than)\b(.+)", q)
    if not m:
        return None

    def _side(text: str, take_last: bool) -> str:
        words = [w for w in re.findall(r"[a-z]+", text) if w not in _STATE_PHRASE_STOPWORDS]
        if not words:
            return ""
        words = words[-2:] if take_last else words[:2]
        return " ".join(words)

    left = _side(m.group(1), take_last=True)
    right = _side(m.group(2), take_last=False)
    if not left or not right or left == right:
        return None
    if (set(left.split()) | set(right.split())) & _TEMPORAL_PHRASE_WORDS:
        return None
    return (left, right)


_CLIP_PROMPT_TEMPLATES = ("{p}", "a photo of a person {p}", "a {p} person")


def _clip_text_embeddings(phrases: list[str]) -> Optional[list[list]]:
    """One averaged CLIP text embedding per phrase, all encoded in a single batch.

    Averages a few prompt templates — absolute CLIP text/image cosine is low and
    noisy, so the ensemble + contrast scoring (see caller) is what gives signal.
    """
    try:
        import numpy as np
        from services.image_embedding_service import image_embedding_service
        n = len(_CLIP_PROMPT_TEMPLATES)
        prompts = [t.format(p=p) for p in phrases for t in _CLIP_PROMPT_TEMPLATES]
        vecs = np.asarray(
            image_embedding_service.clip_model.encode(prompts, convert_to_numpy=True),
            dtype=np.float32,
        )
        return [vecs[i * n:(i + 1) * n].mean(axis=0).tolist() for i in range(len(phrases))]
    except Exception as e:
        print(f"[Chat] CLIP text embedding failed for {phrases}: {e}")
        return None


def _select_query_aware_state_pair(
    appearances: list[dict],
    phrase_a: str,
    phrase_b: str,
) -> Optional[tuple[dict, dict]]:
    """Pick endpoints by how well each frame's scene matches the user's two state
    phrases. Returns (A, B) in PHRASE order: A = most phrase_a, B = most phrase_b.

    Uses *contrast* scoring (sim_b - sim_a) rather than absolute similarity:
    CLIP text/image cosine is flat in absolute terms (~0.25 for everything), but
    the difference between the two phrases separates frames reliably (validated:
    'clothed vs nude' correctly lands B on the nude scene).
    """
    candidates = [a for a in appearances if a.get("scene_embedding")]
    if len(candidates) < 2:
        return None
    texts = _clip_text_embeddings([phrase_a, phrase_b])
    if not texts:
        return None
    text_a, text_b = texts

    scored = [
        (
            a,
            _cosine_similarity(text_b, a.get("scene_embedding"))
            - _cosine_similarity(text_a, a.get("scene_embedding")),
        )
        for a in candidates
    ]
    frame_b = max(scored, key=lambda s: s[1])[0]  # most phrase_b vs phrase_a
    frame_a = min(scored, key=lambda s: s[1])[0]  # most phrase_a vs phrase_b
    if frame_a is frame_b:
        return None
    print(
        f"[Chat] Face comparison used query-aware pair: A~'{phrase_a}' "
        f"@{float(frame_a.get('start_time') or 0.0):.1f}s, B~'{phrase_b}' "
        f"@{float(frame_b.get('start_time') or 0.0):.1f}s"
    )
    return (frame_a, frame_b)


def _select_state_pair(
    appearances: list[dict],
    video_duration: float,
    query: str = "",
    person_names: Optional[list[str]] = None,
) -> Optional[tuple[dict, dict]]:
    """Select two appearances, using comparison wording to steer temporal vs contrast emphasis."""
    if len(appearances) < 2:
        return None

    # Query-aware: if the user named two visible states ("clothed vs nude"),
    # pick the frames that best match each phrase rather than generic difference.
    phrases = _extract_state_phrases(query, person_names)
    if phrases:
        pair = _select_query_aware_state_pair(appearances, phrases[0], phrases[1])
        if pair:
            return pair

    mode = _comparison_query_mode(query)
    candidates = sorted(
        appearances,
        key=lambda row: row.get("similarity", 0.0),
        reverse=True,
    )[:80 if mode in ("early_late", "temporal") else 30]

    if mode == "early_late":
        pair = _select_boundary_state_pair(appearances, video_duration)
        if pair:
            return pair

        early_cutoff = video_duration * 0.35
        late_cutoff = video_duration * 0.65
        early = [row for row in candidates if float(row.get("start_time") or 0.0) <= early_cutoff]
        late = [row for row in candidates if float(row.get("start_time") or 0.0) >= late_cutoff]
        if not early or not late:
            midpoint = video_duration * 0.5
            early = [row for row in candidates if float(row.get("start_time") or 0.0) <= midpoint]
            late = [row for row in candidates if float(row.get("start_time") or 0.0) > midpoint]
        if early and late:
            pair = _select_cross_state_pair(early, late, video_duration, mode)
            if pair:
                print("[Chat] Face comparison selected early/late state pair from query wording")
                return pair

    pair = _select_best_state_pair(candidates, video_duration, mode)
    if pair:
        print(f"[Chat] Face comparison selected state pair using mode={mode}")
    return pair


def _same_comparison_frame(first: dict, second: dict, tolerance_seconds: float = 2.0) -> bool:
    first_key = _comparison_appearance_key(first)
    second_key = _comparison_appearance_key(second)
    if first_key and second_key and first_key == second_key:
        return True
    return abs(
        float(first.get("start_time") or 0.0) - float(second.get("start_time") or 0.0)
    ) <= tolerance_seconds


def _with_comparison_people(appearance: dict, people: list[tuple[str, Optional[dict]]], label: str) -> dict:
    enriched = dict(appearance)
    enriched["people"] = [name for name, _ in people]
    enriched["label"] = label
    enriched["bboxes"] = [
        {"person": name, "bbox": bbox}
        for name, bbox in people
        if bbox
    ]
    return enriched


def _select_multi_person_state_pair(
    primary_appearances: list[dict],
    secondary_appearances: list[dict],
    video_duration: float,
    query: str,
    primary_person: str,
    secondary_person: str,
) -> Optional[tuple[dict, dict]]:
    """Select Frame A with both people and Frame B with the primary person later/changed."""
    if not primary_appearances or not secondary_appearances:
        return None

    joint_candidates = []
    for primary in primary_appearances:
        for secondary in secondary_appearances:
            if not _same_comparison_frame(primary, secondary):
                continue
            joint_candidates.append(
                _with_comparison_people(
                    primary,
                    [
                        (primary_person, primary.get("bbox")),
                        (secondary_person, secondary.get("bbox")),
                    ],
                    f"{primary_person} with {secondary_person}",
                )
            )
            break

    if not joint_candidates:
        print(
            f"[Chat] Face comparison found no shared frames for "
            f"'{primary_person}' + '{secondary_person}'"
        )
        return None

    mode = _comparison_query_mode(query)
    primary_candidates = sorted(
        primary_appearances,
        key=lambda row: row.get("similarity", 0.0),
        reverse=True,
    )[:120]
    best_pair = None
    best_score = -1.0
    for first in joint_candidates:
        first_time = float(first.get("start_time") or 0.0)
        for second in primary_candidates:
            second_time = float(second.get("start_time") or 0.0)
            if _same_comparison_frame(first, second):
                continue
            if mode in ("early_late", "temporal") and second_time <= first_time:
                continue
            score = _state_pair_score(first, second, video_duration, mode)
            if mode in ("early_late", "temporal"):
                score += 0.25 * min(1.0, max(0.0, (second_time - first_time) / max(video_duration, 1.0)))
            if score > best_score:
                best_score = score
                best_pair = (
                    first,
                    _with_comparison_people(
                        second,
                        [(primary_person, second.get("bbox"))],
                        f"{primary_person} later",
                    ),
                )

    if not best_pair:
        return None
    print(
        f"[Chat] Face comparison selected multi-person pair "
        f"primary='{primary_person}' secondary='{secondary_person}' "
        f"joint_candidates={len(joint_candidates)}"
    )
    return tuple(sorted(best_pair, key=lambda row: float(row.get("start_time") or 0.0)))


def _transcript_window_context(video_hash: str, timestamps: list[float], window_seconds: float = 15.0) -> str:
    transcription = get_transcription_from_any_source(video_hash)
    segments = (transcription or {}).get("transcription", {}).get("segments", [])
    if not segments:
        return "No transcript context is available for these moments."

    blocks = []
    for timestamp in timestamps:
        nearby = []
        for segment in segments:
            text = _segment_text(segment)
            if not text:
                continue
            start, end, start_time, end_time = _segment_bounds(segment)
            if start <= timestamp + window_seconds and end >= timestamp - window_seconds:
                nearby.append(f"[{start_time} - {end_time}] {segment.get('speaker') or 'Unknown'}: {text}")
        label = _format_segment_time(timestamp)
        blocks.append(f"Moment around [{label}]:\n" + ("\n".join(nearby) if nearby else "No nearby transcript lines."))
    return "\n\n".join(blocks)


def _comparison_frame_metadata(appearance: dict) -> dict:
    start = float(appearance.get("start_time") or 0.0)
    metadata = {
        "url": appearance.get("screenshot_url"),
        "timestamp_seconds": start,
        "timestamp": _format_segment_time(start),
        "bbox": appearance.get("bbox"),
    }
    if appearance.get("label"):
        metadata["label"] = appearance.get("label")
    if appearance.get("people"):
        metadata["people"] = appearance.get("people")
    if appearance.get("bboxes"):
        metadata["bboxes"] = appearance.get("bboxes")
    return metadata


def _timeline_frame_metadata(appearance: dict) -> dict:
    start = float(appearance.get("start_time") or 0.0)
    metadata = {
        "url": appearance.get("screenshot_url"),
        "timestamp_seconds": start,
        "timestamp": _format_segment_time(start),
        "bbox": appearance.get("bbox"),
    }
    similarity = appearance.get("similarity")
    if similarity is not None:
        try:
            metadata["similarity"] = float(similarity)
        except (TypeError, ValueError):
            pass
    if appearance.get("low_confidence"):
        metadata["low_confidence"] = True
    return metadata


def _select_timeline_candidates(
    appearances: list[dict],
    pair: Optional[tuple[dict, dict]],
    video_duration: float,
    target_count: int = 8,
) -> list[dict]:
    """
    Pick a small set of evenly-spread, high-quality appearances for the timeline strip.

    Returns appearance dicts (NOT yet projected to metadata), sorted by start_time.
    Force-includes both Frame A and Frame B from `pair` so the strip always shows the
    active pair in context. Enrichment fields (people/bboxes/label) on the pair are
    preserved.
    """
    with_url = [
        appearance for appearance in (appearances or [])
        if appearance.get("screenshot_url")
    ]
    if not with_url:
        if pair:
            return list(pair)
        return []

    times = [float(row.get("start_time") or 0.0) for row in with_url]
    t_min = min(times)
    t_max = max(times)
    distinct_timestamps = {round(t, 2) for t in times}

    bucket_count = min(target_count, len(distinct_timestamps))
    if bucket_count <= 0:
        bucket_count = 1

    picks_by_bucket: dict[int, dict] = {}
    span = max(t_max - t_min, 1e-6)
    for row in with_url:
        t = float(row.get("start_time") or 0.0)
        # Map t into [0, bucket_count); clamp the upper bound exactly into the last bucket.
        idx = int(((t - t_min) / span) * bucket_count)
        if idx >= bucket_count:
            idx = bucket_count - 1
        elif idx < 0:
            idx = 0
        existing = picks_by_bucket.get(idx)
        if (
            existing is None
            or float(row.get("similarity") or 0.0) > float(existing.get("similarity") or 0.0)
        ):
            picks_by_bucket[idx] = row

    picks = list(picks_by_bucket.values())

    # Enforce minimum spacing between picks.
    min_gap = max(2.0, video_duration * 0.01) if video_duration else 2.0
    picks.sort(key=lambda row: float(row.get("start_time") or 0.0))
    filtered: list[dict] = []
    for row in picks:
        if not filtered:
            filtered.append(row)
            continue
        prev = filtered[-1]
        gap = abs(float(row.get("start_time") or 0.0) - float(prev.get("start_time") or 0.0))
        if gap < min_gap:
            # Keep the higher-similarity of the two.
            if float(row.get("similarity") or 0.0) > float(prev.get("similarity") or 0.0):
                filtered[-1] = row
            continue
        filtered.append(row)

    # Force-include Frame A and Frame B. Replace the nearest pick by timestamp so we
    # preserve the enriched pair (joint bboxes / labels) and don't grow past the target.
    def _force_include(target: dict) -> None:
        target_t = float(target.get("start_time") or 0.0)
        target_key = _comparison_appearance_key(target)
        for i, row in enumerate(filtered):
            if _comparison_appearance_key(row) == target_key:
                filtered[i] = target  # replace with enriched copy
                return
        if not filtered:
            filtered.append(target)
            return
        nearest_idx = min(
            range(len(filtered)),
            key=lambda i: abs(float(filtered[i].get("start_time") or 0.0) - target_t),
        )
        nearest = filtered[nearest_idx]
        nearest_gap = abs(float(nearest.get("start_time") or 0.0) - target_t)
        if nearest_gap < min_gap:
            filtered[nearest_idx] = target
        else:
            filtered.append(target)

    if pair:
        _force_include(pair[0])
        _force_include(pair[1])

    filtered.sort(key=lambda row: float(row.get("start_time") or 0.0))
    return filtered


def _format_person_comparison_answer(
    person_name: str,
    frame_a: dict,
    frame_b: dict,
    prose: str,
    secondary_person_name: Optional[str] = None,
    timeline_appearances: Optional[list[dict]] = None,
) -> str:
    metadata = {
        "person": person_name,
        "frame_a": frame_a,
        "frame_b": frame_b,
    }
    if secondary_person_name:
        metadata["secondary_person"] = secondary_person_name
    if timeline_appearances:
        metadata["timeline"] = [
            _timeline_frame_metadata(appearance)
            for appearance in timeline_appearances
            if appearance.get("screenshot_url")
        ]
    return (
        "## Person Comparison\n\n"
        "```json\n"
        f"{json.dumps(metadata, ensure_ascii=False)}\n"
        "```\n\n"
        f"{(prose or '').strip()}"
    )


async def _run_person_comparison_llm(
    request: Request,
    *,
    person_name: str,
    secondary_person_name: Optional[str],
    frame_a_appearance: dict,
    frame_b_appearance: dict,
    question: str,
    custom_instructions: Optional[str],
    provider_name: Optional[str],
    video_hash: str,
    timeline_appearances: Optional[list[dict]] = None,
) -> Dict:
    """
    Build the comparison prompt for the resolved pair, run the vision LLM, and return
    the standard chat response shape. Shared by the auto-detect path and the swap endpoint.
    """
    frame_a = _comparison_frame_metadata(frame_a_appearance)
    frame_b = _comparison_frame_metadata(frame_b_appearance)
    transcript_context = _transcript_window_context(
        video_hash,
        [frame_a["timestamp_seconds"], frame_b["timestamp_seconds"]],
        window_seconds=15.0,
    )

    # Resolve timeline intermediates (frames that are neither A nor B).
    intermediates: list[dict] = []
    if timeline_appearances:
        a_key = _comparison_appearance_key(frame_a_appearance)
        b_key = _comparison_appearance_key(frame_b_appearance)
        intermediates = [
            appearance for appearance in timeline_appearances
            if appearance.get("screenshot_url")
            and _comparison_appearance_key(appearance) not in {a_key, b_key}
        ]
        intermediates.sort(key=lambda row: float(row.get("start_time") or 0.0))

    provider = await _get_chat_provider(request, provider_name)
    if not provider.supports_vision():
        provider = await _get_chat_provider(request, "grok")
        provider_name = "grok"

    system_message = (
        "You compare two video frames involving a tagged person. "
        "Focus on visible evidence only and be explicit about uncertainty. "
        "Compare exactly these axes: emotion/facial expression, physical appearance "
        "(clothing, hair, injuries, dirt, age cues), and surroundings/context "
        "(location, lighting, nearby people or objects). Cite timestamps in [HH:MM:SS] format."
    )
    if secondary_person_name:
        system_message += (
            f" Frame A may be selected because it contains both {person_name} "
            f"and {secondary_person_name}; do not claim the second person is present "
            "in Frame B unless visibly shown or supported by the metadata."
        )
    if intermediates:
        system_message += (
            "\n\nAdditional intermediate frames are provided (image positions 3 onward) at "
            "timestamps spread across the video. After the three-axis comparison and the "
            "closing change sentence, add ONE FINAL paragraph that begins with "
            "\"**Timeline arc:**\" (bold lead-in, same line as content, no heading). In that "
            "paragraph, walk through ALL frames in chronological order — including Frame A and "
            "Frame B — briefly noting visible change at each timestamp in [HH:MM:SS] format. "
            "Aim for ~12 words per timestamp. Keep it grounded in what you actually see; do "
            "not invent. The whole paragraph should read as a short narrative."
        )
    if custom_instructions:
        system_message += (
            "\n\nUser's custom instructions (follow these preferences):\n"
            f"{custom_instructions}"
        )

    user_message_parts = [
        f"Question: {question}",
        "",
        f"Tagged person: {person_name}",
    ]
    if secondary_person_name:
        user_message_parts.append(f"Additional tagged person requested: {secondary_person_name}")
    if frame_a.get("label"):
        user_message_parts.append(f"Frame A label: {frame_a.get('label')}")
    if frame_b.get("label"):
        user_message_parts.append(f"Frame B label: {frame_b.get('label')}")
    if frame_a.get("people"):
        user_message_parts.append(f"Frame A people: {', '.join(frame_a.get('people') or [])}")
    if frame_b.get("people"):
        user_message_parts.append(f"Frame B people: {', '.join(frame_b.get('people') or [])}")
    user_message_parts.extend([
        f"Frame A timestamp: [{frame_a['timestamp']}]",
        f"Frame B timestamp: [{frame_b['timestamp']}]",
    ])
    if intermediates:
        intermediate_lines = []
        for offset, appearance in enumerate(intermediates, start=3):
            ts = _format_segment_time(float(appearance.get("start_time") or 0.0))
            intermediate_lines.append(f"  - Image {offset} → [{ts}]")
        user_message_parts.extend([
            "",
            "Intermediate timeline frames (in chronological order, for the Timeline arc):",
            *intermediate_lines,
        ])
    user_message_parts.extend([
        "",
        f"Nearby transcript context:\n{transcript_context}",
        "",
        "Write a concise comparison. Use bullets grouped by the three requested axes, "
        "then end with one sentence summarizing the biggest visible change.",
    ])
    if intermediates:
        user_message_parts[-1] += (
            " Then add the **Timeline arc:** paragraph as described in the system message."
        )

    messages = [
        {
            "role": "system",
            "content": system_message,
        },
        {
            "role": "user",
            "content": "\n".join(user_message_parts),
        },
    ]
    image_paths = [frame_a["url"], frame_b["url"]]
    image_paths.extend(
        appearance["screenshot_url"] for appearance in intermediates
    )
    prose = await provider.generate_with_images(
        messages,
        image_paths=image_paths,
        temperature=0.3,
        max_tokens=1800,
    )

    return {
        "answer": _format_person_comparison_answer(
            person_name,
            frame_a,
            frame_b,
            prose,
            secondary_person_name=secondary_person_name,
            timeline_appearances=timeline_appearances,
        ),
        "sources": [],
        "provider_used": provider_name or llm_manager.default_provider,
        "video_hash": video_hash,
    }


async def _handle_person_comparison(
    request: Request,
    chat_request: ChatRequest,
    intent: ComparisonIntent,
) -> Dict:
    if not intent.person_name:
        name_text = f" {intent.unmatched_name}" if intent.unmatched_name else " that person"
        return {
            "answer": f"I don't recognise{name_text} yet. Tag a face in any screenshot first.",
            "sources": [],
            "provider_used": chat_request.provider or "none",
            "video_hash": chat_request.video_hash,
        }

    video_hash = chat_request.video_hash
    appearances = await _load_person_appearances_with_fallback(video_hash, intent.person_name)
    video_duration = _video_duration_seconds(video_hash, appearances)
    pair = None
    if intent.secondary_person_name:
        secondary_appearances = await _load_person_appearances_with_fallback(
            video_hash,
            intent.secondary_person_name,
        )
        video_duration = _video_duration_seconds(
            video_hash,
            [*appearances, *secondary_appearances],
        )
        pair = _select_multi_person_state_pair(
            primary_appearances=appearances,
            secondary_appearances=secondary_appearances,
            video_duration=video_duration,
            query=chat_request.question,
            primary_person=intent.person_name,
            secondary_person=intent.secondary_person_name,
        )

    person_names = [n for n in (intent.person_name, intent.secondary_person_name) if n]
    if not pair:
        pair = _select_state_pair(appearances, video_duration, chat_request.question, person_names)
    if not pair:
        print(
            f"[Chat] Face comparison could not select a distinct pair from "
            f"{len(appearances)} presence appearances for '{intent.person_name}'; "
            "retrying with manual face tags"
        )
        reference_embedding = _load_speaker_reference_embedding(video_hash, intent.person_name)
        tagged_appearances = (
            _load_face_tag_appearances(video_hash, intent.person_name, reference_embedding)
            if reference_embedding
            else []
        )
        appearances = _merge_comparison_appearances(appearances, tagged_appearances)
        video_duration = _video_duration_seconds(video_hash, appearances)
        pair = _select_state_pair(appearances, video_duration, chat_request.question, person_names)

    if not pair:
        return {
            "answer": (
                f"I found {intent.person_name}, but not enough separate face appearances "
                "to compare yet. Ask a normal chat question, or index more screenshots first."
            ),
            "sources": [],
            "provider_used": chat_request.provider or "none",
            "video_hash": video_hash,
        }

    timeline_appearances = _select_timeline_candidates(appearances, pair, video_duration)

    return await _run_person_comparison_llm(
        request,
        person_name=intent.person_name,
        secondary_person_name=intent.secondary_person_name,
        frame_a_appearance=pair[0],
        frame_b_appearance=pair[1],
        question=chat_request.question,
        custom_instructions=chat_request.custom_instructions,
        provider_name=chat_request.provider,
        video_hash=video_hash,
        timeline_appearances=timeline_appearances,
    )


# ---------------------------------------------------------------------------
# Pure helper functions (no SSE knowledge, shared by sync and streaming endpoints)
# ---------------------------------------------------------------------------

async def _retrieve_text_context(
    video_hash: str,
    question: str,
    n_results: int,
) -> tuple[list, str, list]:
    """
    Search transcript vector store and build context text + sources list.

    Returns:
        (search_results, context_text, sources)
        search_results is the raw list from vector_store.search; empty list if none found.
    """
    query = _clean_query_for_retrieval(question)
    print(f"Searching for relevant context for question: {query}")
    search_results = await _run_in_executor(vector_store.search, video_hash, query, n_results=n_results)

    transcription = get_transcription_from_any_source(video_hash)
    segments = (transcription or {}).get("transcription", {}).get("segments", [])

    if not search_results:
        # Existing empty Chroma collections can make collection_exists() true
        # while search() returns nothing. Rebuild from the persisted transcript
        # once, then retry.
        if segments:
            try:
                await _run_in_executor(vector_store.index_transcription, video_hash, segments)
                search_results = await _run_in_executor(
                    vector_store.search,
                    video_hash,
                    query,
                    n_results=n_results,
                )
            except Exception as e:
                print(f"Transcript reindex/search retry failed: {e}")

    if not search_results:
        fallback = _speaker_segment_context(video_hash, query, limit=max(n_results * 3, 12))
        if fallback[0]:
            return fallback
        lexical_results = _lexical_segment_matches(
            video_hash,
            question,
            segments,
            limit=max(n_results, 6),
        )
        if lexical_results:
            context, sources = _format_text_context(video_hash, lexical_results)
            return lexical_results, context, sources
        return [], "", []

    max_context_results = max(n_results * 4, 16)
    expanded_results = _expand_text_hits_with_neighbors(
        video_hash,
        search_results,
        segments,
        neighbor_count=1,
        max_results=max_context_results,
    )
    lexical_results = _lexical_segment_matches(
        video_hash,
        question,
        segments,
        limit=max(3, n_results // 2),
    )
    combined_results = _merge_text_results(
        expanded_results,
        lexical_results,
        max_results=max_context_results,
    )

    if len(combined_results) != len(search_results):
        print(
            f"Text retrieval context expanded: semantic={len(search_results)}, "
            f"context_segments={len(combined_results)}"
        )

    context, sources = _format_text_context(video_hash, combined_results)
    search_results = combined_results
    return search_results, context, sources


async def _retrieve_visual_context(
    video_hash: str,
    question: str,
    n_images: int,
    user_visual_terms: Optional[set[str]] = None,
    user_visual_phrases: Optional[list[str]] = None,
    phase_cb: Optional[Callable[[str, str], Awaitable[None]]] = None,
) -> dict:
    """
    Search image embeddings, apply temporal + face re-ranking, and return visual context.

    phase_cb: optional async callback(phase_name, label) called before each sub-stage.
              The streaming endpoint passes a coroutine that emits SSE phase events;
              the sync endpoint passes None.

    Returns a dict with keys:
        images_indexed (bool) - False means images are not indexed; all other keys absent
        image_paths, visual_context, visual_sources, visual_query_used,
        image_results, face_tags_available, speaker_names
    """
    use_supabase = _use_supabase_for_images()
    if use_supabase:
        images_indexed = image_embedding_service.image_collection_exists(video_hash)
    else:
        images_indexed = vector_store.image_collection_exists(video_hash)

    try:
        # Extract ALL speaker names from the query
        speaker_names = _extract_all_speakers_from_query(question, video_hash)
        transcription = None
        segments = []
        total_segments = 0
        transcription = get_transcription_from_any_source(video_hash)
        if transcription:
            segments = transcription.get('transcription', {}).get('segments', [])
            total_segments = len(segments)

        # CLIP doesn't know specific people by name; replace names with generic "person"/"people"
        visual_query = _clean_query_for_retrieval(question)
        if speaker_names:
            import re
            replacement = "person" if len(speaker_names) == 1 else "people"
            for speaker_name in speaker_names:
                visual_query = re.sub(
                    rf'\b{re.escape(speaker_name)}\b',
                    replacement,
                    visual_query,
                    flags=re.IGNORECASE
                )
            print(f"Visual search: transformed '{question}' -> '{visual_query}'")
            visual_query_used = visual_query
        else:
            visual_query_used = question

        image_results = []
        query_variants = []
        user_visual_terms = user_visual_terms or set()
        user_visual_phrases = user_visual_phrases or []
        configured_visual_query = _query_matches_user_visual_terms(visual_query, user_visual_terms)
        if images_indexed:
            print(f"Visual analysis requested, searching for {n_images} relevant images...")

            # Sub-stage: CLIP scene search
            if phase_cb is not None:
                await phase_cb("analyzing_scenes", "Analyzing scenes")

            seen_image_paths = set()
            query_variants = _visual_query_variants(
                visual_query,
                user_visual_terms=user_visual_terms,
                user_visual_phrases=user_visual_phrases,
            )[:6]
            per_variant_results = max(n_images, 4)
            for query_variant in query_variants:
                if use_supabase:
                    variant_results = await _run_in_executor(
                        image_embedding_service.search_images,
                        video_hash,
                        query_variant,
                        n_results=per_variant_results,
                        speaker_filter=None
                    )
                else:
                    variant_results = await _run_in_executor(
                        vector_store.search_images,
                        video_hash,
                        query_variant,
                        n_results=per_variant_results,
                        speaker_filter=None
                    )

                for result in variant_results:
                    key = _image_result_key(result)
                    if key in seen_image_paths:
                        continue
                    seen_image_paths.add(key)
                    result["visual_query_variant"] = query_variant
                    image_results.append(result)

            if len(query_variants) > 1:
                print(
                    f"Visual multi-query search: {len(query_variants)} variants, "
                    f"{len(image_results)} unique CLIP candidates"
                )

            clip_candidate_limit = max(n_images * 4, min(32, n_images * (1 + total_segments // 100)))
            if len(image_results) > clip_candidate_limit:
                image_results.sort(
                    key=lambda result: result.get(
                        'similarity',
                        max(0, 1 - result.get('distance', 1)) if 'distance' in result else 0,
                    ),
                    reverse=True,
                )
                image_results = image_results[:clip_candidate_limit]
        else:
            print(
                f"Images not indexed for video {video_hash}. "
                "Checking face tags before falling back to text-only analysis."
            )

        face_tag_results = []
        if speaker_names:
            face_tag_results = await _face_tag_image_results(
                video_hash,
                speaker_names,
                n_images,
            )
            if face_tag_results:
                if configured_visual_query and image_results:
                    print(
                        "Face-tag candidates available, but using them for identity "
                        "scoring only because the query matches configured visual search terms."
                    )
                else:
                    deduped = []
                    seen_paths = set()
                    # For identity-only questions, include manually tagged
                    # face screenshots as candidates. For action questions,
                    # keep CLIP scene matches as the candidate pool and use
                    # face tags only to score whether those scenes include the
                    # named person.
                    for source_results in (image_results, face_tag_results):
                        for result in source_results:
                            key = _image_result_key(result)
                            if key in seen_paths:
                                continue
                            seen_paths.add(key)
                            deduped.append(result)
                    image_results = deduped

        face_tags_available = False

        if configured_visual_query and image_results:
            before_trim = len(image_results)
            image_results.sort(
                key=lambda result: result.get(
                    'similarity',
                    max(0, 1 - result.get('distance', 1)) if 'distance' in result else 0,
                ),
                reverse=True,
            )
            image_results = image_results[:n_images]
            if before_trim != len(image_results):
                print(
                    "Configured visual query: trimmed scene candidates before "
                    f"face scoring ({before_trim} -> {len(image_results)})"
                )

        # Phase 1: Temporal Correlation Scoring
        if speaker_names and image_results:
            print(f"Applying presence correlation scoring for speakers: {speaker_names}")

            speaker_face_embeddings = _load_speaker_face_embeddings(video_hash, speaker_names)
            face_tags_available = bool(speaker_face_embeddings)
            face_presence_by_image, presence_timelines = await _load_face_presence(
                video_hash,
                speaker_face_embeddings,
            )
            has_face_presence = any(presence_timelines.values())

            if transcription:
                if has_face_presence:
                    speaker_timelines = presence_timelines
                    for name in speaker_names:
                        print(f"  Speaker '{name}': {len(speaker_timelines.get(name, []))} face-presence spans")
                else:
                    speaker_timelines = {}
                    for name in speaker_names:
                        speaker_timelines[name] = [
                            (seg['start'], seg['end'])
                            for seg in segments
                            if seg.get('speaker', '').lower() == name.lower()
                        ]
                        print(f"  Speaker '{name}': {len(speaker_timelines[name])} voice segments")

                for result in image_results:
                    img_start = float(result['metadata'].get('start', 0) or 0)
                    img_end = float(result['metadata'].get('end', 0) or 0)

                    overlap_score = 0
                    overlapping_speakers = []

                    for speaker, timeline in speaker_timelines.items():
                        for seg_start, seg_end in timeline:
                            if img_start <= seg_end and img_end >= seg_start:
                                overlap_score += 1
                                if speaker not in overlapping_speakers:
                                    overlapping_speakers.append(speaker)

                    from config import settings
                    if settings.CHAT_DEBUG_LOGS and overlap_score == 0 and speaker_timelines:
                        first_speaker = list(speaker_timelines.keys())[0]
                        tl = speaker_timelines[first_speaker]
                        if tl:
                            print(f"  DEBUG overlap=0: img=[{img_start:.1f}-{img_end:.1f}], "
                                  f"first segment=[{tl[0][0]:.1f}-{tl[0][1]:.1f}], "
                                  f"last segment=[{tl[-1][0]:.1f}-{tl[-1][1]:.1f}], "
                                  f"total={len(tl)} segments")

                    result['overlap_score'] = overlap_score
                    result['likely_speakers'] = overlapping_speakers

                # Sub-stage: face re-ranking (only if face tags exist)
                if face_tags_available:
                    if phase_cb is not None:
                        await phase_cb("matching_faces", "Matching faces")

                    print("Computing face scores for visual results...")
                    try:
                        for result in image_results:
                            # Manually tagged face rows are already positive
                            # identity evidence; re-running face detection on
                            # them is slow and can fail on marginal frames.
                            if result.get("source") == "face_tag":
                                result['face_score'] = 1.0
                                if not result.get('likely_speakers'):
                                    result['likely_speakers'] = speaker_names
                                continue

                            image_id = str(result.get('metadata', {}).get('image_embedding_id') or "")
                            speaker_scores = face_presence_by_image.get(image_id, {})
                            if speaker_scores:
                                result['face_score'] = max(speaker_scores.values())
                                likely = [
                                    speaker for speaker, score in speaker_scores.items()
                                    if score >= 0.5
                                ]
                                if likely:
                                    result['likely_speakers'] = sorted(set(result.get('likely_speakers', []) + likely))
                                continue

                            result['face_score'] = 0.0

                        if not has_face_presence:
                            from services.face_service import face_service
                            print("No face-presence rows found; falling back to query-time face detection")
                            for result in image_results:
                                if result.get("source") == "face_tag":
                                    continue
                                screenshot_url = result.get('screenshot_url') or result.get('screenshot_path', '')
                                if not screenshot_url:
                                    continue

                                detected = await _run_in_executor(face_service.detect_faces, screenshot_url)
                                if not detected:
                                    continue

                                max_sim = 0.0
                                matched_speakers = []
                                for det_face in detected:
                                    for speaker, ref_emb in speaker_face_embeddings.items():
                                        sim = face_service.compute_face_similarity(
                                            det_face['embedding'], ref_emb
                                        )
                                        if sim >= 0.5:
                                            matched_speakers.append(speaker)
                                        max_sim = max(max_sim, sim)
                                result['face_score'] = max(0.0, max_sim)
                                if matched_speakers:
                                    result['likely_speakers'] = sorted(
                                        set(result.get('likely_speakers', []) + matched_speakers)
                                    )
                    except Exception as e:
                        print(f"  Face scoring failed (falling back to no face): {e}")
                        face_tags_available = False

                # Hybrid ranking: temporal is on-screen face presence when the
                # face-presence index exists, otherwise speaker voice overlap.
                for result in image_results:
                    clip_score = result.get('similarity', 0)
                    if clip_score == 0 and 'distance' in result:
                        clip_score = max(0, 1 - result['distance'])

                    max_overlap = 3
                    normalized_overlap = min(result.get('overlap_score', 0), max_overlap) / max_overlap

                    if face_tags_available:
                        face_score = result.get('face_score', 0.0)
                        if configured_visual_query:
                            result['hybrid_score'] = 0.95 * clip_score + 0.05 * face_score
                        else:
                            result['hybrid_score'] = 0.6 * clip_score + 0.15 * normalized_overlap + 0.25 * face_score
                    else:
                        result['hybrid_score'] = 0.8 * clip_score + 0.2 * normalized_overlap

                image_results.sort(key=lambda x: x.get('hybrid_score', 0), reverse=True)

                if face_tags_available and configured_visual_query:
                    ranking_mode = "95% CLIP + 5% face"
                elif face_tags_available:
                    ranking_mode = "60% CLIP + 15% temporal + 25% face"
                else:
                    ranking_mode = "80% CLIP + 20% temporal"
                print(f"Scored {len(image_results)} visual results with hybrid ranking ({ranking_mode})")
                from config import settings
                if settings.CHAT_DEBUG_LOGS:
                    for i, result in enumerate(image_results[:3]):
                        face_info = f", face={result.get('face_score', 0):.3f}" if face_tags_available else ""
                        print(f"  Result {i+1}: hybrid={result.get('hybrid_score', 0):.3f}, "
                              f"clip={result.get('similarity', 0):.3f}, "
                              f"overlap={result.get('overlap_score', 0)}{face_info}, "
                              f"variant={result.get('visual_query_variant', result.get('source', 'unknown'))}, "
                              f"speakers={result.get('likely_speakers', [])}")

        image_paths = []
        visual_context = ""
        visual_sources = []

        if image_results:
            if not any("hybrid_score" in result for result in image_results):
                image_results.sort(
                    key=lambda result: result.get(
                        'similarity',
                        max(0, 1 - result.get('distance', 1)) if 'distance' in result else 0,
                    ),
                    reverse=True,
                )
            image_results = image_results[:n_images]
            print(f"Found {len(image_results)} relevant images")
            image_paths = [result.get('screenshot_url') or result.get('screenshot_path') for result in image_results]

            visual_parts = []
            for i, img_result in enumerate(image_results):
                metadata = img_result['metadata']
                screenshot_path = img_result.get('screenshot_url') or img_result.get('screenshot_path', '')

                if screenshot_path.startswith('https://'):
                    screenshot_url = screenshot_path
                elif 'static/screenshots/' in screenshot_path:
                    filename = screenshot_path.split('static/screenshots/')[-1]
                    screenshot_url = f"/static/screenshots/{filename}"
                else:
                    screenshot_url = screenshot_path.replace('./static/', '/static/')

                speaker_display = ', '.join(img_result.get('likely_speakers', [])) or metadata['speaker']
                visual_parts.append(
                    f"Screenshot {i+1} - Timestamp: {metadata['start']:.2f}s - {metadata['end']:.2f}s, "
                    f"Speaker: {speaker_display}"
                )

                visual_sources.append({
                    "start_time": f"{int(metadata['start'] // 3600):02d}:{int((metadata['start'] % 3600) // 60):02d}:{int(metadata['start'] % 60):02d}",
                    "end_time": f"{int(metadata['end'] // 3600):02d}:{int((metadata['end'] % 3600) // 60):02d}:{int(metadata['end'] % 60):02d}",
                    "start": metadata['start'],
                    "end": metadata['end'],
                    "speaker": ', '.join(img_result.get('likely_speakers', [])) or metadata['speaker'],
                    "screenshot_url": screenshot_url,
                    "type": "visual",
                    "likely_speakers": img_result.get('likely_speakers', []),
                    "overlap_score": img_result.get('overlap_score', 0),
                    "visual_query_variant": img_result.get('visual_query_variant'),
                    "visual_similarity": img_result.get('similarity'),
                    "hybrid_score": img_result.get('hybrid_score'),
                    "face_score": img_result.get('face_score'),
                    "source_kind": img_result.get('source') or "clip",
                    "evidence_label": (
                        "Identity match"
                        if img_result.get('source') == "face_tag"
                        else "Scene + identity"
                        if img_result.get('likely_speakers')
                        else "Scene match"
                    )
                })

            visual_context = "\n".join(visual_parts)
            print(f"Visual context: {visual_context}")
        else:
            print("No relevant images found for the query")
            if not images_indexed:
                return {"images_indexed": False}

        return {
            "images_indexed": images_indexed or bool(image_results),
            "image_paths": image_paths,
            "visual_context": visual_context,
            "visual_sources": visual_sources,
            "visual_query_used": visual_query_used,
            "visual_query_variants": query_variants,
            "image_results": image_results,
            "face_tags_available": face_tags_available,
            "speaker_names": speaker_names,
        }

    except Exception as e:
        print(f"Warning: Failed to search images: {str(e)}")
        return {
            "images_indexed": True,
            "image_paths": [],
            "visual_context": "",
            "visual_sources": [],
            "visual_query_used": question,
            "visual_query_variants": [],
            "image_results": [],
            "face_tags_available": False,
            "speaker_names": [],
        }


async def _retrieve_audio_context(
    video_hash: str,
    question: str,
    search_results: list,
    image_results: list,
) -> tuple[str, list, bool]:
    """
    Search audio event vector store, apply temporal re-ranking, and return audio context.

    Returns:
        (audio_context, audio_sources, audio_indexed)
    """
    if not vector_store.audio_collection_exists(video_hash):
        return "", [], False

    audio_context = ""
    audio_sources = []

    try:
        audio_results = await _run_in_executor(
            vector_store.search_audio_events,
            video_hash,
            question,
            n_results=20
        )

        if audio_results:
            temporal_anchors = []

            if search_results:
                for sr in search_results:
                    s = sr.get('metadata', {}).get('start')
                    e = sr.get('metadata', {}).get('end')
                    if s is not None and e is not None:
                        temporal_anchors.append((float(s), float(e)))

            if image_results:
                for ir in image_results:
                    s = ir.get('metadata', {}).get('start')
                    e = ir.get('metadata', {}).get('end')
                    if s is not None and e is not None:
                        temporal_anchors.append((float(s), float(e)))

            if temporal_anchors:
                for audio_result in audio_results:
                    a_start = float(audio_result['metadata'].get('start', 0) or 0)
                    a_end = float(audio_result['metadata'].get('end', 0) or 0)
                    a_mid = (a_start + a_end) / 2

                    min_dist = float('inf')
                    for anchor_start, anchor_end in temporal_anchors:
                        anchor_mid = (anchor_start + anchor_end) / 2
                        dist = abs(a_mid - anchor_mid)
                        min_dist = min(min_dist, dist)

                    audio_result['temporal_distance'] = min_dist

                audio_results.sort(key=lambda x: x.get('temporal_distance', float('inf')))

                n_text = sum(1 for sr in (search_results or []) if sr.get('metadata', {}).get('start') is not None)
                n_img = len(temporal_anchors) - n_text
                print(f"Audio re-ranking: {n_text} text + {n_img} image = {len(temporal_anchors)} anchors, "
                      f"closest={audio_results[0]['temporal_distance']:.1f}s, "
                      f"furthest={audio_results[-1]['temporal_distance']:.1f}s")

            audio_results = audio_results[:5]
            print(f"Found {len(audio_results)} relevant audio events")
            audio_parts = []

            for i, audio_result in enumerate(audio_results):
                metadata = audio_result['metadata']
                description = audio_result['description']

                audio_parts.append(
                    f"Audio Event {i+1} - Timestamp: {metadata['start']:.2f}s - {metadata['end']:.2f}s, "
                    f"Events: {description}"
                )

                events_list = description.split(", ")

                for event_str in events_list[:3]:
                    if "(" in event_str and ")" in event_str:
                        event_type = event_str.split("(")[0].strip()
                        confidence_str = event_str.split("(")[1].split("%")[0].strip()

                        try:
                            confidence = float(confidence_str) / 100.0
                        except ValueError:
                            confidence = 0.5

                        if confidence < 0.3:
                            continue

                        if event_type.startswith("emotion:"):
                            event_type = event_type.replace("emotion:", "").strip()

                        audio_sources.append({
                            "start_time": f"{int(float(metadata['start']) // 3600):02d}:{int((float(metadata['start']) % 3600) // 60):02d}:{int(float(metadata['start']) % 60):02d}",
                            "end_time": f"{int(float(metadata['end']) // 3600):02d}:{int((float(metadata['end']) % 3600) // 60):02d}:{int(float(metadata['end']) % 60):02d}",
                            "start": float(metadata['start']),
                            "end": float(metadata['end']),
                            "speaker": metadata.get('speaker', 'Unknown'),
                            "event_type": event_type,
                            "confidence": confidence,
                            "type": "audio"
                        })

            audio_context = "\n".join(audio_parts)

    except Exception as e:
        print(f"Warning: Failed to search audio events: {str(e)}")
        import traceback
        traceback.print_exc()

    return audio_context, audio_sources, True


def _build_chat_messages(
    question: str,
    context: str,
    visual_context: str,
    audio_context: str,
    has_images: bool,
    custom_instructions: Optional[str],
    conversation_history: Optional[list],
) -> list:
    """
    Build the messages list ready for the LLM from retrieved context.

    Returns:
        messages list with system, optional history, and user turns
    """
    if has_images:
        system_message = """You are an expert AI assistant specialized in analyzing video content, combining both visual and textual information.

Your role:
- Analyze both the visual content (screenshots) and transcript text
- Provide detailed, comprehensive answers based on what you see and what is said
- Always cite specific timestamps when referencing information (use format [HH:MM:SS])
- Identify speakers and their contributions clearly
- Describe visual elements when relevant to the question
- Connect visual and textual information to provide richer insights
- Offer insights and analysis, not just basic summaries
- Use markdown formatting for better readability (bold, bullet points, etc.)

Communication style:
- Think through your analysis out loud: "Looking at this section, I notice...", "What's interesting here is..."
- Express when something is ambiguous: "The transcript isn't entirely clear on this, but based on the visual context..."
- Offer constructive observations: "One thing worth noting...", "A potential concern here is..."
- When you see multiple interpretations, acknowledge them: "This could mean X or Y - based on what I see, I lean toward X because..."
- If the question could be interpreted multiple ways, briefly ask for clarification at the end
- Be honest about limitations: "I can see X in the screenshot, but I'd need more context to determine..."

Response structure (use these exact markdown headers):
- Start with ## Direct Answer — 2-3 sentences directly answering the question
- Follow with ## Key Analysis — detailed breakdown with bullet points, timestamps, and evidence
- If screenshots are relevant, add ## Visual Observations — describe what you see in the visual content
- Use > blockquotes for direct speaker quotes (e.g., > "exact words" — Speaker Name [HH:MM:SS])
- Use **bold** sparingly for key terms only, not entire sentences
- Always cite timestamps in [HH:MM:SS] format

Guidelines:
- When analyzing screenshots, describe what you observe and how it relates to the question
- For sexual or body-appearance questions, stay factual and neutral: describe visible evidence, timing, and uncertainty. Do not rate attractiveness or make subjective sexualized judgments.
- Include relevant quotes from speakers when appropriate
- Explain context, implications, and connections between ideas
- If asked to summarize, organize information logically with bullet points or sections
- Reference multiple sources/timestamps to support your answers
- If the context is insufficient, explain what information is missing"""

        if custom_instructions:
            system_message += f"\n\nUser's custom instructions (follow these preferences):\n{custom_instructions}"

        user_message_parts = [
            "Based on the following transcript segments and screenshots from the video, please answer the question comprehensively.",
            "",
            "VIDEO TRANSCRIPT CONTEXT:",
            context,
            "",
            "VISUAL CONTEXT (Screenshots provided):",
            visual_context
        ]

        if audio_context:
            user_message_parts.extend([
                "",
                "AUDIO CONTEXT (Sound Events):",
                audio_context
            ])

        user_message_parts.extend([
            "",
            f"QUESTION: {question}",
            "",
            "Please provide a detailed, well-structured answer that:",
            "1. Directly addresses the question",
            "2. Analyzes both the visual content in the screenshots AND the transcript text"
        ])

        if audio_context:
            user_message_parts.append("3. Considers relevant audio events and sound cues")
            user_message_parts.append("4. Cites specific timestamps and speakers")
            user_message_parts.append("5. Describes relevant visual elements you observe")
            user_message_parts.append("6. Provides context and analysis connecting visual, audio, and textual information")
            user_message_parts.append("7. Uses markdown formatting for clarity")
        else:
            user_message_parts.append("3. Cites specific timestamps and speakers")
            user_message_parts.append("4. Describes relevant visual elements you observe")
            user_message_parts.append("5. Provides context and analysis connecting visual and textual information")
            user_message_parts.append("6. Uses markdown formatting for clarity")

        user_message = "\n".join(user_message_parts)
    else:
        system_message = """You are an expert AI assistant specialized in analyzing video content and transcripts.

Your role:
- Provide detailed, comprehensive answers based on the video transcript
- Always cite specific timestamps when referencing information (use format [HH:MM:SS])
- Identify speakers and their contributions clearly
- Connect related points across different parts of the video
- Offer insights and analysis, not just basic summaries
- Use markdown formatting for better readability (bold, bullet points, etc.)

Communication style:
- Think through your analysis out loud: "Looking at this section, I notice...", "What's interesting here is..."
- Express when something is ambiguous: "The transcript isn't entirely clear on this, but based on the context..."
- Offer constructive observations: "One thing worth noting...", "A potential concern here is..."
- When you see multiple interpretations, acknowledge them: "This could mean X or Y - based on the surrounding discussion, I lean toward X because..."
- If the question could be interpreted multiple ways, briefly ask for clarification at the end
- Be honest about limitations: "Based on what's in the transcript, I can tell you X, but I'd need more context to determine..."

Response structure (use these exact markdown headers):
- Start with ## Direct Answer — 2-3 sentences directly answering the question
- Follow with ## Key Analysis — detailed breakdown with bullet points, timestamps, and evidence
- Use > blockquotes for direct speaker quotes (e.g., > "exact words" — Speaker Name [HH:MM:SS])
- Use **bold** sparingly for key terms only, not entire sentences
- Always cite timestamps in [HH:MM:SS] format

Guidelines:
- Be thorough and detailed in your responses
- For sexual or body-appearance questions, stay factual and neutral: describe evidence in the transcript, timing, and uncertainty. Do not rate attractiveness or make subjective sexualized judgments.
- Include relevant quotes from speakers when appropriate
- Explain context, implications, and connections between ideas
- If asked to summarize, organize information logically with bullet points or sections
- Reference multiple sources/timestamps to support your answers
- If the context is insufficient, explain what information is missing"""

        if custom_instructions:
            system_message += f"\n\nUser's custom instructions (follow these preferences):\n{custom_instructions}"

        user_message_parts = [
            "Based on the following transcript segments from the video, please answer the question comprehensively.",
            "",
            "VIDEO TRANSCRIPT CONTEXT:",
            context
        ]

        if audio_context:
            user_message_parts.extend([
                "",
                "AUDIO CONTEXT (Sound Events):",
                audio_context
            ])

        if visual_context:
            user_message_parts.extend([
                "",
                "RETRIEVED SCREENSHOT/TIMESTAMP CONTEXT (metadata only; images are not attached):",
                visual_context
            ])

        user_message_parts.extend([
            "",
            f"QUESTION: {question}",
            "",
            "Please provide a detailed, well-structured answer that:",
            "1. Directly addresses the question",
            "2. Cites specific timestamps and speakers",
            "3. Provides context and analysis"
        ])

        if audio_context:
            user_message_parts.append("4. Considers relevant audio events and sound cues")
            user_message_parts.append("5. Uses markdown formatting for clarity")
            user_message_parts.append("6. Connects related information from different parts of the video")
            if visual_context:
                user_message_parts.append("7. Uses screenshot metadata only for timestamps; do not claim to see image details")
        else:
            user_message_parts.append("4. Uses markdown formatting for clarity")
            user_message_parts.append("5. Connects related information from different parts of the video")
            if visual_context:
                user_message_parts.append("6. Uses screenshot metadata only for timestamps; do not claim to see image details")

        user_message = "\n".join(user_message_parts)

    messages = [
        {"role": "system", "content": system_message},
    ]

    if conversation_history:
        valid_history = []
        for msg in conversation_history:
            if not isinstance(msg, dict):
                continue
            role = msg.get("role")
            content = msg.get("content")
            if role not in ("user", "assistant") or not isinstance(content, str):
                continue
            valid_history.append({
                "role": role,
                "content": content[:8192],
            })
        history = valid_history[-10:]
        for msg in history:
            messages.append({
                "role": msg["role"],
                "content": msg["content"]
            })

    messages.append({"role": "user", "content": user_message})
    return messages


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

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
        # Get transcription data from any available source (legacy DB or Supabase jobs)
        if video_hash:
            transcription = get_transcription_from_any_source(video_hash)
            if not transcription:
                raise HTTPException(status_code=404, detail="Transcription not found")
        else:
            # Use last transcription
            global _last_transcription_data
            if not _last_transcription_data:
                raise HTTPException(status_code=404, detail="No transcription available")
            transcription = _last_transcription_data
            video_hash = transcription.get('video_hash')

        # Get segments
        segments = transcription.get('transcription', {}).get('segments', [])
        if not segments:
            raise HTTPException(status_code=400, detail="No segments found in transcription")

        # Index in vector database (run in executor to avoid blocking)
        print(f"Indexing video {video_hash} with {len(segments)} segments...")
        num_chunks = await _run_in_executor(vector_store.index_transcription, video_hash, segments)

        # Also index audio events if segments contain audio analysis data
        audio_indexed = 0
        try:
            audio_indexed = await _run_in_executor(vector_store.index_audio_events, video_hash, segments)
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
    from services.usage_meter import record_chat_message
    check_can_chat(getattr(request.state, "profile", None))
    _quota_user_id = (request.state.profile or {}).get("id") if hasattr(request.state, "profile") else None

    # Guard: wait for models to finish preloading on cold start
    from model_preloader import models_ready, wait_for_models
    if not models_ready():
        if not wait_for_models(timeout=5.0):
            return {
                "answer": "The server just started and is still loading AI models. Please try again in about 30 seconds.",
                "sources": [],
                "provider_used": "none",
            }

    try:
        question = chat_request.question
        video_hash = chat_request.video_hash
        provider_name = chat_request.provider
        n_results = chat_request.n_results or 8
        include_visuals = chat_request.include_visuals or False
        n_images = chat_request.n_images or 4
        custom_instructions = chat_request.custom_instructions
        user_visual_terms, user_visual_phrases = _user_visual_search_config(
            getattr(request.state, "profile", None)
        )

        if not question:
            raise HTTPException(status_code=400, detail="Question is required")

        retrieval_question = _resolve_contextual_visual_question(
            question,
            chat_request.conversation_history,
            user_visual_terms,
            user_visual_phrases,
            video_hash,
        )

        # Get video_hash from last transcription if not provided
        if not video_hash:
            global _last_transcription_data
            if not _last_transcription_data:
                raise HTTPException(status_code=404, detail="No video available for chat")
            video_hash = _last_transcription_data.get('video_hash')

        # Check if video is indexed
        if not vector_store.collection_exists(video_hash):
            # Auto-index if not already indexed
            transcription = get_transcription_from_any_source(video_hash)
            if transcription:
                segments = transcription.get('transcription', {}).get('segments', [])
                print(f"Auto-indexing video {video_hash}...")
                await _run_in_executor(vector_store.index_transcription, video_hash, segments)
            else:
                raise HTTPException(
                    status_code=404,
                    detail="Video not indexed. Please index it first using /api/index_video/"
                )

        comparison_intent = _detect_comparison_intent(question, video_hash)
        if comparison_intent:
            comparison_request = chat_request.copy(update={"video_hash": video_hash})
            response = await _handle_person_comparison(request, comparison_request, comparison_intent)
            try:
                record_chat_message(_quota_user_id, llm_tokens=0)
            except Exception as _meter_err:
                print(f"[chat] meter failed: {_meter_err}")
            return response

        # Retrieve text context
        search_results, context, sources = await _retrieve_text_context(video_hash, retrieval_question, n_results)

        if not search_results and not include_visuals:
            return {
                "answer": "I couldn't find relevant information in the video to answer your question.",
                "sources": [],
                "provider_used": provider_name or "none",
                "video_hash": video_hash
            }

        # Retrieve visual context
        image_paths = []
        visual_context = ""
        visual_sources = []
        visual_query_used = None
        visual_query_variants = []
        image_results = []

        if include_visuals:
            vis = await _retrieve_visual_context(
                video_hash,
                retrieval_question,
                n_images,
                user_visual_terms=user_visual_terms,
                user_visual_phrases=user_visual_phrases,
            )
            if vis.get("images_indexed"):
                image_paths = vis["image_paths"]
                visual_context = vis["visual_context"]
                visual_sources = vis["visual_sources"]
                visual_query_used = vis["visual_query_used"]
                visual_query_variants = vis.get("visual_query_variants", [])
                image_results = vis["image_results"]

        # Retrieve audio context
        audio_context, audio_sources, _ = await _retrieve_audio_context(
            video_hash, retrieval_question, search_results, image_results
        )

        # Combine text, visual, and audio sources
        all_sources = sources + visual_sources + audio_sources
        if not all_sources:
            return {
                "answer": "I couldn't find relevant information in the video to answer your question.",
                "sources": [],
                "provider_used": provider_name or "none",
                "video_hash": video_hash
            }

        # Get LLM provider and generate response
        try:
            provider = await _get_chat_provider(request, provider_name)
            provider_supports_vision = provider.supports_vision()

            if include_visuals and image_paths and not provider_supports_vision:
                fallback_visual_context = await _generate_visual_observations_with_fallback(
                    request=request,
                    question=question,
                    image_paths=image_paths,
                    visual_context=visual_context,
                    final_provider_name=provider_name,
                )
                if fallback_visual_context:
                    visual_context = fallback_visual_context

            # Build prompt after provider resolution so non-vision providers
            # receive vision observations as text instead of image payloads.
            has_images = include_visuals and bool(image_paths) and provider_supports_vision
            messages = _build_chat_messages(
                question=question,
                context=context,
                visual_context=visual_context,
                audio_context=audio_context,
                has_images=has_images,
                custom_instructions=custom_instructions,
                conversation_history=chat_request.conversation_history,
            )

            if include_visuals and image_paths and provider_supports_vision:
                print(f"Using vision-capable model for analysis with {len(image_paths)} images")
                answer = await provider.generate_with_images(
                    messages,
                    image_paths,
                    temperature=0.7,
                    max_tokens=2000
                )
            else:
                if include_visuals and image_paths and not provider_supports_vision:
                    print(f"Provider {provider_name} is text-only; using text prompt with vision fallback observations when available.")
                answer = await provider.generate(messages, temperature=0.7, max_tokens=2000)
        except Exception as e:
            print(f"[chat] provider generation failed: {type(e).__name__}: {e}")
            raise HTTPException(
                status_code=_provider_http_status(e),
                detail=_provider_error_message(e, provider_name),
                headers={"X-LLM-Error-Code": _classify_provider_error(e)},
            )

        from config import settings
        if settings.CHAT_DEBUG_LOGS:
            print(f"DEBUG: text sources: {len(sources)}, visual sources: {len(visual_sources)}, audio sources: {len(audio_sources)}")
            if audio_sources:
                print(f"DEBUG: First audio source: {audio_sources[0]}")

        response = {
            "answer": answer,
            "sources": all_sources,
            "provider_used": provider_name or llm_manager.default_provider,
            "video_hash": video_hash
        }

        if visual_query_used:
            response["visual_query_used"] = visual_query_used
        if visual_query_variants:
            response["visual_query_variants"] = visual_query_variants

        # Meter (best-effort; never blocks the response)
        try:
            record_chat_message(_quota_user_id, llm_tokens=0)
        except Exception as _meter_err:
            print(f"[chat] meter failed: {_meter_err}")

        return response

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
            )
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
      done    - final completion signal
      error   - pipeline failure
    """
    if not LLM_AVAILABLE:
        raise HTTPException(status_code=503, detail="LLM features not available")

    # Plan gate: free tier has chat disabled; admins always pass
    from middleware.quota import check_can_chat
    from services.usage_meter import record_chat_message
    check_can_chat(getattr(request.state, "profile", None))
    _stream_user_id = (request.state.profile or {}).get("id") if hasattr(request.state, "profile") else None

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
            question = chat_request.question
            video_hash = chat_request.video_hash
            provider_name = chat_request.provider
            n_results = chat_request.n_results or 8
            include_visuals = chat_request.include_visuals or False
            n_images = chat_request.n_images or 4
            custom_instructions = chat_request.custom_instructions
            user_visual_terms, user_visual_phrases = _user_visual_search_config(
                getattr(request.state, "profile", None)
            )

            if not question:
                yield _sse({"type": "error", "message": "Question is required"})
                return

            retrieval_question = _resolve_contextual_visual_question(
                question,
                chat_request.conversation_history,
                user_visual_terms,
                user_visual_phrases,
                video_hash,
            )

            # Resolve video_hash
            if not video_hash:
                global _last_transcription_data
                if not _last_transcription_data:
                    yield _sse({"type": "error", "message": "No video available for chat"})
                    return
                video_hash = _last_transcription_data.get('video_hash')

            # Auto-index check
            if not vector_store.collection_exists(video_hash):
                transcription = get_transcription_from_any_source(video_hash)
                if transcription:
                    segments = transcription.get('transcription', {}).get('segments', [])
                    print(f"Auto-indexing video {video_hash}...")
                    await _run_in_executor(vector_store.index_transcription, video_hash, segments)
                else:
                    yield _sse({"type": "error", "message": "Video not indexed. Please index it first using /api/index_video/"})
                    return

            comparison_intent = _detect_comparison_intent(question, video_hash)
            if comparison_intent:
                yield _sse({"type": "phase", "phase": "comparing", "label": "Comparing person states"})
                comparison_request = chat_request.copy(update={"video_hash": video_hash})
                response = await _handle_person_comparison(request, comparison_request, comparison_intent)
                yield _sse({
                    "type": "sources",
                    "sources": response.get("sources") or [],
                    "visual_query_used": None,
                    "visual_query_variants": [],
                })
                yield _sse({"type": "token", "content": response.get("answer", "")})
                yield _sse({
                    "type": "done",
                    "provider_used": response.get("provider_used") or provider_name or llm_manager.default_provider,
                    "video_hash": video_hash,
                })
                try:
                    record_chat_message(_stream_user_id, llm_tokens=0)
                except Exception as _meter_err:
                    print(f"[chat/stream] meter failed: {_meter_err}")
                return

            # Phase: text search
            yield _sse({"type": "phase", "phase": "searching", "label": "Searching transcript"})

            search_results, context, sources = await _retrieve_text_context(video_hash, retrieval_question, n_results)

            if not search_results and not include_visuals:
                yield _sse({"type": "sources", "sources": [], "visual_query_used": None, "visual_query_variants": []})
                yield _sse({"type": "token", "content": "I couldn't find relevant information in the video to answer your question."})
                yield _sse({"type": "done", "provider_used": provider_name or "none", "video_hash": video_hash})
                return

            # Visual retrieval
            image_paths = []
            visual_context = ""
            visual_sources = []
            visual_query_used = None
            visual_query_variants = []
            image_results = []

            if include_visuals:
                # The phase_cb emits SSE events from within the helper at
                # the right moment. yield is not available inside a nested
                # function, so we write to a shared list and drain it after
                # the helper returns.
                _pending_events: list = []

                async def _phase_cb(phase: str, label: str) -> None:
                    _pending_events.append(_sse({"type": "phase", "phase": phase, "label": label}))

                vis = await _retrieve_visual_context(
                    video_hash,
                    retrieval_question,
                    n_images,
                    user_visual_terms=user_visual_terms,
                    user_visual_phrases=user_visual_phrases,
                    phase_cb=_phase_cb,
                )

                # Drain any phase events that were queued during the helper call
                for evt in _pending_events:
                    yield evt

                if vis.get("images_indexed"):
                    image_paths = vis["image_paths"]
                    visual_context = vis["visual_context"]
                    visual_sources = vis["visual_sources"]
                    visual_query_used = vis["visual_query_used"]
                    visual_query_variants = vis.get("visual_query_variants", [])
                    image_results = vis["image_results"]

            # Audio context
            audio_indexed = vector_store.audio_collection_exists(video_hash)
            if audio_indexed:
                yield _sse({"type": "phase", "phase": "analyzing_audio", "label": "Scanning audio events"})

            audio_context, audio_sources, _ = await _retrieve_audio_context(
                video_hash, retrieval_question, search_results, image_results
            )

            # Emit sources event
            all_sources = sources + visual_sources + audio_sources
            if not all_sources:
                yield _sse({
                    "type": "sources",
                    "sources": [],
                    "visual_query_used": visual_query_used,
                    "visual_query_variants": visual_query_variants,
                })
                yield _sse({"type": "token", "content": "I couldn't find relevant information in the video to answer your question."})
                yield _sse({"type": "done", "provider_used": provider_name or "none", "video_hash": video_hash})
                return

            provider = await _get_chat_provider(request, provider_name)
            provider_supports_vision = provider.supports_vision()

            if include_visuals and image_paths and not provider_supports_vision:
                yield _sse({"type": "phase", "phase": "analyzing_visuals", "label": "Inspecting screenshots"})
                fallback_task = asyncio.create_task(
                    _generate_visual_observations_with_fallback(
                        request=request,
                        question=question,
                        image_paths=image_paths,
                        visual_context=visual_context,
                        final_provider_name=provider_name,
                    )
                )
                while not fallback_task.done():
                    try:
                        await asyncio.wait_for(asyncio.shield(fallback_task), timeout=5.0)
                    except asyncio.TimeoutError:
                        yield _sse({
                            "type": "phase",
                            "phase": "analyzing_visuals",
                            "label": "Inspecting screenshots",
                        })
                fallback_visual_context = fallback_task.result()
                if fallback_visual_context:
                    visual_context = fallback_visual_context

            yield _sse({
                "type": "sources",
                "sources": all_sources,
                "visual_query_used": visual_query_used,
                "visual_query_variants": visual_query_variants,
            })

            # Build messages after provider resolution so non-vision providers
            # receive vision observations as text instead of image payloads.
            has_images = include_visuals and bool(image_paths) and provider_supports_vision
            messages = _build_chat_messages(
                question=question,
                context=context,
                visual_context=visual_context,
                audio_context=audio_context,
                has_images=has_images,
                custom_instructions=custom_instructions,
                conversation_history=chat_request.conversation_history,
            )

            # LLM generation
            yield _sse({"type": "phase", "phase": "generating", "label": "Writing answer"})

            if include_visuals and image_paths and provider_supports_vision:
                print(f"Using vision-capable model for analysis with {len(image_paths)} images")
                # Vision providers are non-streaming, so the call blocks for
                # ~10s with no bytes on the SSE socket. Intermediate proxies
                # can drop idle connections and lose the big token event that
                # follows. Run the call as a task and emit a lightweight phase
                # heartbeat every few seconds to keep the socket warm.
                vision_task = asyncio.create_task(
                    provider.generate_with_images(
                        messages,
                        image_paths,
                        temperature=0.7,
                        max_tokens=2000,
                    )
                )
                while not vision_task.done():
                    try:
                        await asyncio.wait_for(
                            asyncio.shield(vision_task), timeout=5.0
                        )
                    except asyncio.TimeoutError:
                        yield _sse({
                            "type": "phase",
                            "phase": "generating",
                            "label": "Writing answer",
                        })
                    except BaseException as e:
                        print(f"[chat/stream] vision task interrupted before completion: {type(e).__name__}: {e}")
                        break
                vision_err: Optional[Exception] = None
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
                    yield _sse({"type": "token", "content": answer})
                elif vision_err or text_err:
                    # Both paths failed — surface the underlying provider error
                    # instead of pretending the model returned nothing.
                    underlying = text_err or vision_err
                    yield _sse({
                        "type": "error",
                        "message": _provider_error_message(underlying, provider_name),
                        "detail": str(underlying),
                        "code": _classify_provider_error(underlying),
                    })
                else:
                    yield _sse({
                        "type": "token",
                        "content": "The model did not return an answer for this query. Try rephrasing, or turn off visual analysis."
                    })
            else:
                if include_visuals and image_paths and not provider_supports_vision:
                    print(f"Provider {provider_name} is text-only; using text prompt with vision fallback observations when available.")
                streamed_chunks: list[str] = []
                chunk_count = 0
                stream_err: Optional[Exception] = None
                gen_err: Optional[Exception] = None
                try:
                    async for chunk in provider.generate_stream(messages, temperature=0.7, max_tokens=2000):
                        chunk_count += 1
                        streamed_chunks.append(chunk)
                        yield _sse({"type": "token", "content": chunk})
                except Exception as e:
                    stream_err = e
                    print(f"[chat/stream] generate_stream raised: {e}")
                total_streamed = "".join(streamed_chunks).strip()
                print(
                    f"[chat/stream] provider={provider_name or llm_manager.default_provider} "
                    f"chunks={chunk_count} total_chars={len(total_streamed)}"
                )
                # Fallback: some providers (e.g. xAI reasoning models) don't
                # emit delta.content chunks. If streaming produced little or
                # no output, run the non-streaming call and emit the full
                # answer as one token event.
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
                        yield _sse({"type": "reset"})
                    if answer:
                        yield _sse({"type": "token", "content": answer})
                    elif stream_err or gen_err:
                        underlying = gen_err or stream_err
                        yield _sse({
                            "type": "error",
                            "message": _provider_error_message(underlying, provider_name),
                            "detail": str(underlying),
                            "code": _classify_provider_error(underlying),
                        })

            yield _sse({
                "type": "done",
                "provider_used": provider_name or llm_manager.default_provider,
                "video_hash": video_hash
            })

            # Meter the chat message (best-effort; never breaks the stream)
            try:
                record_chat_message(_stream_user_id, llm_tokens=0)
            except Exception as _meter_err:
                print(f"[chat/stream] meter failed: {_meter_err}")

        except Exception as e:
            print(f"Error in streaming chat: {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()
            yield _sse({
                "type": "error",
                "message": _provider_error_message(e, chat_request.provider),
                "detail": f"{type(e).__name__}: {e}",
                "code": _classify_provider_error(e),
            })

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

        user_id = None
        if hasattr(request.state, "profile") and request.state.profile:
            user_id = request.state.profile.get("id")
        if not user_id and hasattr(request.state, "user") and request.state.user:
            user_id = request.state.user.get("id")

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
            if key_provider in saved_key_providers:
                provider["available"] = True
        return {
            "providers": providers,
            "default": llm_manager.default_provider
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


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


def _run_index_images_background(video_hash: str, segments: list, force_reindex: bool, user_id, use_supabase: bool):
    """Background worker: run CLIP indexing synchronously (called from BackgroundTasks)."""
    try:
        storage_type = "Supabase pgvector" if use_supabase else "ChromaDB"
        print(f"[BG] Indexing images for video {video_hash} from {len(segments)} segments using {storage_type}...")
        if use_supabase:
            num = image_embedding_service.index_video_images(video_hash, segments, force_reindex=force_reindex, user_id=user_id)
        else:
            num = vector_store.index_video_images(video_hash, segments, force_reindex=force_reindex)
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
        # Get transcription data from any available source (legacy DB or Supabase jobs)
        if video_hash:
            transcription = get_transcription_from_any_source(video_hash)
            if not transcription:
                raise HTTPException(status_code=404, detail="Transcription not found")
        else:
            # Use last transcription
            global _last_transcription_data
            if not _last_transcription_data:
                raise HTTPException(status_code=404, detail="No transcription available")
            transcription = _last_transcription_data
            video_hash = transcription.get('video_hash')

        # Get segments
        segments = transcription.get('transcription', {}).get('segments', [])
        if not segments:
            raise HTTPException(status_code=400, detail="No segments found in transcription")

        use_supabase = _use_supabase_for_images()
        storage_type = "Supabase pgvector" if use_supabase else "ChromaDB"
        user_id = transcription.get('user_id')

        # Schedule CLIP indexing as a background task so the request returns immediately
        background_tasks.add_task(
            _run_index_images_background, video_hash, segments, force_reindex, user_id, use_supabase
        )

        return IndexImagesResponse(
            success=True,
            video_hash=video_hash,
            images_indexed=0,
            message=f"Re-indexing started in background ({len(segments)} segments, storage: {storage_type}). Visual search will update shortly."
        )
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error starting image indexing: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Failed to start image indexing: {str(e)}")


@router.post(
    "/search_images/",
    response_model=SearchImagesResponse,
    summary="Search video images",
    description="Search for video screenshots using text queries via CLIP embeddings",
    responses={
        503: {"model": ErrorResponse, "description": "LLM features not available"},
        404: {"model": ErrorResponse, "description": "Video not found or images not indexed"}
    }
)
@require_auth
async def search_video_images(request: Request, search_request: SearchImagesRequest) -> SearchImagesResponse:
    """
    Search for video screenshots using text queries via CLIP embeddings

    This endpoint allows you to search for visual moments in a video by describing what you're looking for.
    For example: "person pointing at screen", "whiteboard with equations", "close-up of face", etc.
    """
    if not LLM_AVAILABLE:
        raise HTTPException(status_code=503, detail="LLM features not available")

    try:
        query = search_request.query
        video_hash = search_request.video_hash
        n_results = search_request.n_results or 5

        if not query:
            raise HTTPException(status_code=400, detail="Query is required")

        # Get video_hash from last transcription if not provided
        if not video_hash:
            global _last_transcription_data
            if not _last_transcription_data:
                raise HTTPException(status_code=404, detail="No video available for image search")
            video_hash = _last_transcription_data.get('video_hash')

        # Determine which service to use
        use_supabase = _use_supabase_for_images()

        # Check if images are indexed in the appropriate store
        if use_supabase:
            images_exist = image_embedding_service.image_collection_exists(video_hash)
        else:
            images_exist = vector_store.image_collection_exists(video_hash)

        if not images_exist:
            raise HTTPException(
                status_code=404,
                detail="Images not indexed for this video. Please index images first using /api/index_images/"
            )

        # Check if the query mentions a specific speaker
        speaker_filter = _extract_speaker_from_query(query, video_hash)

        # Search for images using appropriate service
        # Run in executor - CLIP encoding is CPU/GPU intensive
        storage_type = "Supabase" if use_supabase else "ChromaDB"
        print(f"Searching images for query: {query} (using {storage_type})")

        if use_supabase:
            search_results = await _run_in_executor(
                image_embedding_service.search_images,
                video_hash,
                query,
                n_results=n_results,
                speaker_filter=speaker_filter
            )
        else:
            search_results = await _run_in_executor(
                vector_store.search_images,
                video_hash,
                query,
                n_results=n_results,
                speaker_filter=speaker_filter
            )

        # Format results (handle both Supabase and ChromaDB response formats)
        formatted_results = []
        for result in search_results:
            metadata = result['metadata']
            # Supabase uses 'screenshot_url', ChromaDB uses 'screenshot_path'
            screenshot = result.get('screenshot_url') or result.get('screenshot_path')
            # Supabase uses 'similarity' (0-1), ChromaDB uses 'distance' (lower = better)
            score = result.get('similarity') or result.get('distance')
            formatted_results.append(
                ImageSearchResult(
                    screenshot_path=screenshot,
                    segment_id=metadata['segment_id'],
                    start=metadata['start'],
                    end=metadata['end'],
                    speaker=metadata['speaker'],
                    distance=score
                )
            )

        return SearchImagesResponse(
            results=formatted_results,
            video_hash=video_hash,
            query=query
        )

    except HTTPException:
        raise
    except Exception as e:
        print(f"Error searching images: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Image search failed: {str(e)}")
