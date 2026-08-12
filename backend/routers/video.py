"""
Video and utility endpoints
"""
import os
import glob
import uuid
from typing import Dict, Optional
from pathlib import Path
from fastapi import APIRouter, HTTPException, UploadFile, Request, Query
from fastapi.responses import RedirectResponse, Response

from config import settings
from middleware.auth import require_admin, require_auth
from models import (
    CleanupScreenshotsResponse,
    UpdateFilePathResponse,
    DeleteTranscriptionResponse,
    ErrorResponse
)
from services.subtitle_service import SubtitleService
from services.transcription_access import (
    authenticated_user_id,
)
from services.media_storage import get_media_storage
from services.transcription_repository import transcription_repository

router = APIRouter(prefix="/api", tags=["Video & Utilities"])


@router.post(
    "/cleanup_screenshots/",
    response_model=CleanupScreenshotsResponse,
    summary="Cleanup screenshot files",
    description="Delete all screenshots from the static/screenshots directory"
)
@require_admin
async def cleanup_screenshots(request: Request) -> CleanupScreenshotsResponse:
    """Delete all screenshots from the static/screenshots directory"""
    try:
        screenshots_dir = settings.SCREENSHOTS_DIR

        # Check if directory exists
        if not os.path.exists(screenshots_dir):
            os.makedirs(screenshots_dir, exist_ok=True)
            file_count = 0
        else:
            # Count files before deletion
            files = os.listdir(screenshots_dir)
            file_count = len(files)

            # Delete all files in the directory
            for filename in files:
                file_path = os.path.join(screenshots_dir, filename)
                if os.path.isfile(file_path):
                    os.remove(file_path)
                    print(f"Deleted: {file_path}")

        message = f"Successfully deleted {file_count} screenshot files"

        return CleanupScreenshotsResponse(
            success=True,
            message=message,
            files_deleted=file_count
        )
    except Exception as e:
        print(f"Error cleaning up screenshots: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Error cleaning up screenshots: {str(e)}"
        )


@router.get(
    "/video/{video_hash}",
    summary="Stream video file",
    description="Serve the video file for a specific transcription by hash with support for range requests (seeking)",
    responses={
        404: {"model": ErrorResponse, "description": "Video not found"},
        500: {"model": ErrorResponse, "description": "Server error"}
    }
)
@require_auth
async def get_video_file(request: Request, video_hash: str):
    """Redirect an owner to the configured media store's download URL."""
    try:
        user_id = authenticated_user_id(request)
        transcription = transcription_repository.get_transcription(
            video_hash,
            user_id,
        )

        if not transcription:
            print(f"Transcription not found for hash: {video_hash}")
            raise HTTPException(status_code=404, detail="Transcription not found")

        media_key = transcription.get("media_key") or transcription.get("gcs_path")
        if not media_key:
            raise HTTPException(status_code=404, detail="Video media is not available")
        storage = get_media_storage()
        if not storage.file_exists(media_key):
            raise HTTPException(status_code=404, detail="Video media is not available")
        return RedirectResponse(storage.generate_download_url(media_key), status_code=307)

    except HTTPException:
        raise
    except Exception as e:
        print(f"Error serving video: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error serving video: {str(e)}")


@router.get(
    "/subtitles/{language}",
    summary="Generate SRT subtitles",
    description="Generate SRT format subtitles from a transcription",
    responses={
        404: {"model": ErrorResponse, "description": "No transcription available"}
    }
)
@require_auth
async def get_subtitles(
    request: Request,
    language: str,
    video_hash: Optional[str] = Query(None, description="Video hash to generate subtitles for")
):
    """Generate SRT format subtitles from a transcription"""
    # Import here to avoid circular import
    if not video_hash:
        raise HTTPException(status_code=400, detail="video_hash is required")
    transcription_data = transcription_repository.get_transcription(
        video_hash,
        authenticated_user_id(request),
    )
    if not transcription_data:
        raise HTTPException(status_code=404, detail="Transcription not found")

    try:
        # Get segments from transcription
        segments = transcription_data.get('transcription', {}).get('segments', [])
        if not segments:
            raise HTTPException(status_code=404, detail="No segments found in transcription")

        # Determine if we should use translations (accept both "english" and "en")
        use_translation = (language.lower() in ['english', 'en'])

        # Generate SRT content
        srt_content = SubtitleService.generate_srt(segments, use_translation=use_translation)

        # Return as downloadable file
        return Response(
            content=srt_content,
            media_type="application/x-subrip",
            headers={
                "Content-Disposition": f"attachment; filename=subtitles_{language}.srt"
            }
        )

    except HTTPException:
        raise
    except Exception as e:
        print(f"Error generating subtitles: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error generating subtitles: {str(e)}")


