"""
Rate limiting middleware for upload quotas.

Implements per-user daily upload limits (50/day) and file size validation (4GB max).
"""
from datetime import datetime, timedelta
from typing import Optional
from fastapi import HTTPException
from services.supabase_service import SupabaseService


async def check_upload_limit(user_id: str) -> bool:
    """
    Check if user has uploads remaining today (50/day limit).

    Creates or updates rate_limits entry in database.
    Resets counter if window has expired (new day).

    Args:
        user_id: User UUID

    Returns:
        True if upload allowed, False if limit exceeded

    Raises:
        Exception: If database operation fails
    """
    try:
        client = SupabaseService.get_client()

        # Get current rate limit record
        response = (
            client.table("rate_limits")
            .select("*")
            .eq("user_id", user_id)
            .eq("limit_type", "upload_daily")
            .execute()
        )

        today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)

        if response.data and len(response.data) > 0:
            # Existing record
            rate_limit = response.data[0]
            window_start = datetime.fromisoformat(rate_limit["window_start"].replace('Z', '+00:00'))

            # Check if window has expired (new day)
            if window_start.date() < today.date():
                # Reset counter for new day
                client.table("rate_limits").update({
                    "count": 1,
                    "window_start": today.isoformat()
                }).eq("id", rate_limit["id"]).execute()

                return True
            else:
                # Same day - check limit
                current_count = rate_limit["count"]

                if current_count >= 50:
                    return False

                # Increment counter
                client.table("rate_limits").update({
                    "count": current_count + 1
                }).eq("id", rate_limit["id"]).execute()

                return True
        else:
            # No record yet - create one
            client.table("rate_limits").insert({
                "user_id": user_id,
                "limit_type": "upload_daily",
                "count": 1,
                "window_start": today.isoformat()
            }).execute()

            return True

    except Exception as e:
        print(f"[RateLimit] Error checking upload limit: {e}")
        # Fail open - allow upload but log error
        # In production, you might want to fail closed instead
        return True


async def get_upload_remaining(user_id: str) -> dict:
    """
    Get remaining uploads for user today.

    Args:
        user_id: User UUID

    Returns:
        Dict with count, limit, remaining, resets_at
    """
    try:
        client = SupabaseService.get_client()

        response = (
            client.table("rate_limits")
            .select("*")
            .eq("user_id", user_id)
            .eq("limit_type", "upload_daily")
            .execute()
        )

        today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        tomorrow = today + timedelta(days=1)

        if response.data and len(response.data) > 0:
            rate_limit = response.data[0]
            window_start = datetime.fromisoformat(rate_limit["window_start"].replace('Z', '+00:00'))

            # Check if window expired
            if window_start.date() < today.date():
                # New day - reset
                return {
                    "count": 0,
                    "limit": 50,
                    "remaining": 50,
                    "resets_at": tomorrow.isoformat()
                }
            else:
                current_count = rate_limit["count"]
                return {
                    "count": current_count,
                    "limit": 50,
                    "remaining": max(0, 50 - current_count),
                    "resets_at": tomorrow.isoformat()
                }
        else:
            # No record - full quota available
            return {
                "count": 0,
                "limit": 50,
                "remaining": 50,
                "resets_at": tomorrow.isoformat()
            }

    except Exception as e:
        print(f"[RateLimit] Error getting upload remaining: {e}")
        return {
            "count": 0,
            "limit": 50,
            "remaining": 50,
            "resets_at": tomorrow.isoformat()
        }


def validate_file_size(size_bytes: int, max_size_bytes: int = 4 * 1024 * 1024 * 1024) -> None:
    """
    Validate file size against maximum (default 4GB).

    Args:
        size_bytes: File size in bytes
        max_size_bytes: Maximum allowed size in bytes (default 4GB)

    Raises:
        HTTPException 400: If file too large
    """
    if size_bytes > max_size_bytes:
        max_size_gb = max_size_bytes / (1024 * 1024 * 1024)
        raise HTTPException(
            status_code=400,
            detail=f"File too large. Maximum size is {max_size_gb:.0f}GB."
        )


async def increment_upload_count(user_id: str) -> None:
    """
    Manually increment upload count for user.

    Useful when upload is confirmed successful.

    Args:
        user_id: User UUID
    """
    try:
        client = SupabaseService.get_client()

        today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)

        # Get existing record
        response = (
            client.table("rate_limits")
            .select("*")
            .eq("user_id", user_id)
            .eq("limit_type", "upload_daily")
            .execute()
        )

        if response.data and len(response.data) > 0:
            rate_limit = response.data[0]
            window_start = datetime.fromisoformat(rate_limit["window_start"].replace('Z', '+00:00'))

            if window_start.date() < today.date():
                # New day - reset to 1
                client.table("rate_limits").update({
                    "count": 1,
                    "window_start": today.isoformat()
                }).eq("id", rate_limit["id"]).execute()
            else:
                # Increment
                client.table("rate_limits").update({
                    "count": rate_limit["count"] + 1
                }).eq("id", rate_limit["id"]).execute()
        else:
            # Create new record
            client.table("rate_limits").insert({
                "user_id": user_id,
                "limit_type": "upload_daily",
                "count": 1,
                "window_start": today.isoformat()
            }).execute()

    except Exception as e:
        print(f"[RateLimit] Error incrementing upload count: {e}")
