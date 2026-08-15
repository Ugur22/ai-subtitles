"""Owner-scoped persistence for transcription jobs and results."""

from collections.abc import Callable
from typing import Any, Optional

from services.supabase_service import supabase


class TranscriptionRepository:
    """Persist transcription metadata in Supabase's jobs table."""

    _JOB_FIELDS = (
        "id,user_id,status,filename,gcs_path,video_hash,"
        "result_json,result_srt,result_vtt,created_at"
    )

    def __init__(self, client_factory: Callable[[], Any] = supabase):
        self._client_factory = client_factory

    def get_job(
        self,
        video_hash: str,
        user_id: str,
        *,
        completed_only: bool = True,
    ) -> Optional[dict[str, Any]]:
        query = (
            self._client_factory()
            .table("jobs")
            .select(self._JOB_FIELDS)
            .eq("video_hash", video_hash)
            .eq("user_id", user_id)
        )
        if completed_only:
            query = query.eq("status", "completed")
        response = query.order("created_at", desc=True).limit(1).execute()
        return response.data[0] if response.data else None

    def get_job_by_media_key(
        self,
        media_key: str,
        user_id: str,
    ) -> Optional[dict[str, Any]]:
        response = (
            self._client_factory()
            .table("jobs")
            .select(self._JOB_FIELDS)
            .eq("gcs_path", media_key)
            .eq("user_id", user_id)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        return response.data[0] if response.data else None

    def get_transcription(
        self,
        video_hash: str,
        user_id: str,
        *,
        refresh_screenshot_urls: bool = False,
    ) -> Optional[dict[str, Any]]:
        job = self.get_job(video_hash, user_id)
        if not job or not isinstance(job.get("result_json"), dict):
            return None

        result = dict(job["result_json"])
        result["user_id"] = user_id
        result.setdefault("video_hash", video_hash)
        result.setdefault("filename", job.get("filename"))
        result.setdefault("media_key", job.get("gcs_path"))
        result.setdefault("gcs_path", job.get("gcs_path"))

        if refresh_screenshot_urls:
            from services.gcs_service import maybe_refresh_segment_urls

            maybe_refresh_segment_urls(result)
        return result

    def update_transcription(
        self,
        video_hash: str,
        user_id: str,
        transcription: dict[str, Any],
    ) -> bool:
        job = self.get_job(video_hash, user_id)
        if not job:
            return False
        response = (
            self._client_factory()
            .table("jobs")
            .update({"result_json": transcription})
            .eq("id", job["id"])
            .eq("user_id", user_id)
            .execute()
        )
        return bool(response.data)

    def update_media_key(self, video_hash: str, user_id: str, media_key: str) -> bool:
        job = self.get_job(video_hash, user_id, completed_only=False)
        if not job:
            return False
        response = (
            self._client_factory()
            .table("jobs")
            .update({"gcs_path": media_key})
            .eq("id", job["id"])
            .eq("user_id", user_id)
            .execute()
        )
        return bool(response.data)

    def delete(self, video_hash: str, user_id: str) -> bool:
        job = self.get_job(video_hash, user_id, completed_only=False)
        if not job:
            return False
        response = (
            self._client_factory()
            .table("jobs")
            .delete()
            .eq("id", job["id"])
            .eq("user_id", user_id)
            .execute()
        )
        return bool(response.data)

    def hash_resources_are_owner_exclusive(self, video_hash: str, user_id: str) -> bool:
        response = (
            self._client_factory()
            .table("jobs")
            .select("user_id")
            .eq("video_hash", video_hash)
            .execute()
        )
        rows = response.data or []
        if not rows or any(not row.get("user_id") for row in rows):
            return False
        return {str(row["user_id"]) for row in rows} == {str(user_id)}

transcription_repository = TranscriptionRepository()
