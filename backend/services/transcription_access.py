"""Authentication helpers for owner-scoped transcription access."""

from fastapi import HTTPException, Request


def authenticated_user_id(request: Request) -> str:
    """Return the authenticated profile id or fail closed."""
    profile = getattr(request.state, "profile", None) or {}
    user_id = profile.get("id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required")
    return str(user_id)

