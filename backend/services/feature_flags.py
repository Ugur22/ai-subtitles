"""
Server-side feature flags backed by Flagsmith.

The backend is the only Flagsmith client: the browser reads flags from
GET /api/features, so a hidden feature cannot be re-enabled from DevTools.
Every failure path (no key, SDK missing, Flagsmith down, unknown flag) means
"disabled".
"""
import logging
import threading
from typing import Dict, Optional

from fastapi import HTTPException

from config import settings

logger = logging.getLogger(__name__)

# Only these names are evaluated or exposed to clients; anything else is off.
KNOWN_FLAGS = ("chapters", "summary")

_client = None
_client_lock = threading.Lock()
_init_failed = False


def _get_client():
    global _client, _init_failed
    if _client is not None or _init_failed or not settings.FLAGSMITH_SERVER_KEY:
        return _client
    with _client_lock:
        if _client is None and not _init_failed:
            try:
                # Imported lazily so a missing SDK disables flags instead of crashing startup.
                from flagsmith import Flagsmith

                # Local evaluation polls the environment document once a minute per
                # instance instead of one API call per request (free tier: 50k/month).
                _client = Flagsmith(
                    environment_key=settings.FLAGSMITH_SERVER_KEY,
                    enable_local_evaluation=True,
                    environment_refresh_interval_seconds=60,
                )
            except Exception:
                _init_failed = True
                logger.exception("Flagsmith init failed; all feature flags are disabled")
    return _client


def is_enabled(name: str) -> bool:
    if name not in KNOWN_FLAGS:
        return False
    client = _get_client()
    if client is None:
        return False
    try:
        return bool(client.get_environment_flags().is_feature_enabled(name))
    except Exception:
        logger.warning("Flagsmith evaluation failed for %r; treating as disabled", name, exc_info=True)
        return False


def all_flags() -> Dict[str, bool]:
    return {name: is_enabled(name) for name in KNOWN_FLAGS}


def require_feature(name: str):
    """FastAPI dependency: 404 (not 403) so a disabled feature looks nonexistent."""
    if name not in KNOWN_FLAGS:
        raise ValueError(f"Unknown feature flag {name!r}; add it to KNOWN_FLAGS")

    def dependency() -> None:
        if not is_enabled(name):
            raise HTTPException(status_code=404, detail="Not Found")

    return dependency


def _reset_for_tests(client: Optional[object] = None) -> None:
    global _client, _init_failed
    _client = client
    _init_failed = False
