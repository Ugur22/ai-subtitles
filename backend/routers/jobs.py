"""
Jobs API router for background job processing system.

This router provides endpoints for managing asynchronous transcription jobs,
allowing users to submit videos, track progress, and retrieve results without
maintaining an active connection.
"""
import asyncio
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from typing import Optional, List, Callable, Any
from datetime import datetime

from fastapi import APIRouter, HTTPException, BackgroundTasks, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel

from config import settings
from middleware.auth import require_auth, require_admin, optional_auth
from services.media_storage import get_media_storage

logger = logging.getLogger(__name__)


# Executor for non-blocking database operations
# This prevents Supabase calls from blocking the event loop during heavy GPU processing
_jobs_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="jobs_db")


async def _run_in_executor(func: Callable, *args, **kwargs) -> Any:
    """Run blocking function in executor to avoid blocking event loop."""
    loop = asyncio.get_event_loop()
    if kwargs:
        return await loop.run_in_executor(_jobs_executor, lambda: func(*args, **kwargs))
    return await loop.run_in_executor(_jobs_executor, func, *args)


router = APIRouter(prefix="/api/jobs", tags=["Jobs"])


# =============================================================================
# Pydantic Models
# =============================================================================

class JobSubmitRequest(BaseModel):
    """Request model for job submission."""
    filename: str
    gcs_path: str
    file_size_bytes: int
    video_hash: str
    duration_seconds: Optional[int] = None  # client-reported video length (advisory; worker re-probes)
    num_speakers: Optional[int] = None
    min_speakers: Optional[int] = None
    max_speakers: Optional[int] = None
    language: Optional[str] = None
    force_language: bool = False


class JobSubmitResponse(BaseModel):
    """Response model for job submission."""
    job_id: str
    access_token: str
    cached: bool
    cached_at: Optional[str] = None
    estimated_duration_seconds: Optional[int] = None


class JobStatusResponse(BaseModel):
    """Response model for job status."""
    job_id: str
    status: str  # pending, processing, completed, failed, cancelled
    filename: str
    file_size_bytes: int
    progress: int
    progress_stage: Optional[str] = None
    progress_message: Optional[str] = None
    error_message: Optional[str] = None
    error_code: Optional[str] = None
    result_json: Optional[dict] = None
    result_srt: Optional[str] = None
    result_vtt: Optional[str] = None
    created_at: str
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    cached: Optional[bool] = None
    cached_at: Optional[str] = None
    # Pre-signed video playback URL for completed jobs. Lets the frontend mount
    # the video player without a separate /video_url round-trip.
    video_url: Optional[str] = None


def _safe_video_url(job: dict) -> Optional[str]:
    """Generate a short-lived signed video URL for a completed job, or None."""
    if job.get('status') != 'completed':
        return None
    gcs_path = job.get('gcs_path') or (job.get('result_json') or {}).get('gcs_path')
    if not gcs_path:
        return None
    try:
        return get_media_storage().generate_download_url(
            gcs_path, expiry_seconds=settings.GCS_DOWNLOAD_URL_EXPIRY
        )
    except Exception as e:
        print(f"[Jobs] Skipping video_url for {job.get('id')}: {e}")
        return None


class JobListResponse(BaseModel):
    """Response model for job list."""
    jobs: List[JobStatusResponse]
    total: int
    page: int
    per_page: int


class JobCancelResponse(BaseModel):
    """Response model for job cancellation."""
    job_id: str
    status: str
    message: str


class JobRetryResponse(BaseModel):
    """Response model for job retry."""
    job_id: str
    status: str
    message: str


class ShareLinkResponse(BaseModel):
    """Response model for shareable link."""
    share_url: str


class StaleJobCheckResponse(BaseModel):
    """Response model for stale job check."""
    processed: int
    message: str


class RefreshUrlsResponse(BaseModel):
    """Response model for the scheduled screenshot URL refresh job."""
    refreshed_jobs: int
    refreshed_image_rows: int
    skipped: int
    failed: int
    cutoff_days: int


class BackfillFacePresenceResponse(BaseModel):
    """Response model for the manual face-presence backfill job."""
    processed_videos: int
    indexed_face_rows: int
    skipped: int
    failed: int
    batch_size: int


class BackfillCaptionsResponse(BaseModel):
    """Response model for the manual vision-caption backfill job."""
    processed_videos: int
    captioned_images: int
    dense_frames_added: int
    skipped: int
    failed: int
    batch_size: int


# =============================================================================
# Helper Functions
# =============================================================================

def verify_token(job_id: str, token: str) -> bool:
    """
    Verify that the provided access token is valid for the given job.

    Args:
        job_id: The job ID to verify
        token: The access token to validate

    Returns:
        True if token is valid, False otherwise

    Raises:
        HTTPException: If service is unavailable
    """
    try:
        from services.job_queue_service import JobQueueService
        return JobQueueService.verify_access(job_id, token)
    except ImportError:
        raise HTTPException(
            status_code=503,
            detail="Job queue service not available. Background processing not configured."
        )
    except Exception as e:
        print(f"[Jobs] Error verifying token: {e}")
        raise HTTPException(status_code=500, detail="Failed to verify access token")


def require_token(job_id: str, token: Optional[str]) -> None:
    """
    Require valid token or raise 403.

    Args:
        job_id: The job ID to verify
        token: The access token to validate (from query param)

    Raises:
        HTTPException: 403 if token invalid, 400 if missing
    """
    if not token:
        raise HTTPException(
            status_code=400,
            detail="Access token required. Include ?token=YOUR_TOKEN in the URL."
        )

    if not verify_token(job_id, token):
        raise HTTPException(
            status_code=403,
            detail="Invalid access token for this job."
        )


