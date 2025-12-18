"""
Video and utility endpoints
"""
import os
import glob
from typing import Dict, Optional
from pathlib import Path
from fastapi import APIRouter, HTTPException, UploadFile, Request
from fastapi.responses import FileResponse, Response, StreamingResponse

from config import settings
from database import get_transcription, update_file_path, delete_transcription
from models import (
    CleanupScreenshotsResponse,
    UpdateFilePathResponse,
    DeleteTranscriptionResponse,
    ErrorResponse
)
from services.subtitle_service import SubtitleService
from services.video_service import VideoService

router = APIRouter(tags=["Video & Utilities"])


@router.post(
    "/cleanup_screenshots/",
    response_model=CleanupScreenshotsResponse,
    summary="Cleanup screenshot files",
    description="Delete all screenshots from the static/screenshots directory and clean up orphaned ChromaDB image collections"
)
async def cleanup_screenshots() -> CleanupScreenshotsResponse:
    """Delete all screenshots from the static/screenshots directory and clean up orphaned ChromaDB collections"""
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

        # Also clean up orphaned ChromaDB image collections
        # (collections that exist but the transcription doesn't exist in the database anymore)
        collections_cleaned = 0
        try:
            from vector_store import vector_store
            from database import get_transcription
            import re

            all_collections = vector_store.client.list_collections()
            for collection in all_collections:
                # Extract video hash from collection name
                # Collections are named: video_{hash} or video_{hash}_images
                match = re.match(r'video_([a-f0-9]+)(_images)?', collection.name)
                if match:
                    video_hash = match.group(1)
                    # Check if this transcription still exists in the database
                    transcription = get_transcription(video_hash)
                    if not transcription:
                        # This is an orphaned collection - delete it
                        vector_store.client.delete_collection(collection.name)
                        collections_cleaned += 1
                        print(f"Deleted orphaned ChromaDB collection: {collection.name}")

            if collections_cleaned > 0:
                print(f"Cleaned up {collections_cleaned} orphaned ChromaDB collections")
        except Exception as e:
            print(f"Warning: Failed to clean up ChromaDB collections: {str(e)}")

        message = f"Successfully deleted {file_count} screenshot files"
        if collections_cleaned > 0:
            message += f" and {collections_cleaned} orphaned ChromaDB collections"

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