@router.post(
    "/update_file_path/{video_hash}",
    response_model=UpdateFilePathResponse,
    summary="Update video file path",
    description="Update an existing transcription with a new video file",
    responses={
        404: {"model": ErrorResponse, "description": "Transcription not found"},
        400: {"model": ErrorResponse, "description": "Invalid file format"}
    }
)
@require_auth
async def update_video_file_path(request: Request, video_hash: str, file: UploadFile) -> UpdateFilePathResponse:
    """Update an existing transcription with a new file"""
    try:
        # Check if transcription exists
        user_id = authenticated_user_id(request)
        transcription = transcription_repository.get_transcription(video_hash, user_id)
        if not transcription:
            raise HTTPException(status_code=404, detail="Transcription not found")
        if not transcription_repository.hash_resources_are_owner_exclusive(video_hash, user_id):
            raise HTTPException(
                status_code=409,
                detail="Video storage is not owner-isolated for this hash",
            )
        if not settings.LOCAL_MODE:
            raise HTTPException(
                status_code=409,
                detail="Production media replacement must use the upload-intent workflow",
            )

        # Validate file type
        allowed_extensions = {'.mp4', '.mpeg', '.mpga', '.m4a', '.wav', '.webm', '.mp3', '.mov', '.mkv'}
        file_extension = Path(file.filename).suffix.lower()
        if file_extension not in allowed_extensions:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported file format. Supported formats: {', '.join(allowed_extensions)}"
            )

        storage = get_media_storage()
        media_key = storage.upload_path(user_id, str(uuid.uuid4()), file.filename)
        with storage.atomic_writer(media_key) as buffer:
            while chunk := await file.read(1024 * 1024):  # 1MB chunks
                buffer.write(chunk)
        media_key = storage.move_to_processed(media_key)

        # Update the transcription in the database with the new file path
        success = transcription_repository.update_media_key(
            video_hash,
            user_id,
            media_key,
        )

        if not success:
            raise HTTPException(status_code=500, detail="Failed to update database")

        return UpdateFilePathResponse(
            success=True,
            message="File path updated successfully",
            file_path=media_key
        )
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error updating file path: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error updating file path: {str(e)}")


@router.delete(
    "/transcription/{video_hash}",
    response_model=DeleteTranscriptionResponse,
    summary="Delete transcription",
    description="Delete a transcription from the database by hash",
    responses={
        404: {"model": ErrorResponse, "description": "Transcription not found"}
    }
)
@require_auth
async def delete_transcription_endpoint(request: Request, video_hash: str) -> DeleteTranscriptionResponse:
    """Delete a transcription from the database by hash"""
    try:
        # Check if transcription exists
        user_id = authenticated_user_id(request)
        transcription = transcription_repository.get_transcription(video_hash, user_id)
        if not transcription:
            raise HTTPException(status_code=404, detail="Transcription not found")

        deleted_screenshots_count = 0
        # Hash-keyed media and vector collections can be shared by identical
        # uploads. Phase 2 will introduce owner-bound storage locators; until
        # then, deleting the owner's job must not delete shared physical data.
        success = transcription_repository.delete(video_hash, user_id)

        if not success:
            raise HTTPException(status_code=500, detail="Failed to delete transcription metadata")

        return DeleteTranscriptionResponse(
            success=True,
            message=f"Transcription deleted successfully (including {deleted_screenshots_count} screenshots)"
        )
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error deleting transcription: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error deleting transcription: {str(e)}")
