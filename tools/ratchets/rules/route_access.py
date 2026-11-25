"""Ratchet route-access: every route of the app is access-controlled, or explicitly classified.

A route is protected when its registered endpoint is the wrapper of `require_auth` or `require_admin`
(backend/middleware/auth.py), identified by the wrapper's code object, not by a name: `functools.wraps` copies
names. Every other route (a public auth flow, a per-job token, a signed webhook, framework docs) is a violation
unless baseline.json lists its `METHOD path` with a class prefix and a reason. test_route_access.py then checks
each class's behaviour, so the classification is proven, not trusted.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
CLASSES = ("public", "job-token", "job-token-or-owner", "webhook", "framework")


def app():
    if str(ROOT / "backend") not in sys.path:
        sys.path.insert(0, str(ROOT / "backend"))
    import main
    return main.app


def protection_codes():
    import middleware.auth as auth

    def handler(request):
        return None

    return {auth.require_auth(handler).__code__: "user", auth.require_admin(handler).__code__: "admin"}


def routes(application=None):
    """[(fingerprint, class or None, route)] for every route and method; class None = not decorator-protected."""
    application = application or app()
    codes = protection_codes()
    out = []
    for r in application.routes:
        endpoint = getattr(r, "endpoint", None)
        kind = codes.get(getattr(endpoint, "__code__", None))
        for method in sorted(getattr(r, "methods", None) or {"MOUNT"}):
            if method != "HEAD":
                out.append((f"{method} {r.path}", kind, r))
    return out


def collect(root=ROOT, application=None):
    return {fp: f"{getattr(r.endpoint, '__module__', '?')}.{getattr(r.endpoint, '__name__', '?')}"
            for fp, kind, r in routes(application) if kind is None}
