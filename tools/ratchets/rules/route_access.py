"""Protected endpoints are identified by the wrapper's code object, not by a name: `functools.wraps` copies names."""

import functools
import sys
from pathlib import Path
from typing import NamedTuple

ROOT = Path(__file__).resolve().parents[3]
CLASSES = ("public", "job-token", "job-token-or-owner", "webhook", "framework")


def app():
    if str(ROOT / "backend") not in sys.path:
        sys.path.insert(0, str(ROOT / "backend"))
    import main
    return main.app


def entry_class(why):
    return why.partition(":")[0].strip()


def reason_problem(why):
    if entry_class(why) not in CLASSES:
        return f"must start with one of {', '.join(CLASSES)} and a colon"
    if len(why.partition(":")[2].strip()) < 10:
        return "needs a reason after the class"
    return None


@functools.lru_cache(maxsize=None)
def protection_codes():
    import middleware.auth as auth

    def handler(request):
        return None

    return {auth.require_auth(handler).__code__: "user", auth.require_admin(handler).__code__: "admin"}


class Route(NamedTuple):
    fingerprint: str
    protection: object  # "user", "admin", or None when no decorator protects it
    route: object


def routes(application=None):
    application = application or app()
    codes = protection_codes()
    out = []
    for r in application.routes:
        endpoint = getattr(r, "endpoint", None)
        protection = codes.get(getattr(endpoint, "__code__", None))
        for method in sorted(getattr(r, "methods", None) or {"MOUNT"}):
            if method != "HEAD":
                out.append(Route(f"{method} {r.path}", protection, r))
    return out


def collect(_root=None, application=None):
    return {fp: f"{getattr(r.endpoint, '__module__', '?')}.{getattr(r.endpoint, '__name__', '?')}"
            for fp, protection, r in routes(application) if protection is None}
