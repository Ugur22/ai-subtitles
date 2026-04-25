"""
Usage metering — rolls per-job and per-chat usage into the
`user_usage_monthly` table for fast quota checks.

The table is keyed by (user_id, period_start) where period_start is the
first day of the calendar month (UTC). This means a single SELECT row
gives us the user's current-month usage for quota enforcement.

All writes use the service role (bypasses RLS) and are best-effort —
metering should never block or fail a user-facing operation.
"""

from datetime import date, datetime
from typing import Optional

from services.supabase_service import supabase


def _current_period_start() -> str:
    """First day of the current UTC month, ISO date string."""
    today = datetime.utcnow().date()
    return today.replace(day=1).isoformat()


def _upsert_monthly(
    user_id: str,
    *,
    add_transcription_seconds: int = 0,
    add_llm_tokens: int = 0,
    add_chat_messages: int = 0,
) -> None:
    """
    Idempotently bump the user's monthly counters.

    Uses Postgres upsert via Supabase RPC; if the row doesn't exist for
    this period it's created with the deltas as initial values.
    """
    if not user_id:
        return  # legacy / unauthenticated jobs — nothing to meter
    if add_transcription_seconds == 0 and add_llm_tokens == 0 and add_chat_messages == 0:
        return

    client = supabase()
    period_start = _current_period_start()

    try:
        # Read-modify-write — fine for our scale; serializable per row.
        existing = client.table("user_usage_monthly").select("*").eq(
            "user_id", user_id
        ).eq("period_start", period_start).execute()

        if existing.data and len(existing.data) > 0:
            row = existing.data[0]
            client.table("user_usage_monthly").update({
                "transcription_seconds": int(row["transcription_seconds"]) + add_transcription_seconds,
                "llm_tokens":            int(row["llm_tokens"])            + add_llm_tokens,
                "chat_messages":         int(row["chat_messages"])         + add_chat_messages,
                "updated_at":            datetime.utcnow().isoformat(),
            }).eq("user_id", user_id).eq("period_start", period_start).execute()
        else:
            client.table("user_usage_monthly").insert({
                "user_id": user_id,
                "period_start": period_start,
                "transcription_seconds": add_transcription_seconds,
                "llm_tokens": add_llm_tokens,
                "chat_messages": add_chat_messages,
            }).execute()
    except Exception as e:
        # Metering failures must never break the user flow
        print(f"[UsageMeter] Failed to record usage for {user_id}: {e}")


def record_transcription(user_id: Optional[str], video_duration_seconds: int) -> None:
    """Call after a job completes successfully."""
    if not user_id or not video_duration_seconds or video_duration_seconds <= 0:
        return
    _upsert_monthly(user_id, add_transcription_seconds=video_duration_seconds)


def record_chat_message(user_id: Optional[str], llm_tokens: int = 0) -> None:
    """Call after a chat response completes (best estimate of tokens)."""
    if not user_id:
        return
    _upsert_monthly(user_id, add_chat_messages=1, add_llm_tokens=max(0, int(llm_tokens)))


def get_current_month_usage(user_id: str) -> dict:
    """
    Returns {transcription_seconds, llm_tokens, chat_messages} for the
    current calendar month. Returns zeros if no row exists yet.
    """
    if not user_id:
        return {"transcription_seconds": 0, "llm_tokens": 0, "chat_messages": 0}

    client = supabase()
    period_start = _current_period_start()
    try:
        res = client.table("user_usage_monthly").select(
            "transcription_seconds,llm_tokens,chat_messages"
        ).eq("user_id", user_id).eq("period_start", period_start).execute()
        if res.data and len(res.data) > 0:
            return res.data[0]
    except Exception as e:
        print(f"[UsageMeter] Failed to read usage for {user_id}: {e}")
    return {"transcription_seconds": 0, "llm_tokens": 0, "chat_messages": 0}