def require_job_access(job_id: str, token: Optional[str], user_id: Optional[str]) -> dict:
    """
    Verify access to a job via token OR ownership.

    Access granted if:
    1. Valid access token provided, OR
    2. Job belongs to authenticated user (user_id matches)

    Args:
        job_id: The job ID to verify
        token: Optional access token
        user_id: Optional authenticated user ID

    Returns:
        Job dict if access granted

    Raises:
        HTTPException: 403 if no valid access, 404 if job not found
    """
    from services.job_queue_service import JobQueueService

    job = JobQueueService.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # Check token access (for shared links)
    if token and verify_token(job_id, token):
        return job

    # Check ownership (authenticated user owns this job)
    if user_id and job.get("user_id") == user_id:
        return job

    raise HTTPException(
        status_code=403,
        detail="Access denied. Provide valid token or access your own jobs."
    )


def require_job_owner(job_id: str, user_id: str) -> dict:
    """Return an owned job; share tokens are deliberately read-only."""
    from services.job_queue_service import JobQueueService
    job = JobQueueService.get_job_for_user(job_id, user_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


# =============================================================================
# Endpoints
# =============================================================================

@router.post("/submit", response_model=JobSubmitResponse)
@require_auth
async def submit_job(
    request: Request,
    job_request: JobSubmitRequest,
    background_tasks: BackgroundTasks
):
    """
    Submit a new transcription job.

    The job will be queued for background processing. Returns immediately with
    job_id and access_token for tracking progress.

    **Authentication**: Requires authenticated user session.

    **Queue Limit**: Maximum 3 concurrent jobs globally. Returns 429 if queue is full.

    **Deduplication**: If a job with the same video_hash was already completed,
    returns the cached result immediately.

    Args:
        request: FastAPI request with authenticated user
        job_request: Job parameters including file info and transcription settings
        background_tasks: FastAPI background tasks for async processing

    Returns:
        JobSubmitResponse with job_id, access_token, and cache status

    Raises:
        401: Not authenticated
        429: Queue is full (3 jobs already processing)
        503: Job queue service not available
    """
    try:
        from services.job_queue_service import JobQueueService
    except ImportError:
        raise HTTPException(
            status_code=503,
            detail="Job queue service not available. Background processing not configured."
        )

    # Get authenticated user ID
    user_id = request.state.user["id"]

    # Quota check (admins bypass; free/pro/studio enforced). The client-reported
    # duration gives instant feedback here; the worker re-probes the real duration
    # before transcription so this can't be bypassed by spoofing duration_seconds.
    from middleware.quota import check_can_transcribe, _get_plan_limits
    check_can_transcribe(
        getattr(request.state, "profile", None),
        file_duration_seconds=job_request.duration_seconds,
    )

    try:
        media_storage = get_media_storage()
        if not media_storage.is_user_upload_path(job_request.gcs_path, user_id):
            raise HTTPException(status_code=403, detail="Upload path is not owned by this user.")
        if not media_storage.file_exists(job_request.gcs_path):
            raise HTTPException(status_code=400, detail="Uploaded object was not found.")
        actual_size = media_storage.get_file_size(job_request.gcs_path)
        if actual_size != job_request.file_size_bytes:
            raise HTTPException(status_code=400, detail="Uploaded object size does not match the upload intent.")

        limits = _get_plan_limits(getattr(request.state, "profile", None))
        # Create job (checks queue limit and deduplication)
        result = JobQueueService.create_job(
            filename=job_request.filename,
            gcs_path=job_request.gcs_path,
            file_size_bytes=job_request.file_size_bytes,
            video_hash=job_request.video_hash,
            user_id=user_id,  # Associate job with authenticated user
            duration_seconds=job_request.duration_seconds,
            monthly_limit_seconds=limits["monthly_transcription_seconds"],
            user_concurrent_limit=limits["max_concurrent_jobs"],
            num_speakers=job_request.num_speakers,
            min_speakers=job_request.min_speakers,
            max_speakers=job_request.max_speakers,
            language=job_request.language,
            force_language=job_request.force_language
        )

        # If not cached, trigger the Cloud Run Job worker (runs to completion outside the Service).
        if not result.get('cached', False):
            try:
                JobQueueService.trigger_worker_job(result['id'])
            except Exception as dispatch_error:
                JobQueueService.mark_failed(
                    result['id'],
                    "Failed to dispatch worker job",
                    "dispatch_error"
                )
                raise HTTPException(
                    status_code=503,
                    detail="Could not dispatch background worker. Try again shortly."
                ) from dispatch_error

            # Get estimated duration if available
            estimated_duration = JobQueueService.get_estimated_duration(
                job_request.file_size_bytes
            )
            if estimated_duration:
                result['estimated_duration_seconds'] = estimated_duration

        # Map 'id' to 'job_id' for response
        return JobSubmitResponse(
            job_id=result['id'],
            access_token=result['access_token'],
            cached=result.get('cached', False),
            cached_at=result.get('cached_at'),
            estimated_duration_seconds=result.get('estimated_duration_seconds')
        )

    except HTTPException:
        raise
    except Exception as e:
        from services.job_queue_service import JobQueueError
        if isinstance(e, JobQueueError):
            status = 402 if e.code == "monthly_quota_exceeded" else 429
            if e.code in {"invalid_or_expired_upload_intent", "upload_intent_mismatch", "invalid job identity"}:
                status = 400
            raise HTTPException(status_code=status, detail={"error": e.code})
        print(f"[Jobs] Error submitting job: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Failed to submit job: {str(e)}")


@router.get("/{job_id}", response_model=JobStatusResponse)
@require_auth
async def get_job_status(
    request: Request,
    job_id: str,
    token: Optional[str] = Query(None, description="Access token for shared links")
):
    """
    Get detailed status for a specific job.

    Access granted via:
    - Ownership: Authenticated user owns the job
    - Token: Valid access token provided (for shared links)

    Args:
        request: FastAPI request with authenticated user
        job_id: The unique job identifier
        token: Optional access token (for shared links)

    Returns:
        JobStatusResponse with complete job details

    Raises:
        401: Not authenticated
        403: Not owner and no valid token
        404: Job not found
    """
    # Get authenticated user ID
    user_id = request.state.user["id"]

    # Verify access via ownership OR token
    job = require_job_access(job_id, token, user_id)

    try:
        result_json = job.get('result_json')

        # Re-sign per-segment screenshot URLs before responding. V4 IAM URLs cap
        # at 7 days; the daily refresh-screenshot-urls cron keeps DB URLs fresh,
        # but this handler is the user-visible read path so we also self-heal
        # here. Runs in an executor to keep N IAM signBlob calls off the loop.
        # Not added to list_jobs — that path's bulk refresh caused 504s.
        if result_json and settings.ENABLE_GCS_UPLOADS:
            try:
                from services.gcs_service import maybe_refresh_segment_urls
                await _run_in_executor(maybe_refresh_segment_urls, result_json)
            except Exception:
                logger.exception("[Jobs] per-request segment URL refresh failed for job %s", job_id)

        # Map database fields to response model
        return JobStatusResponse(
            job_id=job['id'],
            status=job['status'],
            filename=job['filename'],
            file_size_bytes=job['file_size_bytes'],
            progress=job['progress'],
            progress_stage=job.get('stage'),
            progress_message=job.get('message'),
            error_message=job.get('error_message'),
            error_code=job.get('error_code'),
            result_json=result_json,
            result_srt=job.get('result_srt'),
            result_vtt=job.get('result_vtt'),
            created_at=job['created_at'],
            started_at=job.get('started_at'),
            completed_at=job.get('completed_at'),
            cached=job.get('cached'),
            cached_at=job.get('cached_at'),
            video_url=_safe_video_url(job)
        )

    except HTTPException:
        raise
    except Exception as e:
        print(f"[Jobs] Error getting job status: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve job status")


@router.get("", response_model=JobListResponse)
@require_auth
async def list_jobs(
    request: Request,
    tokens: Optional[str] = Query(None, description="Comma-separated access tokens"),
    page: int = Query(1, ge=1, description="Page number (1-indexed)"),
    per_page: int = Query(10, ge=1, le=50, description="Items per page (max 50)")
):
    """
    List jobs belonging to the authenticated user.

    The list endpoint deliberately ignores browser-stored job tokens. Tokens are
    valid for direct shared-job access, but using them here would let jobs from
    one account appear in another account's Recent list when users switch
    accounts in the same browser.

    **Authentication**: Requires authenticated user session.

    Args:
        request: FastAPI request with authenticated user
        tokens: Deprecated. Ignored for authenticated job listing.
        page: Page number (1-indexed)
        per_page: Items per page (max 50)

    Returns:
        JobListResponse with paginated job list
    """
    try:
        from services.job_queue_service import JobQueueService

        # Get authenticated user ID
        user_id = request.state.user["id"]

        # Get jobs owned by the authenticated user only. Do not merge token
        # matches into this list; localStorage is shared across accounts on the
        # same browser origin.
        result = await _run_in_executor(
            JobQueueService.get_jobs_for_user,
            user_id=user_id,
            page=page,
            per_page=per_page
        )
        jobs = result['jobs']
        total = result['total']

        # Map jobs to response format. The list endpoint intentionally skips
        # per-segment URL refresh and per-job video_url signing — both cost an
        # IAM signBlob HTTP call each and used to time out the page. URLs are
        # kept fresh at rest by the daily refresh-screenshot-urls cron; the
        # opened-video player gets its video_url from get_job_status instead.
        mapped_jobs = []
        for job in jobs:
            mapped_jobs.append(JobStatusResponse(
                job_id=job['id'],
                status=job['status'],
                filename=job['filename'],
                file_size_bytes=job['file_size_bytes'],
                progress=job['progress'],
                progress_stage=job.get('stage'),
                progress_message=job.get('message'),
                error_message=job.get('error_message'),
                error_code=job.get('error_code'),
                result_json=job.get('result_json'),
                result_srt=job.get('result_srt'),
                result_vtt=job.get('result_vtt'),
                created_at=job['created_at'],
                started_at=job.get('started_at'),
                completed_at=job.get('completed_at'),
                cached=job.get('cached'),
                cached_at=job.get('cached_at'),
                video_url=None,
            ))

        return JobListResponse(
            jobs=mapped_jobs,
            total=total,
            page=page,
            per_page=per_page
        )

    except Exception as e:
        print(f"[Jobs] Error listing jobs: {e}")
        raise HTTPException(status_code=500, detail="Failed to list jobs")


@router.delete("/{job_id}", response_model=JobCancelResponse)
@require_auth
async def cancel_job(
    request: Request,
    job_id: str,
    token: Optional[str] = Query(None, description="Access token for shared links")
):
    """
    Cancel a pending or processing job.

    Pending and processing jobs can be cancelled. Jobs that are already
    completed, failed, or cancelled cannot be cancelled.

    Access granted via ownership OR token.

    Args:
        request: FastAPI request with authenticated user
        job_id: The unique job identifier
        token: Optional access token (for shared links)

    Returns:
        JobCancelResponse with cancellation status

    Raises:
        400: Job cannot be cancelled (already completed/failed/cancelled)
        401: Not authenticated
        403: Not owner and no valid token
        404: Job not found
    """
    # Get authenticated user ID
    user_id = request.state.user["id"]

    # Verify access via ownership OR token (also fetches job)
    job = require_job_owner(job_id, user_id)

    try:
        from services.job_queue_service import JobQueueService

        # Check if job can be cancelled (allow pending and processing)
        if job['status'] not in ('pending', 'processing'):
            raise HTTPException(
                status_code=400,
                detail=f"Cannot cancel job with status '{job['status']}'. Only pending or processing jobs can be cancelled."
            )

        # Cancel the job
        success = JobQueueService.cancel_job(job_id, user_id)

        if not success:
            raise HTTPException(
                status_code=400,
                detail="Failed to cancel job. It may have already started processing."
            )

        return JobCancelResponse(
            job_id=job_id,
            status="cancelled",
            message="Job cancelled successfully"
        )

    except HTTPException:
        raise
    except Exception as e:
        print(f"[Jobs] Error cancelling job: {e}")
        raise HTTPException(status_code=500, detail="Failed to cancel job")


@router.post("/{job_id}/retry", response_model=JobRetryResponse)
@require_auth
async def retry_job(
    request: Request,
    job_id: str,
    token: Optional[str] = Query(None, description="Access token for shared links"),
    background_tasks: BackgroundTasks = None
):
    """
    Retry a failed job with the same settings.

    Resets the job to pending status and re-queues it for processing.
    Settings cannot be modified during retry - use a new job submission to change settings.

    Access granted via ownership OR token.

    Args:
        request: FastAPI request with authenticated user
        job_id: The unique job identifier
        token: Optional access token (for shared links)
        background_tasks: FastAPI background tasks for async processing

    Returns:
        JobRetryResponse with retry status

    Raises:
        400: Job is not in failed status
        401: Not authenticated
        403: Not owner and no valid token
        404: Job not found
    """
    # Get authenticated user ID
    user_id = request.state.user["id"]

    # Verify access via ownership OR token (also fetches job)
    job = require_job_owner(job_id, user_id)

    try:
        from services.job_queue_service import JobQueueService

        if job['status'] != 'failed':
            raise HTTPException(
                status_code=400,
                detail=f"Cannot retry job with status '{job['status']}'. Only failed jobs can be retried."
            )

        # Retry the job (creates a new job with same params)
        new_job = JobQueueService.retry_job(job_id, user_id)

        if not new_job:
            raise HTTPException(status_code=500, detail="Failed to retry job")

        new_job_id = new_job['id']

        # Trigger the Cloud Run Job worker for the NEW job.
        try:
            JobQueueService.trigger_worker_job(new_job_id)
        except Exception as dispatch_error:
            JobQueueService.mark_failed(
                new_job_id,
                "Failed to dispatch worker job",
                "dispatch_error"
            )
            raise HTTPException(
                status_code=503,
                detail="Could not dispatch background worker. Try again shortly."
            ) from dispatch_error

        return JobRetryResponse(
            job_id=new_job_id,
            status="pending",
            message="Job queued for retry"
        )

    except HTTPException:
        raise
    except Exception as e:
        print(f"[Jobs] Error retrying job: {e}")
        raise HTTPException(status_code=500, detail="Failed to retry job")


@router.delete("/{job_id}/permanent")
@require_auth
async def delete_job_permanent(
    request: Request,
    job_id: str,
    token: Optional[str] = Query(None, description="Access token for shared links")
):
    """
    Permanently delete a job and all associated files.

    Deletes:
    - Video file from GCS (if exists)
    - Screenshots folder from GCS (if exists)
    - Job record from database

    **Warning**: This action is irreversible. All job data and results will be lost.

    Access granted via ownership OR token.

    Args:
        request: FastAPI request with authenticated user
        job_id: The unique job identifier
        token: Optional access token (for shared links)

    Returns:
        Success message with details about deleted resources

    Raises:
        401: Not authenticated
        403: Not owner and no valid token
        404: Job not found
    """
    from services.job_queue_service import JobQueueService

    # Get authenticated user ID
    user_id = request.state.user["id"]

    # Verify access via ownership OR token (also fetches job)
    job = require_job_owner(job_id, user_id)

    try:
        deleted_resources = {
            "video": False,
            "screenshots": 0,
            "database": False
        }

        deletion = await _run_in_executor(
            JobQueueService.claim_permanent_deletion,
            job_id,
            user_id,
        )
        if not deletion or deletion.get("error_code") == "job_not_found":
            raise HTTPException(status_code=409, detail="Job could not be deleted")
        if deletion.get("error_code") == "job_not_terminal":
            raise HTTPException(
                status_code=409,
                detail="Only completed, failed, or cancelled jobs can be permanently deleted",
            )
        if not deletion.get("deleted"):
            raise HTTPException(status_code=409, detail="Job could not be deleted")

        deleted_resources["database"] = True
        outbox_id = deletion.get("outbox_id")
        cleanup_pending = False
        if outbox_id:
            cleanup = await _run_in_executor(
                JobQueueService.drain_media_deletions_best_effort,
                limit=1,
                outbox_id=outbox_id,
            )
            deleted_resources["video"] = cleanup["completed"] == 1
            cleanup_pending = not deleted_resources["video"]

        # Shared, legacy, and screenshot resources are deliberately retained.

        # Build response message
        message_parts = ["Job deleted permanently"]
        if deleted_resources["video"]:
            message_parts.append("video file removed")
        if deleted_resources["screenshots"] > 0:
            message_parts.append(f"{deleted_resources['screenshots']} screenshots removed")

        message = ". ".join(message_parts) + "."

        return {
            "success": True,
            "message": message,
            "deleted_resources": deleted_resources,
            "cleanup_pending": cleanup_pending,
        }

    except HTTPException:
        raise
    except Exception as e:
        print(f"[Jobs] Error permanently deleting job: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail=f"Failed to permanently delete job: {str(e)}"
        )


@router.get("/{job_id}/share", response_model=ShareLinkResponse)
@require_auth
async def get_share_link(
    request: Request,
    job_id: str,
    token: Optional[str] = Query(None, description="Access token for shared links")
):
    """
    Generate a shareable link for a job.

    The link includes the access token, allowing anyone with the link to view
    the job status and results.

    **Security Note**: Anyone with this link can access the job. Only share with
    trusted parties.

    Access granted via ownership OR token.

    Args:
        request: FastAPI request with authenticated user
        job_id: The unique job identifier
        token: Optional access token (for shared links)

    Returns:
        ShareLinkResponse with shareable URL

    Raises:
        401: Not authenticated
        403: Not owner and no valid token
        404: Job not found
    """
    # Get authenticated user ID
    user_id = request.state.user["id"]

    # Verify access via ownership OR token (also fetches job)
    job = require_job_owner(job_id, user_id)

    try:
        # Generate shareable URL using the job's access token
        # Note: In production, this would use the actual frontend URL from settings
        base_url = "https://REDACTED_FRONTEND_URL"  # TODO: Get from settings
        share_url = f"{base_url}/jobs/{job_id}?token={job['access_token']}"

        return ShareLinkResponse(share_url=share_url)

    except HTTPException:
        raise
    except Exception as e:
        print(f"[Jobs] Error generating share link: {e}")
        raise HTTPException(status_code=500, detail="Failed to generate share link")


@router.post("/check-stale", response_model=StaleJobCheckResponse)
@require_admin
async def check_stale_jobs(request: Request, background_tasks: BackgroundTasks):
    """
    Check for and recover stuck jobs (admin-only endpoint).

    This endpoint is called by Cloud Scheduler every 5 minutes to detect jobs
    that are stuck either in 'processing' (worker crashed mid-job) or in 'pending'
    (worker never started — dispatch failed or crashed before mark_processing).
    Requires admin authentication to prevent unauthorized access.

    **Stale Detection**: processing jobs with no heartbeat for 90+ seconds, or
      pending jobs older than PENDING_STALE_SECONDS (no other poller picks these up)
    **Recovery**: re-dispatches the worker; after max 3 attempts marks the job failed
    **Rate Limit**: Processes one stuck job per call

    Returns:
        StaleJobCheckResponse with number of jobs processed
    """
    try:
        from services.job_queue_service import JobQueueService
        from services.key_validator import sweep_stuck_pending_keys

        # Self-heal API keys stuck in 'pending' validation so the frontend stops
        # polling /api/keys every 2s for them (see PENDING_KEY_STALE_SECONDS).
        sweep_stuck_pending_keys()

        try:
            cleanup = await _run_in_executor(
                JobQueueService.process_media_delete_outbox,
                limit=10,
            )
            if cleanup["pending"]:
                logger.warning(
                    "[Jobs] %d media deletions remain pending",
                    cleanup["pending"],
                )
        except Exception:
            logger.exception("[Jobs] Pending media cleanup failed")

        recovered_job_id = JobQueueService.check_and_recover_stale_jobs()

        if recovered_job_id:
            message = f"Recovered stale job {recovered_job_id}"
            processed = 1
        else:
            message = "No stale jobs found"
            processed = 0

        return StaleJobCheckResponse(
            processed=processed,
            message=message
        )

    except Exception as e:
        print(f"[Jobs] Error checking stale jobs: {e}")
        import traceback
        traceback.print_exc()
        # Don't raise exception - this is a background job, just log and return
        return StaleJobCheckResponse(
            processed=0,
            message=f"Error: {str(e)}"
        )


@router.post("/refresh-screenshot-urls", response_model=RefreshUrlsResponse)
@require_admin
async def refresh_screenshot_urls(request: Request):
    """Refresh GCS signed URLs for completed jobs whose at-rest URLs are nearing expiry.

    V4 IAM-signed URLs cap at 7 days. Cloud Scheduler should hit this daily so the
    URLs stored in `jobs.result_json` and `image_embeddings.screenshot_url` are
    never more than ~24 hours old, keeping screenshots reachable for the full
    `URL_REFRESH_CUTOFF_DAYS` window without any user-side refresh.
    """
    from datetime import datetime, timedelta, timezone

    cutoff_days = settings.URL_REFRESH_CUTOFF_DAYS

    if not settings.ENABLE_GCS_UPLOADS:
        return RefreshUrlsResponse(
            refreshed_jobs=0,
            refreshed_image_rows=0,
            skipped=0,
            failed=0,
            cutoff_days=cutoff_days,
        )

    from services.gcs_service import maybe_refresh_segment_urls, gcs_service
    from services.supabase_service import supabase
    import time

    cutoff = (datetime.now(timezone.utc) - timedelta(days=cutoff_days)).isoformat()
    batch_size = settings.URL_REFRESH_BATCH_SIZE

    # Stop well before Cloud Scheduler's 300s attempt-deadline so the run always
    # returns a clean summary (and the next daily run picks up any remainder)
    # instead of being killed mid-flight.
    deadline = time.monotonic() + 240.0

    # Refresh signing credentials once up front so each signBlob call reuses a valid
    # access token instead of risking a refresh race per URL.
    try:
        gcs_service._get_credentials()
    except Exception:
        logger.exception("[Jobs] refresh-screenshot-urls: credential refresh failed")

    client = supabase()
    refreshed_jobs = 0
    refreshed_image_rows = 0
    skipped = 0
    failed = 0
    stopped_early = False
    owned_video_hashes: set[tuple[str, str]] = set()

    # 1. Refresh jobs.result_json segments
    try:
        resp = await _run_in_executor(
            lambda: client.table("jobs")
            .select("id, user_id, video_hash, result_json")
            .eq("status", "completed")
            .gte("completed_at", cutoff)
            .not_.is_("result_json", "null")
            .order("completed_at", desc=False)
            .limit(batch_size)
            .execute()
        )
        for job in resp.data or []:
            if time.monotonic() > deadline:
                stopped_early = True
                break
            result_json = job.get("result_json")
            if not result_json:
                skipped += 1
                continue
            try:
                maybe_refresh_segment_urls(result_json)  # Mutates in place
                job_id = job["id"]
                await _run_in_executor(
                    lambda jid=job_id, rj=result_json: client.table("jobs")
                    .update({"result_json": rj})
                    .eq("id", jid)
                    .execute()
                )
                refreshed_jobs += 1
                vh = job.get("video_hash")
                owner_id = job.get("user_id")
                if vh and owner_id:
                    owned_video_hashes.add((owner_id, vh))
            except Exception:
                logger.exception("[Jobs] refresh-screenshot-urls failed for job %s", job.get("id"))
                failed += 1
    except Exception:
        logger.exception("[Jobs] refresh-screenshot-urls: jobs query failed")

    # 2. Refresh image_embeddings.screenshot_url for the same video_hashes
    for owner_id, vh in owned_video_hashes:
        if time.monotonic() > deadline:
            stopped_early = True
            break
        try:
            rows_resp = await _run_in_executor(
                lambda uid=owner_id, v=vh: client.table("image_embeddings")
                .select("id, screenshot_url")
                .eq("user_id", uid)
                .eq("video_hash", v)
                .execute()
            )
            for row in rows_resp.data or []:
                url = row.get("screenshot_url")
                if not url or not url.startswith("https://storage.googleapis.com"):
                    continue
                gcs_path = gcs_service.extract_gcs_path_from_signed_url(url)
                if not gcs_path:
                    continue
                try:
                    new_url = gcs_service.generate_download_signed_url_resilient(
                        gcs_path, expiry_seconds=settings.GCS_SCREENSHOT_URL_EXPIRY
                    )
                    row_id = row["id"]
                    await _run_in_executor(
                        lambda uid=owner_id, rid=row_id, u=new_url: client.table("image_embeddings")
                        .update({"screenshot_url": u})
                        .eq("user_id", uid)
                        .eq("id", rid)
                        .execute()
                    )
                    refreshed_image_rows += 1
                except Exception:
                    logger.exception("[Jobs] image_embeddings refresh failed for path %s", gcs_path)
                    failed += 1
        except Exception:
            logger.exception("[Jobs] image_embeddings query failed for video_hash %s", vh)

    logger.info(
        "[Jobs] refresh-screenshot-urls done: jobs=%d image_rows=%d skipped=%d failed=%d "
        "cutoff_days=%d stopped_early=%s",
        refreshed_jobs, refreshed_image_rows, skipped, failed, cutoff_days, stopped_early,
    )

    return RefreshUrlsResponse(
        refreshed_jobs=refreshed_jobs,
        refreshed_image_rows=refreshed_image_rows,
        skipped=skipped,
        failed=failed,
        cutoff_days=cutoff_days,
    )


@router.post("/backfill-face-presence", response_model=BackfillFacePresenceResponse)
@require_admin
async def backfill_face_presence(
    request: Request,
    batch_size: int = Query(10, ge=1, le=50, description="Maximum videos to backfill in one invocation"),
    video_hash: Optional[str] = Query(None, description="Backfill exactly this video instead of scanning for missing ones"),
    user_id: Optional[str] = Query(None, description="Owner required when targeting a video hash"),
    force: bool = Query(False, description="Re-index even if the video already has face presence rows"),
):
    """Backfill image_face_presence rows for videos that already have image embeddings.

    By default scans `videos_missing_face_presence` for a batch. Pass `video_hash`
    to target one specific video (e.g. a film processed before face indexing
    existed), optionally with `force=true` to re-index over existing rows.
    """
    from services.image_embedding_service import image_embedding_service
    from services.supabase_service import supabase

    client = supabase()
    processed_videos = 0
    indexed_face_rows = 0
    skipped = 0
    failed = 0

    candidate_videos: list[tuple[str, str]] = []
    if video_hash:
        if not user_id:
            raise HTTPException(status_code=400, detail="user_id is required with video_hash")
        candidate_videos = [(user_id, video_hash)]
    else:
        try:
            rows_resp = await _run_in_executor(
                lambda: client.rpc(
                    "videos_missing_face_presence",
                    {"batch_limit": batch_size},
                ).execute()
            )
            for row in rows_resp.data or []:
                vh = row.get("video_hash")
                owner_id = row.get("user_id")
                candidate = (owner_id, vh)
                if owner_id and vh and candidate not in candidate_videos:
                    candidate_videos.append(candidate)
        except Exception:
            logger.exception("[Jobs] backfill-face-presence: videos_missing_face_presence RPC failed")
            return BackfillFacePresenceResponse(
                processed_videos=0,
                indexed_face_rows=0,
                skipped=0,
                failed=1,
                batch_size=batch_size,
            )

    for owner_id, vh in candidate_videos:
        if processed_videos >= batch_size:
            break
        try:
            if not force:
                existing = await _run_in_executor(
                    lambda uid=owner_id, v=vh: client.table("image_face_presence")
                    .select("id")
                    .eq("user_id", uid)
                    .eq("video_hash", v)
                    .limit(1)
                    .execute()
                )
                if existing.data:
                    skipped += 1
                    continue

            count = await _run_in_executor(
                image_embedding_service.index_face_presence_for_video,
                vh,
                owner_id,
                force,
            )
            processed_videos += 1
            indexed_face_rows += count
        except Exception:
            logger.exception("[Jobs] backfill-face-presence failed for video_hash %s", vh)
            failed += 1

    logger.info(
        "[Jobs] backfill-face-presence done: videos=%d rows=%d skipped=%d failed=%d batch_size=%d",
        processed_videos,
        indexed_face_rows,
        skipped,
        failed,
        batch_size,
    )

    return BackfillFacePresenceResponse(
        processed_videos=processed_videos,
        indexed_face_rows=indexed_face_rows,
        skipped=skipped,
        failed=failed,
        batch_size=batch_size,
    )


@router.post("/backfill-captions", response_model=BackfillCaptionsResponse)
@require_admin
async def backfill_captions(
    request: Request,
    batch_size: int = Query(3, ge=1, le=10, description="Maximum videos to caption in one invocation"),
    video_hash: Optional[str] = Query(None, description="Caption exactly this video instead of scanning for missing ones"),
    force: bool = Query(False, description="Re-caption rows that already have captions"),
    dense: bool = Query(True, description="Also sample dense frames if the source video still exists"),
):
    """Backfill xAI vision captions (and optionally dense frames) for videos that
    already have image embeddings.

    Dense sampling degrades gracefully: if the source video was lifecycle-deleted
    from storage, only the existing screenshots are captioned. Dense-frame
    indexing runs with face_force=False so it never wipes existing face rows
    (dense frames simply get no face-presence entries on backfill).
    """
    import tempfile as _tempfile
    from services.image_embedding_service import image_embedding_service
    from services.supabase_service import supabase
    from services.gcs_service import gcs_service
    from services.video_service import VideoService
    from services.background_worker import _compute_dense_timestamps
    from routers.chat import _get_saved_provider_key

    client = supabase()
    processed_videos = 0
    captioned_images = 0
    dense_frames_added = 0
    skipped = 0
    failed = 0

    candidate_hashes: list[str] = []
    if video_hash:
        candidate_hashes = [video_hash]
    else:
        try:
            rows_resp = await _run_in_executor(
                lambda: client.rpc(
                    "videos_missing_captions",
                    {"batch_limit": batch_size},
                ).execute()
            )
            for row in rows_resp.data or []:
                vh = row.get("video_hash")
                if vh and vh not in candidate_hashes:
                    candidate_hashes.append(vh)
        except Exception:
            logger.exception("[Jobs] backfill-captions: videos_missing_captions RPC failed")
            return BackfillCaptionsResponse(
                processed_videos=0,
                captioned_images=0,
                dense_frames_added=0,
                skipped=0,
                failed=1,
                batch_size=batch_size,
            )

    for vh in candidate_hashes:
        if processed_videos >= batch_size:
            break
        collected: list = []
        try:
            rows = await _run_in_executor(
                lambda v=vh: client.table("image_embeddings")
                .select("segment_id, caption, start_time, end_time")
                .eq("video_hash", v)
                .execute()
            )
            all_rows = rows.data or []
            pending = [r for r in all_rows if r.get("caption") is None]

            job_user_id = None
            gcs_path = None
            try:
                job_resp = await _run_in_executor(
                    lambda v=vh: client.table("jobs")
                    .select("gcs_path, user_id, result_json")
                    .eq("video_hash", v)
                    .limit(1)
                    .execute()
                )
                if job_resp.data:
                    job_row = job_resp.data[0]
                    job_user_id = job_row.get("user_id")
                    gcs_path = job_row.get("gcs_path") or (job_row.get("result_json") or {}).get("gcs_path")
            except Exception:
                logger.warning("[Jobs] backfill-captions: job lookup failed for %s", vh)

            video_dense_frames = 0
            if dense and all_rows and gcs_path:
                try:
                    if gcs_service.file_exists(gcs_path):
                        duration = max((r.get("end_time") or 0) for r in all_rows)
                        existing_ts = [r.get("start_time") or 0 for r in all_rows]
                        dense_ts = _compute_dense_timestamps(
                            duration,
                            existing_ts,
                            settings.DENSE_FRAME_INTERVAL_SECONDS,
                            settings.DENSE_FRAME_MIN_GAP_SECONDS,
                        )
                        if dense_ts:
                            read_url = gcs_service.generate_download_signed_url(gcs_path)
                            screenshots_dir = os.path.join("static", "screenshots")
                            os.makedirs(screenshots_dir, exist_ok=True)
                            dense_results = await _run_in_executor(
                                VideoService.extract_screenshots_parallel_from_url,
                                source_url=read_url,
                                timestamps=dense_ts,
                                output_dir=screenshots_dir,
                                video_hash=vh,
                                max_workers=4,
                            )
                            dense_urls = gcs_service.upload_screenshots_batch(
                                screenshot_paths=dense_results,
                                video_hash=vh,
                            )
                            dense_segments = [
                                {
                                    "id": f"dense_{ts:.2f}",
                                    "start": ts,
                                    "end": ts,
                                    "speaker": None,
                                    "screenshot_url": url,
                                }
                                for ts, url in ((ts, dense_urls.get(ts)) for ts in dense_ts)
                                if url
                            ]
                            for local_path in dense_results.values():
                                if local_path and os.path.exists(local_path):
                                    try:
                                        os.unlink(local_path)
                                    except Exception:
                                        pass
                            if dense_segments:
                                await _run_in_executor(
                                    image_embedding_service.index_video_images,
                                    vh,
                                    dense_segments,
                                    force_reindex=True,
                                    user_id=job_user_id,
                                    collect_segments=collected,
                                    face_force=False,
                                )
                                video_dense_frames = len(dense_segments)
                                dense_frames_added += video_dense_frames
                    else:
                        logger.info(
                            "[Jobs] backfill-captions: source video gone for %s; "
                            "captioning existing screenshots only", vh
                        )
                except Exception:
                    logger.exception("[Jobs] backfill-captions: dense sampling failed for %s", vh)

            if not force and not pending and video_dense_frames == 0:
                skipped += 1
                continue

            api_key = None
            try:
                api_key = await _get_saved_provider_key(job_user_id, "xai")
            except Exception:
                pass

            captioned = await image_embedding_service.caption_video_images(
                vh,
                segments=collected or None,
                api_key=api_key,
                force=force,
            )
            processed_videos += 1
            captioned_images += captioned
        except Exception:
            logger.exception("[Jobs] backfill-captions failed for video_hash %s", vh)
            failed += 1
        finally:
            for seg in collected:
                local_path = seg.get("local_path")
                if local_path and local_path.startswith(_tempfile.gettempdir()):
                    try:
                        os.unlink(local_path)
                    except Exception:
                        pass

    logger.info(
        "[Jobs] backfill-captions done: videos=%d captions=%d dense=%d skipped=%d failed=%d",
        processed_videos,
        captioned_images,
        dense_frames_added,
        skipped,
        failed,
    )

    return BackfillCaptionsResponse(
        processed_videos=processed_videos,
        captioned_images=captioned_images,
        dense_frames_added=dense_frames_added,
        skipped=skipped,
        failed=failed,
        batch_size=batch_size,
    )


@router.get("/{job_id}/download/{format}")
async def download_result(
    job_id: str,
    format: str,
    token: Optional[str] = Query(None, description="Access token for this job")
):
    """
    Download job result in specified format.

    Supported formats:
    - **srt**: SubRip subtitle format
    - **vtt**: WebVTT subtitle format
    - **json**: Full transcription data as JSON

    Args:
        job_id: The unique job identifier
        format: Output format (srt, vtt, or json)
        token: Access token (query parameter)

    Returns:
        File download with appropriate Content-Disposition header

    Raises:
        400: Invalid format, job not completed, or token missing
        403: Invalid token
        404: Job not found
    """
    # Validate format
    if format not in ['srt', 'vtt', 'json']:
        raise HTTPException(
            status_code=400,
            detail="Invalid format. Must be one of: srt, vtt, json"
        )

    # Verify access
    require_token(job_id, token)

    try:
        from services.job_queue_service import JobQueueService

        # Get job
        job = JobQueueService.get_job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")

        # Check if completed
        if job['status'] != 'completed':
            raise HTTPException(
                status_code=400,
                detail=f"Job is not completed (current status: {job['status']})"
            )

        # Get the appropriate result
        if format == 'srt':
            content = job.get('result_srt')
            media_type = "application/x-subrip"
            filename = f"{job['filename']}.srt"
        elif format == 'vtt':
            content = job.get('result_vtt')
            media_type = "text/vtt"
            filename = f"{job['filename']}.vtt"
        else:  # json
            import json
            content = json.dumps(job.get('result_json'), indent=2)
            media_type = "application/json"
            filename = f"{job['filename']}.json"

        if not content:
            raise HTTPException(
                status_code=404,
                detail=f"Result in {format} format not available"
            )

        return Response(
            content=content,
            media_type=media_type,
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"'
            }
        )

    except HTTPException:
        raise
    except Exception as e:
        print(f"[Jobs] Error downloading result: {e}")
        raise HTTPException(status_code=500, detail="Failed to download result")


