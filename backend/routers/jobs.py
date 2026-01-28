"""
Jobs API router for background job processing system.

This router provides endpoints for managing asynchronous transcription jobs,
allowing users to submit videos, track progress, and retrieve results without
maintaining an active connection.
"""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Optional, List, Callable, Any
from datetime import datetime

from fastapi import APIRouter, HTTPException, BackgroundTasks, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel

from config import settings
from middleware.auth import require_auth, require_admin


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
        from services.background_worker import background_worker
    except ImportError:
        raise HTTPException(
            status_code=503,
            detail="Job queue service not available. Background processing not configured."
        )

    # Get authenticated user ID
    user_id = request.state.user["id"]

    try:
        # Create job (checks queue limit and deduplication)
        result = JobQueueService.create_job(
            filename=job_request.filename,
            gcs_path=job_request.gcs_path,
            file_size_bytes=job_request.file_size_bytes,
            video_hash=job_request.video_hash,
            user_id=user_id,  # Associate job with authenticated user
            num_speakers=job_request.num_speakers,
            min_speakers=job_request.min_speakers,
            max_speakers=job_request.max_speakers,
            language=job_request.language,
            force_language=job_request.force_language
        )

        # If not cached, trigger background processing
        if not result.get('cached', False):
            background_tasks.add_task(
                background_worker.process_job,
                result['id']
            )

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
            result_json=job.get('result_json'),
            result_srt=job.get('result_srt'),
            result_vtt=job.get('result_vtt'),
            created_at=job['created_at'],
            started_at=job.get('started_at'),
            completed_at=job.get('completed_at'),
            cached=job.get('cached'),
            cached_at=job.get('cached_at')
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
    page: int = Query(1, ge=1, description="Page number (1-indexed)"),
    per_page: int = Query(10, ge=1, le=50, description="Items per page (max 50)")
):
    """
    List jobs belonging to the authenticated user.

    Returns all jobs owned by the current user with pagination.

    **Authentication**: Requires authenticated user session.

    Args:
        request: FastAPI request with authenticated user
        page: Page number (1-indexed)
        per_page: Items per page (max 50)

    Returns:
        JobListResponse with paginated job list
    """
    try:
        from services.job_queue_service import JobQueueService

        # Get authenticated user ID
        user_id = request.state.user["id"]

        # Get jobs for this user (run in executor to avoid blocking during GPU processing)
        result = await _run_in_executor(
            JobQueueService.get_jobs_for_user,
            user_id=user_id,
            page=page,
            per_page=per_page
        )
        jobs = result['jobs']
        total = result['total']

        # Map jobs to response format
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
                cached_at=job.get('cached_at')
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
    Cancel a pending job.

    Only pending jobs can be cancelled. Jobs that are already processing or
    completed cannot be cancelled.

    Access granted via ownership OR token.

    Args:
        request: FastAPI request with authenticated user
        job_id: The unique job identifier
        token: Optional access token (for shared links)

    Returns:
        JobCancelResponse with cancellation status

    Raises:
        400: Job cannot be cancelled (not pending)
        401: Not authenticated
        403: Not owner and no valid token
        404: Job not found
    """
    # Get authenticated user ID
    user_id = request.state.user["id"]

    # Verify access via ownership OR token (also fetches job)
    job = require_job_access(job_id, token, user_id)

    try:
        from services.job_queue_service import JobQueueService

        # Check if job can be cancelled
        if job['status'] != 'pending':
            raise HTTPException(
                status_code=400,
                detail=f"Cannot cancel job with status '{job['status']}'. Only pending jobs can be cancelled."
            )

        # Cancel the job
        success = JobQueueService.cancel_job(job_id)

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
    job = require_job_access(job_id, token, user_id)

    try:
        from services.job_queue_service import JobQueueService
        from services.background_worker import background_worker

        if job['status'] != 'failed':
            raise HTTPException(
                status_code=400,
                detail=f"Cannot retry job with status '{job['status']}'. Only failed jobs can be retried."
            )

        # Retry the job
        success = JobQueueService.retry_job(job_id)

        if not success:
            raise HTTPException(status_code=500, detail="Failed to retry job")

        # Trigger background processing
        if background_tasks:
            background_tasks.add_task(background_worker.process_job, job_id)

        return JobRetryResponse(
            job_id=job_id,
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
    from services.gcs_service import gcs_service
    from services.job_queue_service import JobQueueService
    from services.supabase_service import supabase

    # Get authenticated user ID
    user_id = request.state.user["id"]

    # Verify access via ownership OR token (also fetches job)
    job = require_job_access(job_id, token, user_id)

    try:
        deleted_resources = {
            "video": False,
            "screenshots": 0,
            "database": False
        }

        # Extract video path from video_url if available
        video_path = None
        video_url = job.get('video_url')
        if video_url:
            # video_url is a signed URL like:
            # https://storage.googleapis.com/bucket/path/to/file?signature...
            # Extract the path after the bucket name
            try:
                # Parse GCS path from signed URL
                import re
                # Pattern: bucket-name/path/to/file
                match = re.search(r'/([^/]+/[^?]+)', video_url)
                if match:
                    full_path = match.group(1)
                    # Remove bucket name (first segment)
                    parts = full_path.split('/', 1)
                    if len(parts) > 1:
                        video_path = parts[1]
                        print(f"[Jobs] Extracted video path: {video_path}")
            except Exception as e:
                print(f"[Jobs] Failed to extract video path from URL: {e}")

        # Alternatively, try to get from result_json.gcs_path
        if not video_path and job.get('result_json'):
            video_path = job['result_json'].get('gcs_path')
            if video_path:
                print(f"[Jobs] Using video path from result_json: {video_path}")

        # Delete video file from GCS if path exists (non-blocking)
        if video_path:
            deleted_resources["video"] = await _run_in_executor(gcs_service.delete_file, video_path)

        # Delete screenshots folder from GCS if video_hash exists (non-blocking)
        video_hash = job.get('video_hash')
        if video_hash:
            screenshots_prefix = f"screenshots/{video_hash}/"
            deleted_count = await _run_in_executor(gcs_service.delete_folder, screenshots_prefix)
            deleted_resources["screenshots"] = deleted_count

        # Delete job record from Supabase (non-blocking)
        try:
            client = supabase()
            await _run_in_executor(lambda: client.table("jobs").delete().eq("id", job_id).execute())
            deleted_resources["database"] = True
            print(f"[Jobs] Deleted job record from database: {job_id}")
        except Exception as e:
            print(f"[Jobs] Failed to delete job from database: {e}")
            raise HTTPException(
                status_code=500,
                detail=f"Failed to delete job from database: {str(e)}"
            )

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
            "deleted_resources": deleted_resources
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
    job = require_job_access(job_id, token, user_id)

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
    Check for and recover stale jobs (admin-only endpoint).

    This endpoint is called by Cloud Scheduler every 5 minutes to detect jobs
    that are stuck in 'processing' state due to worker crashes.
    Requires admin authentication to prevent unauthorized access.

    **Stale Detection**: Jobs with no heartbeat for 90+ seconds
    **Recovery**: Resets to pending and auto-retries (max 3 attempts)
    **Rate Limit**: Processes one stale job per call

    Returns:
        StaleJobCheckResponse with number of jobs processed
    """
    try:
        from services.job_queue_service import JobQueueService

        processed = JobQueueService.check_and_recover_stale_jobs()

        message = "No stale jobs found" if processed == 0 else f"Recovered {processed} stale job(s)"

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
    from services.gcs_service import gcs_service

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
        if not gcs_service.file_exists(gcs_path):
            raise HTTPException(status_code=404, detail="Video file not found in storage")

        # Generate signed URL (valid for 1 hour)
        signed_url = gcs_service.generate_download_signed_url(gcs_path, expiry_seconds=3600)

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
