"""Fetch the chat models a provider currently offers, so model IDs are not hardcoded."""

import hashlib
import os
import time
from typing import Dict, List, Optional, Tuple

import httpx

from services.provider_http import provider_error_detail

CACHE_TTL_SECONDS = 300
FAILURE_TTL_SECONDS = 60
# Key-level errors: another endpoint with the same key cannot succeed.
_KEY_ERROR_STATUSES = (401, 402, 403, 429)

# Tried in order; xAI's language-models endpoint lists only chat models.
_ENDPOINTS = {
    "openai": ["https://api.openai.com/v1/models"],
    "anthropic": ["https://api.anthropic.com/v1/models?limit=100"],
    "xai": ["https://api.x.ai/v1/language-models", "https://api.x.ai/v1/models"],
    "groq": ["https://api.groq.com/openai/v1/models"],
    "deepseek": [os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/") + "/models"],
}


class ModelListError(Exception):
    """Upstream refused or failed the listing; the message carries the provider's own reason."""


# Listings mix in embeddings, speech, image and moderation models that cannot chat.
_NON_CHAT_MARKERS = (
    "embed", "whisper", "tts", "transcribe", "dall-e", "image", "moderation",
    "realtime", "audio", "guard", "search-preview", "davinci", "babbage",
)

_cache: Dict[Tuple[str, str], Tuple[float, List[str]]] = {}
_failures: Dict[Tuple[str, str], Tuple[float, str]] = {}


def _headers(provider: str, api_key: str) -> Dict[str, str]:
    if provider == "anthropic":
        return {"x-api-key": api_key, "anthropic-version": "2023-06-01"}
    return {"Authorization": f"Bearer {api_key}"}


def filter_chat_models(provider: str, ids: List[str]) -> List[str]:
    out = []
    for model_id in set(ids):
        lowered = model_id.lower()
        if any(marker in lowered for marker in _NON_CHAT_MARKERS):
            continue
        if provider == "openai" and not lowered.startswith(("gpt-", "o1", "o3", "o4", "chatgpt-")):
            continue
        out.append(model_id)
    return sorted(out)


async def list_models(provider: str, api_key: str, timeout: float = 10.0) -> List[str]:
    """Return chat-capable model IDs, cached briefly. Raises on upstream failure."""
    urls = _ENDPOINTS.get(provider)
    if not urls or not api_key:
        raise ValueError(f"No model listing for provider '{provider}'")

    # Hash the key so cached entries are per-account without storing the secret.
    cache_key = (provider, hashlib.sha256(api_key.encode()).hexdigest())
    now = time.monotonic()
    cached = _cache.get(cache_key)
    if cached and now - cached[0] < CACHE_TTL_SECONDS:
        return cached[1]
    failed = _failures.get(cache_key)
    if failed and now - failed[0] < FAILURE_TTL_SECONDS:
        # A key that was just refused (e.g. out of credits) would be refused again.
        raise ModelListError(failed[1])

    message = "Provider returned no models"
    async with httpx.AsyncClient(timeout=timeout) as client:
        for url in urls:
            response = await client.get(url, headers=_headers(provider, api_key))
            if response.is_error:
                message = f"HTTP {response.status_code}: {provider_error_detail(response)}"
                if response.status_code in _KEY_ERROR_STATUSES:
                    break
                continue
            payload = response.json()
            ids = [m["id"] for m in (payload.get("data") or payload.get("models") or []) if m.get("id")]
            if ids:
                models = filter_chat_models(provider, ids)
                # Evict on write so rotated keys cannot accumulate forever.
                for store, ttl in ((_cache, CACHE_TTL_SECONDS), (_failures, FAILURE_TTL_SECONDS)):
                    for key in [k for k, (stamp, _) in store.items() if now - stamp >= ttl]:
                        del store[key]
                _cache[cache_key] = (now, models)
                _failures.pop(cache_key, None)
                return models

    _failures[cache_key] = (now, message)
    raise ModelListError(message)
