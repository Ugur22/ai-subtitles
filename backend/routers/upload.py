"""
Upload endpoints for GCS-based large file uploads.

These endpoints enable direct-to-GCS uploads which bypass Cloud Run's 32MB request limit.
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

from config import settings


router = APIRouter(prefix="/api/upload", tags=["Upload"])


class SignedUrlRequest(BaseModel):
    """Request for a signed upload URL."""
    filename: str
    content_type: str = "video/mp4"
    file_size: Optional[int] = None  # Size in bytes for choosing upload method


class SignedUrlResponse(BaseModel):
    """Response containing signed URL for upload."""
    upload_url: str
    gcs_path: str
    method: str  # "PUT" for simple, "POST" for resumable
    expires_in: int  # seconds


class UploadStatusResponse(BaseModel):
    """Response for upload status check."""
    exists: bool
    size: int  # bytes
    gcs_path: str


@router.post("/signed-url", response_model=SignedUrlResponse)
async def get_signed_upload_url(request: SignedUrlRequest):
    """
    Get a signed URL for uploading a file directly to GCS.

    This bypasses Cloud Run's 32MB limit by letting the browser upload
    directly to Google Cloud Storage.

    For files < 100MB: Returns a simple PUT URL
    For files >= 100MB: Returns a resumable upload URL

    Args:
        request: Contains filename, content_type, and optional file_size

    Returns:
        SignedUrlResponse with upload URL and GCS path
    """
    if not settings.ENABLE_GCS_UPLOADS:
        raise HTTPException(
            status_code=503,
            detail="GCS uploads are not enabled. Use direct upload for files < 32MB."
        )

    try:
        from services.gcs_service import gcs_service

        # Determine upload method based on file size
        file_size = request.file_size or 0
        threshold = 100 * 1024 * 1024  # 100MB

        if file_size >= threshold:
            # Use resumable upload for large files
            upload_url, gcs_path = gcs_service.generate_resumable_upload_url(
                filename=request.filename,
                content_type=request.content_type,
            )
            method = "POST"
        else:
            # Use simple signed URL for smaller files
            upload_url, gcs_path = gcs_service.generate_upload_signed_url(
                filename=request.filename,
                content_type=request.content_type,
            )
            method = "PUT"

        return SignedUrlResponse(
            upload_url=upload_url,
            gcs_path=gcs_path,
            method=method,
            expires_in=settings.GCS_SIGNED_URL_EXPIRY,
        )

    except Exception as e:
        print(f"[Upload] Error generating signed URL: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Failed to generate upload URL: {str(e)}")


@router.post("/resumable-url", response_model=SignedUrlResponse)
async def get_resumable_upload_url(request: SignedUrlRequest):
    """
    Get a resumable upload URL for very large files.

    Resumable uploads support:
    - Pause and resume
    - Automatic retry on network failures
    - Progress tracking via Content-Range headers

    Use this for files > 100MB.
    """
    if not settings.ENABLE_GCS_UPLOADS:
        raise HTTPException(
            status_code=503,
            detail="GCS uploads are not enabled."
        )

    try:
        from services.gcs_service import gcs_service

        upload_url, gcs_path = gcs_service.generate_resumable_upload_url(
            filename=request.filename,
            content_type=request.content_type,
        )

        return SignedUrlResponse(
            upload_url=upload_url,
            gcs_path=gcs_path,
            method="POST",
            expires_in=settings.GCS_SIGNED_URL_EXPIRY,
        )

    except Exception as e:
        print(f"[Upload] Error generating resumable URL: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to generate upload URL: {str(e)}")


@router.get("/status/{gcs_path:path}", response_model=UploadStatusResponse)
async def check_upload_status(gcs_path: str):
    """
    Check if a file was successfully uploaded to GCS.

    Args:
        gcs_path: The GCS path returned from signed-url endpoint

    Returns:
        UploadStatusResponse with exists flag and file size
    """
    if not settings.ENABLE_GCS_UPLOADS:
        raise HTTPException(status_code=503, detail="GCS uploads are not enabled.")

    try:
        from services.gcs_service import gcs_service

        exists = gcs_service.file_exists(gcs_path)
        size = gcs_service.get_file_size(gcs_path) if exists else 0

        return UploadStatusResponse(
            exists=exists,
            size=size,
            gcs_path=gcs_path,
        )

    except Exception as e:
        print(f"[Upload] Error checking status: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to check upload status: {str(e)}")


@router.get("/config")
async def get_upload_config():
    """
    Get client-side upload configuration.

    Returns information about upload limits and GCS availability.
    """
    return {
        "gcs_enabled": settings.ENABLE_GCS_UPLOADS,
        "direct_upload_limit": 32 * 1024 * 1024,  # 32MB Cloud Run limit
        "gcs_bucket": settings.GCS_BUCKET_NAME if settings.ENABLE_GCS_UPLOADS else None,
        "max_file_size": 10 * 1024 * 1024 * 1024,  # 10GB
    }
