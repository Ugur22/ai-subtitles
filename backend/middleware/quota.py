"""
Quota enforcement middleware.

Used to gate expensive operations (job submission, chat) based on the
caller's subscription plan + this month's usage.

Two key rules:
  1. Admins (`is_admin=true`) bypass ALL quota checks. The owner always
     has unlimited use of their own infrastructure.
  2. Quotas are checked against `user_usage_monthly` (rolled up by the
     usage_meter service after each job/chat). The DB query is a single
     primary-key lookup, so this is cheap.

Plan limits live in PLAN_LIMITS below. Add tiers there when introducing
new ones — no other code changes needed.
"""

from functools import wraps
from typing import Optional

from fastapi import HTTPException, Request

from services.usage_meter import get_current_month_usage


# ─── Plan limits ─────────────────────────────────────────────────────────────
# All values in seconds (or counts). None = unlimited (used by 'unlimited' plan
# and admin bypass).

PLAN_LIMITS = {
    "free": {
        "monthly_transcription_seconds": 60 * 60,           # 60 min/month
        "max_file_duration_seconds": 30 * 60,               # 30 min per file
        "max_concurrent_jobs": 1,
        "chat_enabled": False,
    },
    "pro": {
        "monthly_transcription_seconds": 15 * 60 * 60,      # 15 hours/month
        "max_file_duration_seconds": 3 * 60 * 60,           # 3 hours per file
        "max_concurrent_jobs": 3,
        "chat_enabled": True,
    },
    "studio": {
        "monthly_transcription_seconds": 50 * 60 * 60,      # 50 hours/month
        "max_file_duration_seconds": 6 * 60 * 60,
        "max_concurrent_jobs": 10,
        "chat_enabled": True,
    },
}

# Sentinel returned when the user is exempt (admin or unknown plan).
UNLIMITED = {
    "monthly_transcription_seconds": None,
    "max_file_duration_seconds": None,
    "max_concurrent_jobs": None,
    "chat_enabled": True,
}


def _profile_is_admin(profile: Optional[dict]) -> bool:
    return bool(profile and profile.get("is_admin"))


def _get_plan_limits(profile: Optional[dict]) -> dict:
    """Return the effective limits for this user (admin → UNLIMITED)."""
    if _profile_is_admin(profile):
        return UNLIMITED
    plan = (profile or {}).get("subscription_plan") or "free"
    return PLAN_LIMITS.get(plan, PLAN_LIMITS["free"])


# ─── Public helpers ──────────────────────────────────────────────────────────

def check_can_transcribe(
    profile: Optional[dict],
    *,
    file_duration_seconds: Optional[int] = None,
) -> None:
    """
    Raise HTTPException 402 (Payment Required) if the caller cannot start a
    new transcription. Admins always pass.

    Args:
      profile: dict from request.state.profile (must include subscription_plan,
               is_admin, id).
      file_duration_seconds: if known up-front (rare — usually we only know
               after probing), enforce the per-file cap.
    """
    if _profile_is_admin(profile):
        return

    user_id = (profile or {}).get("id")
    limits = _get_plan_limits(profile)

    # Per-file duration cap
    cap = limits["max_file_duration_seconds"]
    if cap is not None and file_duration_seconds is not None and file_duration_seconds > cap:
        raise HTTPException(
            status_code=402,
            detail={
                "error": "file_too_long",
                "message": f"This file exceeds your plan's per-file limit of {cap // 60} minutes.",
                "limit_seconds": cap,
                "file_seconds": file_duration_seconds,
                "upgrade_url": "/pricing",
            },
        )

    # Monthly minute cap
    monthly_cap = limits["monthly_transcription_seconds"]
    if monthly_cap is not None and user_id:
        used = get_current_month_usage(user_id)["transcription_seconds"]
        if used >= monthly_cap:
            raise HTTPException(
                status_code=402,
                detail={
                    "error": "monthly_quota_exceeded",
                    "message": f"You've used your {monthly_cap // 60}-minute monthly transcription quota. Upgrade for more.",
                    "limit_seconds": monthly_cap,
                    "used_seconds": used,
                    "upgrade_url": "/pricing",
                },
            )


def check_can_chat(profile: Optional[dict]) -> None:
    """
    Raise HTTPException 402 if the caller cannot send a chat message.
    Admins always pass. Free tier has chat disabled.
    """
    if _profile_is_admin(profile):
        return
    limits = _get_plan_limits(profile)
    if not limits["chat_enabled"]:
        raise HTTPException(
            status_code=402,
            detail={
                "error": "chat_requires_upgrade",
                "message": "Chat with video is a Pro feature. Upgrade to unlock.",
                "upgrade_url": "/pricing",
            },
        )


# ─── Decorators (optional sugar — endpoints can also call helpers directly) ──

def require_transcription_quota(func):
    """
    Decorator for endpoints that start a transcription. Assumes the route
    is already protected by @require_auth so request.state.profile exists.
    """
    @wraps(func)
    async def wrapper(request: Request, *args, **kwargs):
        check_can_transcribe(getattr(request.state, "profile", None))
        return await func(request, *args, **kwargs)
    return wrapper


def require_chat_quota(func):
    @wraps(func)
    async def wrapper(request: Request, *args, **kwargs):
        check_can_chat(getattr(request.state, "profile", None))
        return await func(request, *args, **kwargs)
    return wrapper


# ─── Usage snapshot for UI ───────────────────────────────────────────────────

def get_usage_snapshot(profile: Optional[dict]) -> dict:
    """
    Returns the data the frontend needs to render the usage meter & upgrade
    prompts: limits + this month's usage + plan + admin flag.
    """
    limits = _get_plan_limits(profile)
    is_admin = _profile_is_admin(profile)
    plan = (profile or {}).get("subscription_plan") or "free"
    user_id = (profile or {}).get("id")
    usage = get_current_month_usage(user_id) if user_id else {
        "transcription_seconds": 0, "llm_tokens": 0, "chat_messages": 0
    }
    return {
        "plan": plan,
        "is_admin": is_admin,
        "is_unlimited": is_admin,
        "usage": usage,
        "limits": limits,
    }
