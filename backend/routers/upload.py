"""
Upload endpoints for GCS-based large file uploads.

These endpoints enable direct-to-GCS uploads which bypass Cloud Run's 32MB request limit.
"""
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from typing import Optional

from config import settings
from middleware.auth import require_auth


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
@require_auth
async def get_signed_upload_url(request: Request, body: SignedUrlRequest):
    """
    Get a signed URL for uploading a file directly to GCS.

    This bypasses Cloud Run's 32MB limit by letting the browser upload
    directly to Google Cloud Storage.

    For files < 100MB: Returns a simple PUT URL
    For files >= 100MB: Returns a resumable upload URL

    Args:
        request: FastAPI request object (injected by require_auth)
        body: Contains filename, content_type, and optional file_size

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
        file_size = body.file_size or 0
        threshold = 100 * 1024 * 1024  # 100MB

        if settings.LOCAL_MODE:
            # Local uploads have no size limit and no resumable protocol —
            # always a plain PUT to this server.
            upload_url, gcs_path = gcs_service.generate_upload_signed_url(
                filename=body.filename,
                content_type=body.content_type,
            )
            method = "PUT"
        elif file_size >= threshold:
            # Use resumable upload for large files
            upload_url, gcs_path = gcs_service.generate_resumable_upload_url(
                filename=body.filename,
                content_type=body.content_type,
            )
            method = "POST"
        else:
            # Use simple signed URL for smaller files
            upload_url, gcs_path = gcs_service.generate_upload_signed_url(
                filename=body.filename,
                content_type=body.content_type,
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
@require_auth
async def get_resumable_upload_url(request: Request, body: SignedUrlRequest):
    """
    Get a resumable upload URL for very large files.

    Resumable uploads support:
    - Pause and resume
    - Automatic retry on network failures
    - Progress tracking via Content-Range headers

    Use this for files > 100MB.

    Args:
        request: FastAPI request object (injected by require_auth)
        body: Contains filename, content_type, and optional file_size
    """
    if not settings.ENABLE_GCS_UPLOADS:
        raise HTTPException(
            status_code=503,
            detail="GCS uploads are not enabled."
        )

    try:
        from services.gcs_service import gcs_service

        upload_url, gcs_path = gcs_service.generate_resumable_upload_url(
            filename=body.filename,
            content_type=body.content_type,
        )

        return SignedUrlResponse(
            upload_url=upload_url,
            gcs_path=gcs_path,
            # Local mode has no resumable protocol — the URL is a plain PUT
            method="PUT" if settings.LOCAL_MODE else "POST",
            expires_in=settings.GCS_SIGNED_URL_EXPIRY,
        )

    except Exception as e:
        print(f"[Upload] Error generating resumable URL: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to generate upload URL: {str(e)}")


@router.put("/local/{upload_id}/{filename}")
async def upload_local_file(request: Request, upload_id: str, filename: str):
    """
    LOCAL_MODE: receive the file the browser would otherwise PUT to a GCS
    signed URL, streaming it to {LOCAL_DATA_DIR}/uploads/.

    No cookie auth on purpose — this mirrors GCS signed-URL semantics where the
    unguessable URL (the random upload_id issued by /signed-url) is the
    capability. The XHR PUT in the frontend sends no credentials.
    """
    if not settings.LOCAL_MODE:
        raise HTTPException(status_code=404, detail="Not found")

    import os
    import re

    if not re.fullmatch(r"[0-9a-f-]{36}", upload_id):
        raise HTTPException(status_code=400, detail="Invalid upload id")
    safe_filename = os.path.basename(filename).replace(" ", "_")

    from services.local_storage_service import LocalStorageService

    uploads_dir = LocalStorageService._uploads_dir()
    os.makedirs(uploads_dir, exist_ok=True)
    dest = os.path.join(uploads_dir, f"{upload_id}_{safe_filename}")

    size = 0
    try:
        with open(dest, "wb") as f:
            async for chunk in request.stream():
                f.write(chunk)
                size += len(chunk)
    except Exception as e:
        if os.path.exists(dest):
            os.unlink(dest)
        raise HTTPException(status_code=500, detail=f"Upload failed: {e}")

    print(f"[Upload] LOCAL_MODE stored {dest} ({size / (1024*1024):.1f} MB)")
    return {"gcs_path": f"{settings.GCS_UPLOAD_PREFIX}{upload_id}_{safe_filename}", "size": size}


@router.get("/status/{gcs_path:path}", response_model=UploadStatusResponse)
@require_auth
async def check_upload_status(request: Request, gcs_path: str):
    """
    Check if a file was successfully uploaded to GCS.

    Args:
        request: FastAPI request object (injected by require_auth)
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
@require_auth
async def get_upload_config(request: Request):
    """
    Get client-side upload configuration.

    Returns information about upload limits and GCS availability.

    Args:
        request: FastAPI request object (injected by require_auth)
    """
    return {
        "gcs_enabled": settings.ENABLE_GCS_UPLOADS,
        "direct_upload_limit": 32 * 1024 * 1024,  # 32MB Cloud Run limit
        "gcs_bucket": settings.GCS_BUCKET_NAME if settings.ENABLE_GCS_UPLOADS else None,
        "max_file_size": 10 * 1024 * 1024 * 1024,  # 10GB
    }
