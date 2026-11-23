"""LLM provider resolution, saved-key lookup and provider error mapping for chat."""
from typing import List, Optional
from fastapi import HTTPException, Request
from services.model_catalog import ReasoningEffort
from services.provider_http import VisionTimeoutError, is_credit_exhausted

# Import LLM module
try:
    from llm_providers import llm_manager
    LLM_AVAILABLE = True
except ImportError as e:
    print(f"Warning: LLM features not available: {str(e)}")
    LLM_AVAILABLE = False


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
    if is_credit_exhausted(msg):
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
        if isinstance(err, VisionTimeoutError):
            return (
                f"{provider_label} took too long to answer. Visual answers with several images "
                "can be slow; retry or pick a faster model."
            )
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
    if provider_name in ("grok", "xai"):
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


def _request_user_id(request: Request) -> Optional[str]:
    user_id = None
    if hasattr(request.state, "profile") and request.state.profile:
        user_id = request.state.profile.get("id")
    if not user_id and hasattr(request.state, "user") and request.state.user:
        user_id = request.state.user.get("id")
    return user_id


async def _get_chat_provider(
    request: Request,
    provider_name: Optional[str],
    model: Optional[str] = None,
    reasoning_effort: Optional[ReasoningEffort] = None,
):
    """Resolve an LLM provider using the user's validated saved key.

    `model` overrides the provider's default for this request only.
    """
    provider_name = provider_name or llm_manager.default_provider
    saved_key = await _get_saved_provider_key(_request_user_id(request), provider_name)
    if not saved_key:
        raise HTTPException(status_code=400, detail=f"No valid API key saved for {provider_name}. Add one in Settings.")
    try:
        return llm_manager.get_provider(
            provider_name, api_key_override=saved_key,
            model_override=model, reasoning_effort=reasoning_effort,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


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
