"""
Pipeline cache service for caching intermediate results in Supabase.

Enables crash recovery by allowing the pipeline to skip completed stages
when a job is retried after a Cloud Run crash.
"""
from typing import Optional, Dict

from services.supabase_service import supabase


class PipelineCacheService:
    """Service for caching intermediate pipeline results in Supabase."""

    @staticmethod
    def get_cached(user_id: str, video_hash: str, stage: str) -> Optional[Dict]:
        """
        Retrieve cached data for a pipeline stage.

        Args:
            video_hash: Hash identifying the video
            stage: Pipeline stage name (e.g. 'transcription', 'diarization', 'screenshots')

        Returns:
            Cached data dict, or None if not found
        """
        try:
            client = supabase()
            response = (
                client.table("pipeline_cache")
                .select("data")
                .eq("user_id", user_id)
                .eq("video_hash", video_hash)
                .eq("stage", stage)
                .execute()
            )
            if response.data and len(response.data) > 0:
                print(f"[PipelineCache] Cache HIT for {stage} (video_hash={video_hash[:8]}...)")
                return response.data[0]["data"]
            return None
        except Exception as e:
            print(f"[PipelineCache] Error reading cache for {stage}: {e}")
            return None

    @staticmethod
    def save_cache(user_id: str, video_hash: str, stage: str, data: Dict) -> bool:
        """
        Save intermediate result to cache. Uses upsert to handle re-runs.

        Args:
            video_hash: Hash identifying the video
            stage: Pipeline stage name
            data: Data to cache (must be JSON-serializable)

        Returns:
            True if saved successfully
        """
        try:
            client = supabase()
            client.table("pipeline_cache").upsert(
                {
                    "user_id": user_id,
                    "video_hash": video_hash,
                    "stage": stage,
                    "data": data,
                },
                on_conflict="user_id,video_hash,stage",
            ).execute()
            print(f"[PipelineCache] Cached {stage} for video_hash={video_hash[:8]}...")
            return True
        except Exception as e:
            print(f"[PipelineCache] Error saving cache for {stage}: {e}")
            return False

    @staticmethod
    def get_cached_prefix(user_id: str, video_hash: str, prefix: str) -> Dict[str, Dict]:
        """Return {stage: data} for every stage starting with prefix, in one query."""
        try:
            response = (
                supabase().table("pipeline_cache")
                .select("stage,data")
                .eq("user_id", user_id)
                .eq("video_hash", video_hash)
                .like("stage", f"{prefix}%")
                .execute()
            )
            # "_" is a LIKE wildcard, so match the literal prefix again here.
            rows = {
                row["stage"]: row["data"] for row in (response.data or [])
                if row["stage"].startswith(prefix)
            }
            if rows:
                print(f"[PipelineCache] {len(rows)} checkpoint rows for {prefix} (video_hash={video_hash[:8]}...)")
            return rows
        except Exception as e:
            print(f"[PipelineCache] Error reading cache prefix {prefix}: {e}")
            return {}

    @staticmethod
    def clear_prefix(user_id: str, video_hash: str, prefix: str) -> int:
        """Delete every stage starting with prefix (used once a stage's merged result is saved)."""
        try:
            response = (
                supabase().table("pipeline_cache")
                .delete()
                .eq("user_id", user_id)
                .eq("video_hash", video_hash)
                .like("stage", f"{prefix}%")
                .execute()
            )
            return len(response.data) if response.data else 0
        except Exception as e:
            print(f"[PipelineCache] Error clearing cache prefix {prefix}: {e}")
            return 0

    @staticmethod
    def clear_cache(user_id: str, video_hash: str) -> int:
        """
        Clear all cached stages for a video.

        Args:
            video_hash: Hash identifying the video

        Returns:
            Number of cache entries deleted
        """
        try:
            client = supabase()
            response = (
                client.table("pipeline_cache")
                .delete()
                .eq("user_id", user_id)
                .eq("video_hash", video_hash)
                .execute()
            )
            deleted = len(response.data) if response.data else 0
            if deleted > 0:
                print(f"[PipelineCache] Cleared {deleted} cache entries for video_hash={video_hash[:8]}...")
            return deleted
        except Exception as e:
            print(f"[PipelineCache] Error clearing cache: {e}")
            return 0
