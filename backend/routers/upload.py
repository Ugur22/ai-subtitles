"""
Upload endpoints for GCS-based large file uploads.

These endpoints enable direct-to-GCS uploads which bypass Cloud Run's 32MB request limit.
"""
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel
from datetime import datetime, timedelta, timezone
import mimetypes
import uuid

from config import settings
from middleware.auth import require_auth
from middleware.rate_limit import check_upload_limit, validate_file_size
from services.supabase_service import supabase
from services.local_storage_service import LocalStorageService
from services.media_storage import get_media_storage


router = APIRouter(prefix="/api/upload", tags=["Upload"])


class SignedUrlRequest(BaseModel):
    """Request for a signed upload URL."""
    filename: str
    content_type: str = "video/mp4"
    file_size: int


class SignedUrlResponse(BaseModel):
    """Response containing signed URL for upload."""
    upload_url: str
    gcs_path: str
    method: str  # "PUT" for simple, "POST" for resumable
    expires_in: int  # seconds
    upload_intent_id: str


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
    if not settings.LOCAL_MODE and not settings.ENABLE_GCS_UPLOADS:
        raise HTTPException(
            status_code=503,
            detail="GCS uploads are not enabled. Use direct upload for files < 32MB."
        )

    try:
        media_storage = get_media_storage()
        user_id = request.state.user["id"]
        validate_file_size(body.file_size)
        if body.file_size <= 0:
            raise HTTPException(status_code=400, detail="File size must be greater than zero.")
        if not await check_upload_limit(user_id):
            raise HTTPException(status_code=429, detail="Daily upload limit reached.")

        intent_id = str(uuid.uuid4())
        gcs_path = media_storage.upload_path(user_id, intent_id, body.filename)
        supabase().table("upload_intents").insert({
            "id": intent_id,
            "user_id": user_id,
            "gcs_path": gcs_path,
            "original_filename": body.filename,
            "content_type": body.content_type,
            "expected_size_bytes": body.file_size,
            "expires_at": (datetime.now(timezone.utc) + timedelta(
                seconds=settings.GCS_SIGNED_URL_EXPIRY
            )).isoformat(),
        }).execute()

        # Determine upload method based on file size
        file_size = body.file_size
        threshold = 100 * 1024 * 1024  # 100MB

        upload_url, gcs_path, method = media_storage.create_upload_url(
            filename=body.filename,
            user_id=user_id,
            upload_intent_id=intent_id,
            content_type=body.content_type,
            resumable=file_size >= threshold,
        )

        return SignedUrlResponse(
            upload_url=upload_url,
            gcs_path=gcs_path,
            method=method,
            expires_in=settings.GCS_SIGNED_URL_EXPIRY,
            upload_intent_id=intent_id,
        )

    except HTTPException:
        raise
    except Exception as e:
        print(f"[Upload] Error generating signed URL: {e}")
        raise HTTPException(status_code=503, detail="Failed to create upload intent")


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
    if not settings.LOCAL_MODE and not settings.ENABLE_GCS_UPLOADS:
        raise HTTPException(
            status_code=503,
            detail="GCS uploads are not enabled."
        )

    try:
        media_storage = get_media_storage()
        user_id = request.state.user["id"]
        validate_file_size(body.file_size)
        if body.file_size <= 0:
            raise HTTPException(status_code=400, detail="File size must be greater than zero.")
        if not await check_upload_limit(user_id):
            raise HTTPException(status_code=429, detail="Daily upload limit reached.")
        intent_id = str(uuid.uuid4())
        gcs_path = media_storage.upload_path(user_id, intent_id, body.filename)
        supabase().table("upload_intents").insert({
            "id": intent_id,
            "user_id": user_id,
            "gcs_path": gcs_path,
            "original_filename": body.filename,
            "content_type": body.content_type,
            "expected_size_bytes": body.file_size,
            "expires_at": (datetime.now(timezone.utc) + timedelta(
                seconds=settings.GCS_SIGNED_URL_EXPIRY
            )).isoformat(),
        }).execute()

        upload_url, gcs_path, method = media_storage.create_upload_url(
            filename=body.filename,
            user_id=user_id,
            upload_intent_id=intent_id,
            content_type=body.content_type,
            resumable=True,
        )

        return SignedUrlResponse(
            upload_url=upload_url,
            gcs_path=gcs_path,
            method=method,
            expires_in=settings.GCS_SIGNED_URL_EXPIRY,
            upload_intent_id=intent_id,
        )

    except HTTPException:
        raise
    except Exception as e:
        print(f"[Upload] Error generating resumable URL: {e}")
        raise HTTPException(status_code=503, detail="Failed to create upload intent")


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
    if not settings.LOCAL_MODE and not settings.ENABLE_GCS_UPLOADS:
        raise HTTPException(status_code=503, detail="GCS uploads are not enabled.")

    try:
        media_storage = get_media_storage()
        user_id = request.state.user["id"]
        if not media_storage.is_user_upload_path(gcs_path, user_id):
            raise HTTPException(status_code=403, detail="Upload path is not owned by this user.")
        intent = supabase().table("upload_intents").select("gcs_path").eq(
            "user_id", user_id
        ).eq("gcs_path", gcs_path).limit(1).execute()
        if not intent.data:
            raise HTTPException(status_code=404, detail="Upload intent not found.")

        exists = media_storage.file_exists(gcs_path)
        size = media_storage.get_file_size(gcs_path) if exists else 0

        return UploadStatusResponse(
            exists=exists,
            size=size,
            gcs_path=gcs_path,
        )

    except HTTPException:
        raise
    except Exception as e:
        print(f"[Upload] Error checking status: {e}")
        raise HTTPException(status_code=503, detail="Failed to check upload status")


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
        "gcs_enabled": settings.ENABLE_GCS_UPLOADS or settings.LOCAL_MODE,
        "direct_upload_limit": 32 * 1024 * 1024,  # 32MB Cloud Run limit
        "gcs_bucket": settings.GCS_BUCKET_NAME if not settings.LOCAL_MODE else None,
        "max_file_size": 4 * 1024 * 1024 * 1024,
    }


