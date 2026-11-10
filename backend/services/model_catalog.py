"""Fetch the chat models a provider currently offers, so model IDs are not hardcoded."""

import hashlib
import os
import time
from typing import Dict, List, Optional, Tuple

import httpx

CACHE_TTL_SECONDS = 300

# provider -> (models URL, extra headers builder)
_ENDPOINTS = {
    "openai": "https://api.openai.com/v1/models",
    "anthropic": "https://api.anthropic.com/v1/models?limit=100",
    "xai": "https://api.x.ai/v1/models",
    "groq": "https://api.groq.com/openai/v1/models",
    "deepseek": None,  # base URL is env-configurable, resolved in _url()
}

# Listings mix in embeddings, speech, image and moderation models that cannot chat.
_NON_CHAT_MARKERS = (
    "embed", "whisper", "tts", "transcribe", "dall-e", "image", "moderation",
    "realtime", "audio", "guard", "search-preview", "davinci", "babbage",
)

_cache: Dict[Tuple[str, str], Tuple[float, List[str]]] = {}


def _url(provider: str) -> Optional[str]:
    if provider == "deepseek":
        return os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/") + "/models"
    return _ENDPOINTS.get(provider)


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
    url = _url(provider)
    if not url or not api_key:
        raise ValueError(f"No model listing for provider '{provider}'")

    # Hash the key so cached entries are per-account without storing the secret.
    cache_key = (provider, hashlib.sha256(api_key.encode()).hexdigest())
    cached = _cache.get(cache_key)
    if cached and time.monotonic() - cached[0] < CACHE_TTL_SECONDS:
        return cached[1]

    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.get(url, headers=_headers(provider, api_key))
    response.raise_for_status()
    ids = [m["id"] for m in response.json().get("data", []) if m.get("id")]
    models = filter_chat_models(provider, ids)
    _cache[cache_key] = (time.monotonic(), models)
    return models