@router.get("/{job_id}/video")
async def stream_job_video(
    job_id: str,
    token: Optional[str] = Query(None, description="Access token for this job")
):
    """
    Stream the video file for a completed job.

    Generates a signed URL for the video stored in GCS and redirects to it.
    The signed URL is valid for 1 hour.

    Args:
        job_id: The unique job identifier
        token: Access token (query parameter)

    Returns:
        Redirect to signed GCS URL for video streaming

    Raises:
        400: Job not completed or token missing
        403: Invalid token
        404: Job not found or video not available
    """
    from fastapi.responses import RedirectResponse

    # Verify access
    require_token(job_id, token)

    try:
        from services.job_queue_service import JobQueueService

        # Get job
        job = JobQueueService.get_job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")

        # Check if completed
        if job['status'] != 'completed':
            raise HTTPException(
                status_code=400,
                detail=f"Job is not completed (current status: {job['status']})"
            )

        # Get GCS path from result
        result_json = job.get('result_json')
        if not result_json:
            raise HTTPException(status_code=404, detail="Job result not available")

        gcs_path = result_json.get('gcs_path')
        if not gcs_path:
            raise HTTPException(status_code=404, detail="Video file path not found in job result")

        # Verify file exists in GCS
        media_storage = get_media_storage()
        if not media_storage.file_exists(gcs_path):
            raise HTTPException(status_code=404, detail="Video file not found in storage")

        # Generate signed URL (valid for 1 hour)
        signed_url = media_storage.generate_download_url(gcs_path, expiry_seconds=3600)

        print(f"[Jobs] Generated video stream URL for job {job_id}")

        # Redirect to signed URL
        return RedirectResponse(url=signed_url, status_code=302)

    except HTTPException:
        raise
    except Exception as e:
        print(f"[Jobs] Error streaming video: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Failed to stream video")


