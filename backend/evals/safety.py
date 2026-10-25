"""Opt-in guard for scripts that use the Supabase project named in the environment."""

import sys
from urllib.parse import urlparse


def require_remote_opt_in(allow_remote: bool, action: str) -> None:
    """Exit unless the caller explicitly accepted the target project.

    These scripts use SUPABASE_SERVICE_KEY, which bypasses row-level security and
    normally points at production, so a bare run must not touch it by accident.
    """
    from config import settings

    if getattr(settings, "LOCAL_MODE", False):
        return
    host = urlparse(settings.SUPABASE_URL or "").hostname or "<SUPABASE_URL not set>"
    print(f"Target Supabase project: {host} ({action})")
    if not allow_remote:
        print("Refusing to run without --allow-remote.", file=sys.stderr)
        raise SystemExit(2)