@router.put("/local/{upload_intent_id}", status_code=204)
@require_auth
async def upload_local_object(request: Request, upload_intent_id: str):
    """Stream an upload atomically into the local media store."""
    if not settings.LOCAL_MODE:
        raise HTTPException(status_code=404, detail="Not found")
    storage = get_media_storage()
    if not isinstance(storage, LocalStorageService):
        raise HTTPException(status_code=500, detail="Local storage is not configured")

    user_id = request.state.user["id"]
    response = supabase().table("upload_intents").select(
        "gcs_path, expected_size_bytes"
    ).eq("id", upload_intent_id).eq("user_id", user_id).limit(1).execute()
    if not response.data:
        raise HTTPException(status_code=404, detail="Upload intent not found")
    intent = response.data[0]
    object_key = intent["gcs_path"]
    if not storage.is_user_upload_path(object_key, user_id):
        raise HTTPException(status_code=403, detail="Upload path is not owned by this user")

    expected_size = int(intent["expected_size_bytes"])
    written = 0
    try:
        with storage.atomic_writer(object_key) as handle:
            async for chunk in request.stream():
                written += len(chunk)
                if written > expected_size or written > settings.MAX_UPLOAD_SIZE:
                    raise HTTPException(status_code=413, detail="Upload exceeds declared size")
                handle.write(chunk)
    except HTTPException:
        raise
    except OSError as exc:
        raise HTTPException(status_code=503, detail="Local upload failed") from exc
    if written != expected_size:
        storage.delete_file(object_key)
        raise HTTPException(status_code=400, detail="Uploaded size does not match upload intent")
    return Response(status_code=204)


@router.get("/object/{object_key:path}")
@require_auth
async def read_local_object(request: Request, object_key: str):
    """
    Serve owner-scoped local media; this route does not exist in production mode.

    Supports HTTP Range requests — a plain full-body StreamingResponse breaks
    ffmpeg screenshot extraction (which seeks) and browser video seeking, since
    both expect 206 Partial Content for ranged GETs.
    """
    if not settings.LOCAL_MODE:
        raise HTTPException(status_code=404, detail="Not found")
    storage = get_media_storage()
    if not isinstance(storage, LocalStorageService):
        raise HTTPException(status_code=500, detail="Local storage is not configured")
    user_id = request.state.user["id"]
    if not storage.is_owned_media_key(object_key, user_id):
        raise HTTPException(status_code=403, detail="Media is not owned by this user")
    try:
        if not storage.file_exists(object_key):
            raise FileNotFoundError(object_key)
        file_size = storage.get_file_size(object_key)
    except (FileNotFoundError, ValueError):
        raise HTTPException(status_code=404, detail="Media not found")

    media_type = mimetypes.guess_type(object_key)[0] or "application/octet-stream"

    def iter_range(start: int, end: int, chunk_size: int = 1024 * 1024):
        with storage.open_reader(object_key) as handle:
            handle.seek(start)
            remaining = end - start + 1
            while remaining > 0:
                chunk = handle.read(min(chunk_size, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
                yield chunk

    range_header = request.headers.get("range")
    if range_header:
        try:
            range_value = range_header.replace("bytes=", "").split("-")
            start = int(range_value[0]) if range_value[0] else 0
            end = int(range_value[1]) if range_value[1] else file_size - 1
            end = min(end, file_size - 1)
        except (ValueError, IndexError):
            raise HTTPException(status_code=416, detail="Invalid Range header")
        if start > end or start >= file_size:
            raise HTTPException(status_code=416, detail="Range not satisfiable")
        return StreamingResponse(
            iter_range(start, end),
            status_code=206,
            media_type=media_type,
            headers={
                "Content-Range": f"bytes {start}-{end}/{file_size}",
                "Accept-Ranges": "bytes",
                "Content-Length": str(end - start + 1),
            },
        )

    return StreamingResponse(
        iter_range(0, file_size - 1),
        media_type=media_type,
        headers={"Accept-Ranges": "bytes", "Content-Length": str(file_size)},
    )
