"""
Server-side feature flags backed by Flagsmith.

The backend is the only Flagsmith client: the browser reads flags from
GET /api/features, so a hidden feature cannot be re-enabled from DevTools.
Unknown flags and failures before the first successful fetch mean "disabled".
"""
import logging
import threading
import time
from typing import Dict, Optional

from fastapi import HTTPException

from config import settings

logger = logging.getLogger(__name__)

# Only these names are evaluated or exposed to clients; anything else is off.
KNOWN_FLAGS = ("chapters", "summary")

INIT_RETRY_COOLDOWN_SECONDS = 300
FLAG_CACHE_SECONDS = 900

_client = None
_client_lock = threading.Lock()
_cached_flags: Optional[Dict[str, bool]] = None
_next_refresh_at = 0.0


def all_flags() -> Dict[str, bool]:
    global _client, _cached_flags, _next_refresh_at
    if not settings.FLAGSMITH_SERVER_KEY:
        return dict.fromkeys(KNOWN_FLAGS, False)
    with _client_lock:
        if time.monotonic() >= _next_refresh_at:
            try:
                if _client is None:
                    from flagsmith import Flagsmith

                    _client = Flagsmith(environment_key=settings.FLAGSMITH_SERVER_KEY)
                flags = _client.get_environment_flags()
                _cached_flags = {name: bool(flags.is_feature_enabled(name)) for name in KNOWN_FLAGS}
                _next_refresh_at = time.monotonic() + FLAG_CACHE_SECONDS
            except Exception:
                _next_refresh_at = time.monotonic() + INIT_RETRY_COOLDOWN_SECONDS
                logger.warning(
                    "Flagsmith refresh failed; retrying on demand after %ss",
                    INIT_RETRY_COOLDOWN_SECONDS,
                    exc_info=True,
                )
        return dict(_cached_flags) if _cached_flags is not None else dict.fromkeys(KNOWN_FLAGS, False)


def is_enabled(name: str) -> bool:
    if name not in KNOWN_FLAGS:
        return False
    return all_flags()[name]


def require_feature(name: str):
    """FastAPI dependency: 404 (not 403) so a disabled feature looks nonexistent."""
    if name not in KNOWN_FLAGS:
        raise ValueError(f"Unknown feature flag {name!r}; add it to KNOWN_FLAGS")

    def dependency() -> None:
        if not is_enabled(name):
            raise HTTPException(status_code=404, detail="Not Found")

    return dependency


def _reset_for_tests(client: Optional[object] = None) -> None:
    global _client, _cached_flags, _next_refresh_at
    _client = client
    _cached_flags = None
    _next_refresh_at = 0.0
