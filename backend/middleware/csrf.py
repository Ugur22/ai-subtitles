"""Reject cross-site state-changing requests that would carry the auth cookie."""
from typing import Iterable, Optional
from urllib.parse import urlsplit

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

_UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def _normalize(origin: str) -> str:
    return origin.strip().rstrip("/").lower()


class CSRFProtectionMiddleware(BaseHTTPMiddleware):
    """
    The auth cookie is SameSite=None because the frontend lives on another site,
    so browsers attach it to requests made by any page. CORS only decides who may
    read a response, not whether the request is processed. For unsafe methods:

    - An Origin header that is not in the allow-list, and is not this server's own
      host, is refused. Browsers always send Origin on cross-origin requests with
      these methods; non-browser clients send none and are unaffected.
    - A request body without a Content-Type is refused. FastAPI parses such a body
      as JSON, which let a cross-site page send a "simple" request that needs no
      CORS preflight.
    """

    def __init__(self, app, allowed_origins: Optional[Iterable[str]] = None):
        super().__init__(app)
        self.allowed_origins = {_normalize(origin) for origin in allowed_origins or []}

    async def dispatch(self, request, call_next):
        if request.method in _UNSAFE_METHODS:
            origin = request.headers.get("origin")
            if origin is not None and not self._origin_allowed(request, origin):
                return JSONResponse(status_code=403, content={"detail": "Origin not allowed"})
            if self._has_body(request) and not request.headers.get("content-type"):
                return JSONResponse(status_code=415, content={"detail": "Content-Type header is required"})
        return await call_next(request)

    def _origin_allowed(self, request, origin: str) -> bool:
        if _normalize(origin) in self.allowed_origins:
            return True
        own_host = request.headers.get("host", "").lower()
        return bool(own_host) and urlsplit(origin).netloc.lower() == own_host

    @staticmethod
    def _has_body(request) -> bool:
        length = request.headers.get("content-length")
        if length is not None:
            return length.strip() not in ("", "0")
        return "transfer-encoding" in request.headers
