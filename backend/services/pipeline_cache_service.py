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
    def get_cached(video_hash: str, stage: str) -> Optional[Dict]:
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
    def save_cache(video_hash: str, stage: str, data: Dict) -> bool:
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
                    "video_hash": video_hash,
                    "stage": stage,
                    "data": data,
                },
                on_conflict="video_hash,stage",
            ).execute()
            print(f"[PipelineCache] Cached {stage} for video_hash={video_hash[:8]}...")
            return True
        except Exception as e:
            print(f"[PipelineCache] Error saving cache for {stage}: {e}")
            return False

    @staticmethod
    def clear_cache(video_hash: str) -> int:
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