def ranged_file_generator(file_path: str, start: int, end: int, chunk_size: int = 1024 * 1024):
    """Generator that yields chunks of a file for range requests"""
    with open(file_path, "rb") as f:
        f.seek(start)
        remaining = end - start + 1
        while remaining > 0:
            chunk = f.read(min(chunk_size, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk


@router.get(
    "/video/{video_hash}",
    summary="Stream video file",
    description="Serve the video file for a specific transcription by hash with support for range requests (seeking)",
    responses={
        404: {"model": ErrorResponse, "description": "Video not found"},
        500: {"model": ErrorResponse, "description": "Server error"}
    }
)
async def get_video_file(video_hash: str, request: Request):
    """Serve the video file for a specific transcription by hash with range request support"""
    try:
        transcription = get_transcription(video_hash)

        if not transcription:
            print(f"Transcription not found for hash: {video_hash}")
            raise HTTPException(status_code=404, detail="Transcription not found")

        if 'file_path' not in transcription or not transcription['file_path']:
            print(f"File path not set for hash: {video_hash}")
            raise HTTPException(
                status_code=404,
                detail="Video file not found. Please upload the video file using /update_file_path/"
            )

        file_path = transcription['file_path']
        if not os.path.exists(file_path):
            print(f"Video file does not exist at path: {file_path}")
            raise HTTPException(
                status_code=404,
                detail="Video file not found on disk. The file may have been moved or deleted."
            )

        # Check if this is an MKV file - serve MP4 version if available
        if file_path.endswith('.mkv'):
            # Check if MP4 version exists
            mp4_path = file_path.replace('.mkv', '.mp4')
            if os.path.exists(mp4_path):
                print(f"Serving converted MP4 file: {mp4_path}")
                file_path = mp4_path
            else:
                # Convert on the fly if needed
                print(f"Converting MKV to MP4 on-the-fly for: {video_hash}")
                VideoService.convert_mkv_to_mp4(file_path, mp4_path)
                if os.path.exists(mp4_path):
                    file_path = mp4_path

        file_size = os.path.getsize(file_path)

        # Check for Range header (needed for video seeking)
        range_header = request.headers.get("range")

        if range_header:
            # Parse range header (e.g., "bytes=0-1024" or "bytes=0-")
            range_match = range_header.replace("bytes=", "").split("-")
            start = int(range_match[0]) if range_match[0] else 0
            end = int(range_match[1]) if range_match[1] else file_size - 1

            # Ensure end doesn't exceed file size
            end = min(end, file_size - 1)
            content_length = end - start + 1

            print(f"Serving video range: {start}-{end}/{file_size}")

            headers = {
                "Content-Range": f"bytes {start}-{end}/{file_size}",
                "Accept-Ranges": "bytes",
                "Content-Length": str(content_length),
                "Content-Type": "video/mp4",
            }

            return StreamingResponse(
                ranged_file_generator(file_path, start, end),
                status_code=206,  # Partial Content
                headers=headers,
                media_type="video/mp4"
            )
        else:
            # No range header - serve the full file
            print(f"Serving full video file: {file_path}")
            headers = {
                "Accept-Ranges": "bytes",
                "Content-Length": str(file_size),
            }
            return FileResponse(
                file_path,
                media_type="video/mp4",
                filename=os.path.basename(file_path),
                headers=headers
            )

    except HTTPException:
        raise
    except Exception as e:
        print(f"Error serving video: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error serving video: {str(e)}")


@router.get(
    "/subtitles/{language}",
    summary="Generate SRT subtitles",
    description="Generate SRT format subtitles from the last transcription",
    responses={
        404: {"model": ErrorResponse, "description": "No transcription available"}
    }
)
async def get_subtitles(language: str):
    """Generate SRT format subtitles from the last transcription"""
    # Import here to avoid circular import
    from dependencies import _last_transcription_data

    if not _last_transcription_data:
        raise HTTPException(
            status_code=404,
            detail="No transcription available. Please transcribe a video first."
        )

    try:
        # Get segments from transcription
        segments = _last_transcription_data.get('transcription', {}).get('segments', [])
        if not segments:
            raise HTTPException(status_code=404, detail="No segments found in transcription")

        # Determine if we should use translations
        use_translation = (language.lower() == 'en')

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
async def update_video_file_path(video_hash: str, file: UploadFile) -> UpdateFilePathResponse:
    """Update an existing transcription with a new file"""
    try:
        # Check if transcription exists
        transcription = get_transcription(video_hash)
        if not transcription:
            raise HTTPException(status_code=404, detail="Transcription not found")

        # Validate file type
        allowed_extensions = {'.mp4', '.mpeg', '.mpga', '.m4a', '.wav', '.webm', '.mp3', '.mov', '.mkv'}
        file_extension = Path(file.filename).suffix.lower()
        if file_extension not in allowed_extensions:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported file format. Supported formats: {', '.join(allowed_extensions)}"
            )

        # Save the file to the permanent storage
        permanent_storage_dir = settings.VIDEOS_DIR
        os.makedirs(permanent_storage_dir, exist_ok=True)
        permanent_file_path = os.path.join(permanent_storage_dir, f"{video_hash}{file_extension}")

        # Save file in chunks
        with open(permanent_file_path, "wb") as buffer:
            while chunk := await file.read(1024 * 1024):  # 1MB chunks
                buffer.write(chunk)

        # Update the transcription in the database with the new file path
        success = update_file_path(video_hash, permanent_file_path)

        if not success:
            raise HTTPException(status_code=500, detail="Failed to update database")

        return UpdateFilePathResponse(
            success=True,
            message="File path updated successfully",
            file_path=permanent_file_path
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
async def delete_transcription_endpoint(video_hash: str) -> DeleteTranscriptionResponse:
    """Delete a transcription from the database by hash"""
    try:
        # Check if transcription exists
        transcription = get_transcription(video_hash)
        if not transcription:
            raise HTTPException(status_code=404, detail="Transcription not found")

        # Delete the video file if it exists
        if 'file_path' in transcription and transcription['file_path']:
            file_path = transcription['file_path']
            if os.path.exists(file_path):
                try:
                    os.remove(file_path)
                    print(f"Deleted video file: {file_path}")
                except Exception as e:
                    print(f"Error deleting video file {file_path}: {str(e)}")

        # Delete all screenshots associated with this video hash
        screenshots_dir = settings.SCREENSHOTS_DIR
        screenshot_pattern = os.path.join(screenshots_dir, f"{video_hash}_*.jpg")
        screenshots_to_delete = glob.glob(screenshot_pattern)

        deleted_screenshots_count = 0
        for screenshot in screenshots_to_delete:
            try:
                os.remove(screenshot)
                deleted_screenshots_count += 1
                print(f"Deleted screenshot: {screenshot}")
            except Exception as e:
                print(f"Error deleting screenshot {screenshot}: {str(e)}")

        if deleted_screenshots_count > 0:
            print(f"Deleted {deleted_screenshots_count} screenshots for video hash: {video_hash}")
        else:
            print(f"No screenshots found to delete for video hash: {video_hash}")

        # Delete ChromaDB collections (text and image embeddings)
        try:
            from vector_store import vector_store

            # Delete text collection
            if vector_store.collection_exists(video_hash):
                vector_store.delete_collection(video_hash)
                print(f"Deleted text embeddings collection for video hash: {video_hash}")

            # Delete image collection
            if vector_store.image_collection_exists(video_hash):
                vector_store.delete_image_collection(video_hash)
                print(f"Deleted image embeddings collection for video hash: {video_hash}")
        except Exception as e:
            # Don't fail the deletion if vector store cleanup fails
            print(f"Warning: Failed to delete vector store collections: {str(e)}")

        # Delete from database
        success = delete_transcription(video_hash)

        if not success:
            raise HTTPException(status_code=500, detail="Failed to delete from database")

        return DeleteTranscriptionResponse(
            success=True,
            message=f"Transcription deleted successfully (including {deleted_screenshots_count} screenshots)"
        )
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error deleting transcription: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error deleting transcription: {str(e)}")
