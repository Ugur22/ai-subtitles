"""
Jobs API router for background job processing system.

This router provides endpoints for managing asynchronous transcription jobs,
allowing users to submit videos, track progress, and retrieve results without
maintaining an active connection.
"""
from fastapi import APIRouter, HTTPException, BackgroundTasks, Query
from fastapi.responses import Response
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime

from config import settings


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


# =============================================================================
# Endpoints
# =============================================================================

@router.post("/submit", response_model=JobSubmitResponse)
async def submit_job(
    request: JobSubmitRequest,
    background_tasks: BackgroundTasks
):
    """
    Submit a new transcription job.

    The job will be queued for background processing. Returns immediately with
    job_id and access_token for tracking progress.

    **Queue Limit**: Maximum 3 concurrent jobs globally. Returns 429 if queue is full.

    **Deduplication**: If a job with the same video_hash was already completed,
    returns the cached result immediately.

    Args:
        request: Job parameters including file info and transcription settings
        background_tasks: FastAPI background tasks for async processing

    Returns:
        JobSubmitResponse with job_id, access_token, and cache status

    Raises:
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

    try:
        # Create job (checks queue limit and deduplication)
        result = JobQueueService.create_job(
            filename=request.filename,
            gcs_path=request.gcs_path,
            file_size_bytes=request.file_size_bytes,
            video_hash=request.video_hash,
            num_speakers=request.num_speakers,
            min_speakers=request.min_speakers,
            max_speakers=request.max_speakers,
            language=request.language,
            force_language=request.force_language
        )

        # If not cached, trigger background processing
        if not result.get('cached', False):
            background_tasks.add_task(
                background_worker.process_job,
                result['id']
            )

            # Get estimated duration if available
            estimated_duration = JobQueueService.get_estimated_duration(
                request.file_size_bytes
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
async def get_job_status(
    job_id: str,
    token: Optional[str] = Query(None, description="Access token for this job")
):
    """
    Get detailed status for a specific job.

    Requires the access token that was returned when the job was submitted.

    Args:
        job_id: The unique job identifier
        token: Access token (query parameter)

    Returns:
        JobStatusResponse with complete job details

    Raises:
        400: Token missing
        403: Invalid token
        404: Job not found
    """
    # Verify access
    require_token(job_id, token)

    try:
        from services.job_queue_service import JobQueueService

        job = JobQueueService.get_job(job_id)

        if not job:
            raise HTTPException(status_code=404, detail="Job not found")

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
async def list_jobs(
    tokens: str = Query(..., description="Comma-separated access tokens"),
    page: int = Query(1, ge=1, description="Page number (1-indexed)"),
    per_page: int = Query(10, ge=1, le=50, description="Items per page (max 50)")
):
    """
    List jobs that the user has access to.

    Takes a comma-separated list of access tokens (from localStorage) and returns
    all matching jobs with pagination.

    Args:
        tokens: Comma-separated access tokens
        page: Page number (1-indexed)
        per_page: Items per page (max 50)

    Returns:
        JobListResponse with paginated job list
    """
    try:
        from services.job_queue_service import JobQueueService

        # Parse tokens
        token_list = [t.strip() for t in tokens.split(',') if t.strip()]

        if not token_list:
            return JobListResponse(jobs=[], total=0, page=page, per_page=per_page)

        # Get jobs for these tokens
        result = JobQueueService.get_jobs_by_tokens(
            tokens=token_list,
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
async def cancel_job(
    job_id: str,
    token: Optional[str] = Query(None, description="Access token for this job")
):
    """
    Cancel a pending job.

    Only pending jobs can be cancelled. Jobs that are already processing or
    completed cannot be cancelled.

    Args:
        job_id: The unique job identifier
        token: Access token (query parameter)

    Returns:
        JobCancelResponse with cancellation status

    Raises:
        400: Job cannot be cancelled (not pending) or token missing
        403: Invalid token
        404: Job not found
    """
    # Verify access
    require_token(job_id, token)

    try:
        from services.job_queue_service import JobQueueService

        # Check job exists
        job = JobQueueService.get_job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")

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
async def retry_job(
    job_id: str,
    token: Optional[str] = Query(None, description="Access token for this job"),
    background_tasks: BackgroundTasks = None
):
    """
    Retry a failed job with the same settings.

    Resets the job to pending status and re-queues it for processing.
    Settings cannot be modified during retry - use a new job submission to change settings.

    Args:
        job_id: The unique job identifier
        token: Access token (query parameter)
        background_tasks: FastAPI background tasks for async processing

    Returns:
        JobRetryResponse with retry status

    Raises:
        400: Job is not in failed status or token missing
        403: Invalid token
        404: Job not found
    """
    # Verify access
    require_token(job_id, token)

    try:
        from services.job_queue_service import JobQueueService
        from services.background_worker import background_worker

        # Check job exists and is failed
        job = JobQueueService.get_job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")

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


@router.get("/{job_id}/share", response_model=ShareLinkResponse)
async def get_share_link(
    job_id: str,
    token: Optional[str] = Query(None, description="Access token for this job")
):
    """
    Generate a shareable link for a job.

    The link includes the access token, allowing anyone with the link to view
    the job status and results.

    **Security Note**: Anyone with this link can access the job. Only share with
    trusted parties.

    Args:
        job_id: The unique job identifier
        token: Access token (query parameter)

    Returns:
        ShareLinkResponse with shareable URL

    Raises:
        400: Token missing
        403: Invalid token
        404: Job not found
    """
    # Verify access
    require_token(job_id, token)

    try:
        from services.job_queue_service import JobQueueService

        # Verify job exists
        job = JobQueueService.get_job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")

        # Generate shareable URL
        # Note: In production, this would use the actual frontend URL from settings
        base_url = "https://REDACTED_FRONTEND_URL"  # TODO: Get from settings
        share_url = f"{base_url}/jobs/{job_id}?token={token}"

        return ShareLinkResponse(share_url=share_url)

    except HTTPException:
        raise
    except Exception as e:
        print(f"[Jobs] Error generating share link: {e}")
        raise HTTPException(status_code=500, detail="Failed to generate share link")


@router.post("/check-stale", response_model=StaleJobCheckResponse)
async def check_stale_jobs(background_tasks: BackgroundTasks):
    """
    Check for and recover stale jobs (internal endpoint).

    This endpoint is called by Cloud Scheduler every 5 minutes to detect jobs
    that are stuck in 'processing' state due to worker crashes.

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