@router.get("/{job_id}/video_url")
@optional_auth
async def get_job_video_url(
    request: Request,
    job_id: str,
    token: Optional[str] = Query(None, description="Access token for this job (optional if authenticated)")
):
    """
    Return a short-lived signed GCS URL for the job's video.

    Authorization: either a valid per-job access token, or an authenticated
    user who owns the job. Returns JSON so the frontend can plug the signed
    URL directly into a `<video>` tag.
    """

    user = getattr(request.state, "user", None)
    user_id = user["id"] if user else None

    job = require_job_access(job_id, token, user_id)

    if job.get("status") != "completed":
        raise HTTPException(
            status_code=400,
            detail=f"Job is not completed (current status: {job.get('status')})"
        )

    result_json = job.get("result_json") or {}
    gcs_path = job.get("gcs_path") or result_json.get("gcs_path")
    if not gcs_path:
        raise HTTPException(status_code=404, detail="Video file path not found in job result")

    try:
        media_storage = get_media_storage()
        if not media_storage.file_exists(gcs_path):
            raise HTTPException(status_code=404, detail="Video file not found in storage")

        signed_url = media_storage.generate_download_url(
            gcs_path, expiry_seconds=settings.GCS_DOWNLOAD_URL_EXPIRY
        )
    except HTTPException:
        raise
    except Exception as e:
        print(f"[Jobs] Error generating signed URL for job {job_id}: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Failed to generate video URL")

    return {"download_url": signed_url, "expires_in": settings.GCS_DOWNLOAD_URL_EXPIRY}


