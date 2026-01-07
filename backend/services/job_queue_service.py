"""
Job queue service for managing background transcription jobs in Supabase
"""
import uuid
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from services.supabase_service import supabase


# Configuration constants
GLOBAL_CONCURRENT_LIMIT = 3
STALE_THRESHOLD_SECONDS = 90
MAX_RETRIES = 3


class JobQueueService:
    """Service for managing transcription jobs in Supabase queue"""

    @staticmethod
    def create_job(
        filename: str,
        gcs_path: str,
        file_size_bytes: int,
        video_hash: str,
        user_id: str = None,
        **params
    ) -> Dict:
        """
        Create a new transcription job.

        Checks:
        1. Global concurrent job limit (max 3 processing jobs)
        2. Deduplication by video hash (if video was already processed)

        Args:
            filename: Original filename
            gcs_path: Path in GCS bucket
            file_size_bytes: Size of the file in bytes
            video_hash: Hash of the video content for deduplication
            user_id: Optional user ID for job ownership (from authenticated user)
            **params: Additional parameters (num_speakers, min_speakers, max_speakers, language, force_language)

        Returns:
            Job record with job_id and access_token

        Raises:
            Exception: If concurrent limit reached or other errors
        """
        client = supabase()

        # Check global concurrent limit
        response = client.table("jobs").select("id").eq("status", "processing").execute()
        processing_count = len(response.data) if response.data else 0

        if processing_count >= GLOBAL_CONCURRENT_LIMIT:
            raise Exception(
                f"System is currently processing {processing_count} videos. "
                f"Please wait until one completes before submitting a new job."
            )

        # Check for duplicate by video_hash (if already completed successfully)
        if video_hash:
            response = client.table("jobs").select("*").eq("video_hash", video_hash).eq("status", "completed").execute()
            if response.data and len(response.data) > 0:
                existing_job = response.data[0]
                print(f"[JobQueue] Found existing completed job for video_hash={video_hash}: {existing_job['id']}")
                # Return the existing job instead of creating a new one
                return existing_job

        # Generate unique job ID and access token
        job_id = str(uuid.uuid4())
        access_token = str(uuid.uuid4())

        # Estimate duration based on file size
        estimated_duration_seconds = JobQueueService.get_estimated_duration(file_size_bytes)

        # Create job record
        job_data = {
            "id": job_id,
            "access_token": access_token,
            "user_id": user_id,  # Job ownership for authenticated users
            "filename": filename,
            "gcs_path": gcs_path,
            "file_size_bytes": file_size_bytes,
            "video_hash": video_hash,
            "status": "pending",
            "progress": 0,
            "stage": "queued",
            "message": "Job created and queued",
            "estimated_duration_seconds": estimated_duration_seconds,
            "retry_count": 0,
            # Store job parameters as JSON
            "params": params,
            "created_at": datetime.utcnow().isoformat(),
            "updated_at": datetime.utcnow().isoformat(),
            "last_seen": datetime.utcnow().isoformat(),
        }

        response = client.table("jobs").insert(job_data).execute()

        if not response.data or len(response.data) == 0:
            raise Exception("Failed to create job in database")

        print(f"[JobQueue] Created job {job_id} for {filename} ({file_size_bytes / (1024*1024):.1f} MB)")
        return response.data[0]

    @staticmethod
    def get_job(job_id: str) -> Optional[Dict]:
        """
        Get a job by ID.

        Args:
            job_id: Job ID

        Returns:
            Job record or None if not found
        """
        client = supabase()
        response = client.table("jobs").select("*").eq("id", job_id).execute()

        if response.data and len(response.data) > 0:
            return response.data[0]
        return None

    @staticmethod
    def get_jobs_by_tokens(tokens: List[str], page: int = 1, per_page: int = 10) -> Dict:
        """
        Get jobs for given access tokens with pagination.

        Args:
            tokens: List of access tokens
            page: Page number (1-indexed)
            per_page: Number of jobs per page

        Returns:
            Dict with 'jobs', 'total', 'page', 'per_page', 'total_pages'
        """
        client = supabase()

        # Calculate offset
        offset = (page - 1) * per_page

        # Get total count
        count_response = client.table("jobs").select("id", count="exact").in_("access_token", tokens).execute()
        total = count_response.count if hasattr(count_response, 'count') else 0

        # Get paginated jobs
        response = (
            client.table("jobs")
            .select("*")
            .in_("access_token", tokens)
            .order("created_at", desc=True)
            .range(offset, offset + per_page - 1)
            .execute()
        )

        jobs = response.data if response.data else []
        total_pages = (total + per_page - 1) // per_page if total > 0 else 0

        return {
            "jobs": jobs,
            "total": total,
            "page": page,
            "per_page": per_page,
            "total_pages": total_pages,
        }

    @staticmethod
    def get_jobs_for_user(user_id: str, page: int = 1, per_page: int = 10) -> Dict:
        """
        Get jobs belonging to a specific user with pagination.

        Args:
            user_id: User ID to filter by
            page: Page number (1-indexed)
            per_page: Number of jobs per page

        Returns:
            Dict with 'jobs', 'total', 'page', 'per_page', 'total_pages'
        """
        client = supabase()

        # Calculate offset
        offset = (page - 1) * per_page

        # Get total count for this user
        count_response = client.table("jobs").select("id", count="exact").eq("user_id", user_id).execute()
        total = count_response.count if hasattr(count_response, 'count') else 0

        # Get paginated jobs
        response = (
            client.table("jobs")
            .select("*")
            .eq("user_id", user_id)
            .order("created_at", desc=True)
            .range(offset, offset + per_page - 1)
            .execute()
        )

        jobs = response.data if response.data else []
        total_pages = (total + per_page - 1) // per_page if total > 0 else 0

        return {
            "jobs": jobs,
            "total": total,
            "page": page,
            "per_page": per_page,
            "total_pages": total_pages,
        }

    @staticmethod
    def verify_access(job_id: str, token: str) -> bool:
        """
        Verify that a token has access to a job.

        Args:
            job_id: Job ID
            token: Access token

        Returns:
            True if token is valid for this job
        """
        client = supabase()
        response = client.table("jobs").select("id").eq("id", job_id).eq("access_token", token).execute()

        return response.data and len(response.data) > 0

    @staticmethod
    def update_heartbeat(job_id: str) -> bool:
        """
        Update the last_seen timestamp for a job (heartbeat).

        Args:
            job_id: Job ID

        Returns:
            True if successful
        """
        client = supabase()

        try:
            response = client.table("jobs").update({
                "last_seen": datetime.utcnow().isoformat(),
                "updated_at": datetime.utcnow().isoformat(),
            }).eq("id", job_id).execute()

            return response.data and len(response.data) > 0
        except Exception as e:
            print(f"[JobQueue] Failed to update heartbeat for {job_id}: {e}")
            return False

    @staticmethod
    def update_progress(job_id: str, progress: int, stage: str, message: str = "") -> bool:
        """
        Update job progress.

        Args:
            job_id: Job ID
            progress: Progress percentage (0-100)
            stage: Current stage name
            message: Optional status message

        Returns:
            True if successful
        """
        client = supabase()

        try:
            response = client.table("jobs").update({
                "progress": progress,
                "stage": stage,
                "message": message,
                "updated_at": datetime.utcnow().isoformat(),
                "last_seen": datetime.utcnow().isoformat(),
            }).eq("id", job_id).execute()

            return response.data and len(response.data) > 0
        except Exception as e:
            print(f"[JobQueue] Failed to update progress for {job_id}: {e}")
            return False

    @staticmethod
    def mark_processing(job_id: str) -> bool:
        """
        Mark a job as processing (status change from pending to processing).

        Args:
            job_id: Job ID

        Returns:
            True if successful

        Raises:
            Exception: If job is not in pending state
        """
        client = supabase()

        # Verify job is pending
        job = JobQueueService.get_job(job_id)
        if not job:
            raise Exception(f"Job {job_id} not found")

        if job["status"] != "pending":
            raise Exception(f"Job {job_id} is not in pending state (current: {job['status']})")

        response = client.table("jobs").update({
            "status": "processing",
            "started_at": datetime.utcnow().isoformat(),
            "updated_at": datetime.utcnow().isoformat(),
            "last_seen": datetime.utcnow().isoformat(),
            "progress": 0,
            "stage": "starting",
            "message": "Job processing started",
        }).eq("id", job_id).execute()

        success = response.data and len(response.data) > 0
        if success:
            print(f"[JobQueue] Marked job {job_id} as processing")
        return success

    @staticmethod
    def mark_completed(
        job_id: str,
        video_hash: str,
        result_json: Dict,
        result_srt: str,
        result_vtt: str
    ) -> bool:
        """
        Mark a job as completed with results.

        Args:
            job_id: Job ID
            video_hash: Final video hash
            result_json: Full transcription result as JSON
            result_srt: SRT format subtitles
            result_vtt: VTT format subtitles

        Returns:
            True if successful
        """
        client = supabase()

        try:
            response = client.table("jobs").update({
                "status": "completed",
                "progress": 100,
                "stage": "completed",
                "message": "Transcription completed successfully",
                "video_hash": video_hash,
                "result_json": result_json,
                "result_srt": result_srt,
                "result_vtt": result_vtt,
                "completed_at": datetime.utcnow().isoformat(),
                "updated_at": datetime.utcnow().isoformat(),
                "last_seen": datetime.utcnow().isoformat(),
            }).eq("id", job_id).execute()

            success = response.data and len(response.data) > 0
            if success:
                print(f"[JobQueue] Marked job {job_id} as completed")
            return success
        except Exception as e:
            print(f"[JobQueue] Failed to mark job {job_id} as completed: {e}")
            return False

    @staticmethod
    def mark_failed(job_id: str, error_message: str, error_code: str = "processing_error") -> bool:
        """
        Mark a job as failed with error details.

        Args:
            job_id: Job ID
            error_message: User-friendly error message
            error_code: Error code for categorization

        Returns:
            True if successful
        """
        client = supabase()

        try:
            response = client.table("jobs").update({
                "status": "failed",
                "stage": "failed",
                "message": error_message,
                "error_code": error_code,
                "error_message": error_message,
                "failed_at": datetime.utcnow().isoformat(),
                "updated_at": datetime.utcnow().isoformat(),
                "last_seen": datetime.utcnow().isoformat(),
            }).eq("id", job_id).execute()

            success = response.data and len(response.data) > 0
            if success:
                print(f"[JobQueue] Marked job {job_id} as failed: {error_message}")
            return success
        except Exception as e:
            print(f"[JobQueue] Failed to mark job {job_id} as failed: {e}")
            return False

    @staticmethod
    def cancel_job(job_id: str) -> bool:
        """
        Cancel a pending job (only pending jobs can be cancelled).

        Args:
            job_id: Job ID

        Returns:
            True if successful

        Raises:
            Exception: If job is not in pending state
        """
        client = supabase()

        # Verify job is pending
        job = JobQueueService.get_job(job_id)
        if not job:
            raise Exception(f"Job {job_id} not found")

        if job["status"] != "pending":
            raise Exception(f"Can only cancel pending jobs. Job {job_id} status: {job['status']}")

        response = client.table("jobs").update({
            "status": "cancelled",
            "stage": "cancelled",
            "message": "Job cancelled by user",
            "cancelled_at": datetime.utcnow().isoformat(),
            "updated_at": datetime.utcnow().isoformat(),
        }).eq("id", job_id).execute()

        success = response.data and len(response.data) > 0
        if success:
            print(f"[JobQueue] Cancelled job {job_id}")
        return success

    @staticmethod
    def retry_job(job_id: str) -> Dict:
        """
        Retry a failed job with the same settings.

        Creates a new job with the same parameters and increments retry count.

        Args:
            job_id: ID of the failed job to retry

        Returns:
            New job record

        Raises:
            Exception: If job is not in failed state or max retries reached
        """
        client = supabase()

        # Get the failed job
        job = JobQueueService.get_job(job_id)
        if not job:
            raise Exception(f"Job {job_id} not found")

        if job["status"] != "failed":
            raise Exception(f"Can only retry failed jobs. Job {job_id} status: {job['status']}")

        if job.get("retry_count", 0) >= MAX_RETRIES:
            raise Exception(f"Maximum retry count ({MAX_RETRIES}) reached for job {job_id}")

        # Create a new job with the same parameters
        params = job.get("params", {})
        new_job = JobQueueService.create_job(
            filename=job["filename"],
            gcs_path=job["gcs_path"],
            file_size_bytes=job["file_size_bytes"],
            video_hash=job["video_hash"],
            **params
        )

        # Update retry count
        client.table("jobs").update({
            "retry_count": job.get("retry_count", 0) + 1,
            "updated_at": datetime.utcnow().isoformat(),
        }).eq("id", new_job["id"]).execute()

        print(f"[JobQueue] Created retry job {new_job['id']} for original job {job_id}")
        return new_job

    @staticmethod
    def check_and_recover_stale_jobs() -> Optional[str]:
        """
        Find and recover ONE stale job (last_seen > STALE_THRESHOLD_SECONDS).

        A stale job is one that's been processing but hasn't updated its heartbeat
        in the threshold time, indicating the worker may have crashed.

        Returns:
            Job ID of the recovered job, or None if no stale jobs found
        """
        client = supabase()

        # Calculate stale threshold timestamp
        threshold = datetime.utcnow() - timedelta(seconds=STALE_THRESHOLD_SECONDS)

        # Find stale processing jobs
        response = (
            client.table("jobs")
            .select("*")
            .eq("status", "processing")
            .lt("last_seen", threshold.isoformat())
            .order("last_seen", desc=False)  # Oldest first
            .limit(1)
            .execute()
        )

        if not response.data or len(response.data) == 0:
            return None

        stale_job = response.data[0]
        job_id = stale_job["id"]

        # Reset to pending for retry
        client.table("jobs").update({
            "status": "pending",
            "stage": "queued",
            "message": "Job recovered from stale state - will retry",
            "updated_at": datetime.utcnow().isoformat(),
            "last_seen": datetime.utcnow().isoformat(),
        }).eq("id", job_id).execute()

        print(f"[JobQueue] Recovered stale job {job_id} (last seen: {stale_job['last_seen']})")
        return job_id

    @staticmethod
    def get_estimated_duration(file_size_bytes: int) -> int:
        """
        Estimate processing duration based on file size and historical data.

        Uses historical job data to calculate average processing time per MB,
        then applies that to the current file size.

        Args:
            file_size_bytes: File size in bytes

        Returns:
            Estimated duration in seconds
        """
        client = supabase()

        try:
            # Get completed jobs from the last 30 days with processing time
            thirty_days_ago = (datetime.utcnow() - timedelta(days=30)).isoformat()

            response = (
                client.table("jobs")
                .select("file_size_bytes, started_at, completed_at")
                .eq("status", "completed")
                .gte("completed_at", thirty_days_ago)
                .not_.is_("started_at", "null")
                .not_.is_("completed_at", "null")
                .execute()
            )

            if response.data and len(response.data) > 0:
                # Calculate average processing time per MB
                total_seconds = 0
                total_mb = 0

                for job in response.data:
                    try:
                        started = datetime.fromisoformat(job["started_at"].replace("Z", "+00:00"))
                        completed = datetime.fromisoformat(job["completed_at"].replace("Z", "+00:00"))
                        duration = (completed - started).total_seconds()

                        file_mb = job["file_size_bytes"] / (1024 * 1024)

                        if duration > 0 and file_mb > 0:
                            total_seconds += duration
                            total_mb += file_mb
                    except Exception as e:
                        print(f"[JobQueue] Error parsing job times: {e}")
                        continue

                if total_mb > 0:
                    # Calculate seconds per MB
                    seconds_per_mb = total_seconds / total_mb
                    current_mb = file_size_bytes / (1024 * 1024)
                    estimated = int(seconds_per_mb * current_mb)

                    print(f"[JobQueue] Estimated duration: {estimated}s ({seconds_per_mb:.1f}s/MB * {current_mb:.1f}MB)")
                    return estimated

        except Exception as e:
            print(f"[JobQueue] Error calculating estimated duration: {e}")

        # Fallback: Use a conservative estimate (60 seconds per MB)
        file_mb = file_size_bytes / (1024 * 1024)
        estimated = int(file_mb * 60)
        print(f"[JobQueue] Using fallback estimate: {estimated}s (60s/MB * {file_mb:.1f}MB)")
        return estimated

    @staticmethod
    def cleanup_old_jobs() -> int:
        """
        Delete jobs older than 7 days.

        This helps maintain database size and remove stale data.
        Only deletes jobs that are completed, failed, or cancelled.

        Returns:
            Number of jobs deleted
        """
        client = supabase()

        try:
            # Calculate cutoff date (7 days ago)
            cutoff = (datetime.utcnow() - timedelta(days=7)).isoformat()

            # Delete old jobs (only completed/failed/cancelled)
            response = (
                client.table("jobs")
                .delete()
                .in_("status", ["completed", "failed", "cancelled"])
                .lt("created_at", cutoff)
                .execute()
            )

            deleted_count = len(response.data) if response.data else 0
            if deleted_count > 0:
                print(f"[JobQueue] Cleaned up {deleted_count} old jobs")

            return deleted_count

        except Exception as e:
            print(f"[JobQueue] Error cleaning up old jobs: {e}")
            return 0