@router.get("/{job_id}/screenshot_url")
@optional_auth
async def get_job_screenshot_url(
    request: Request,
    job_id: str,
    gcs_path: str = Query(..., description="GCS object path of the screenshot to re-sign"),
    token: Optional[str] = Query(None, description="Access token for this job (optional if authenticated)")
):
    """
    Return a short-lived signed GCS URL for a specific screenshot belonging to this job.

    Authorization: either a valid per-job access token, or an authenticated
    user who owns the job. The gcs_path must reside under the screenshots prefix
    and its video_hash segment must match the job's own video_hash, preventing
    cross-job URL theft via a leaked token.
    """
    user = getattr(request.state, "user", None)
    user_id = user["id"] if user else None

    job = require_job_access(job_id, token, user_id)

    storage = get_media_storage()
    object_key = storage.parse_screenshot_key(gcs_path)
    job_video_hash = job.get("video_hash")
    job_user_id = job.get("user_id")
    from services.transcription_repository import transcription_repository
    allow_legacy = bool(
        job_video_hash
        and job_user_id
        and transcription_repository.hash_resources_are_owner_exclusive(
            job_video_hash, job_user_id
        )
    )
    if (
        not object_key
        or not job_video_hash
        or not job_user_id
        or not storage.is_owned_screenshot_key(
            object_key, job_user_id, job_video_hash, allow_legacy=allow_legacy
        )
    ):
        raise HTTPException(
            status_code=403,
            detail="gcs_path does not belong to this job"
        )

    try:
        signed_url = storage.generate_download_url(
            object_key, expiry_seconds=settings.GCS_SCREENSHOT_URL_EXPIRY
        )
    except Exception as e:
        print(f"[Jobs] Error generating screenshot signed URL for job {job_id}: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Failed to generate screenshot URL")

    return {"download_url": signed_url, "expires_in": settings.GCS_SCREENSHOT_URL_EXPIRY}
