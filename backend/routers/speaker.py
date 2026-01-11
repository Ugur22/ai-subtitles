"""
Speaker recognition endpoints
"""
import os
import tempfile
from typing import Dict
from fastapi import APIRouter, HTTPException, UploadFile, Form, Request

from database import store_transcription
from routers.transcription import get_transcription_from_any_source
from dependencies import _last_transcription_data
from middleware.auth import require_auth
from models import (
    EnrollSpeakerResponse,
    ListSpeakersResponse,
    SuccessResponse,
    ErrorResponse
)

router = APIRouter(prefix="/api/speaker", tags=["Speaker Recognition"])


@router.post(
    "/enroll",
    response_model=EnrollSpeakerResponse,
    summary="Enroll a speaker",
    description="Enroll a speaker with their voice sample. Can provide either an audio file or use a segment from an existing video.",
    responses={
        400: {"model": ErrorResponse, "description": "Invalid request"},
        404: {"model": ErrorResponse, "description": "Video not found"},
        500: {"model": ErrorResponse, "description": "Enrollment failed"}
    }
)
@require_auth
async def enroll_speaker_endpoint(
    request: Request,
    speaker_name: str = Form(...),
    audio_file: UploadFile = None,
    video_hash: str = Form(None),
    start_time: float = Form(None),
    end_time: float = Form(None)
) -> EnrollSpeakerResponse:
    """
    Enroll a speaker with their voice sample

    Can provide either:
    - audio_file: Direct audio file upload
    - video_hash + start/end time: Use segment from existing video
    """
    try:
        from speaker_recognition import get_speaker_recognition_system
        sr_system = get_speaker_recognition_system()

        # Determine audio source
        if audio_file:
            # Save uploaded audio file temporarily
            with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp:
                content = await audio_file.read()
                tmp.write(content)
                audio_path = tmp.name
        elif video_hash:
            # Get video from existing transcription
            transcription = get_transcription_from_any_source(video_hash)
            if not transcription or 'file_path' not in transcription:
                raise HTTPException(status_code=404, detail="Video not found")
            audio_path = transcription['file_path']
        else:
            raise HTTPException(
                status_code=400,
                detail="Must provide either audio_file or video_hash"
            )

        # Enroll the speaker
        success = sr_system.enroll_speaker(
            speaker_name,
            audio_path,
            start_time,
            end_time
        )

        # Cleanup temp file if uploaded
        if audio_file and os.path.exists(audio_path):
            os.remove(audio_path)

        if success:
            return EnrollSpeakerResponse(
                success=True,
                message=f"Successfully enrolled speaker: {speaker_name}",
                speaker_info=sr_system.get_speaker_info(speaker_name)
            )
        else:
            raise HTTPException(status_code=500, detail="Enrollment failed")

    except HTTPException:
        raise
    except Exception as e:
        print(f"Error in speaker enrollment: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/list",
    response_model=ListSpeakersResponse,
    summary="List enrolled speakers",
    description="Get list of all enrolled speakers with their metadata",
    responses={
        500: {"model": ErrorResponse, "description": "Server error"}
    }
)
@require_auth
async def list_speakers(request: Request) -> ListSpeakersResponse:
    """Get list of all enrolled speakers"""
    try:
        from speaker_recognition import get_speaker_recognition_system
        sr_system = get_speaker_recognition_system()

        speakers = sr_system.list_speakers()
        speaker_info = [sr_system.get_speaker_info(name) for name in speakers]

        return ListSpeakersResponse(
            speakers=speaker_info,
            count=len(speakers)
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/identify",
    response_model=Dict,
    summary="Identify speaker from audio",
    description="Identify a speaker from an audio segment using enrolled voice prints",
    responses={
        400: {"model": ErrorResponse, "description": "Invalid request"},
        404: {"model": ErrorResponse, "description": "Video not found"},
        500: {"model": ErrorResponse, "description": "Identification failed"}
    }
)
@require_auth
async def identify_speaker_endpoint(
    request: Request,
    audio_file: UploadFile = None,
    video_hash: str = Form(None),
    start_time: float = Form(None),
    end_time: float = Form(None),
    threshold: float = Form(0.7)
) -> Dict:
    """
    Identify a speaker from audio segment
    """
    try:
        from speaker_recognition import get_speaker_recognition_system
        sr_system = get_speaker_recognition_system()

        # Determine audio source
        if audio_file:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp:
                content = await audio_file.read()
                tmp.write(content)
                audio_path = tmp.name
        elif video_hash:
            transcription = get_transcription_from_any_source(video_hash)
            if not transcription or 'file_path' not in transcription:
                raise HTTPException(status_code=404, detail="Video not found")
            audio_path = transcription['file_path']
        else:
            raise HTTPException(
                status_code=400,
                detail="Must provide either audio_file or video_hash"
            )

        # Identify speaker
        speaker_name, confidence = sr_system.identify_speaker(
            audio_path,
            start_time,
            end_time,
            threshold
        )

        # Cleanup temp file
        if audio_file and os.path.exists(audio_path):
            os.remove(audio_path)

        return {
            "speaker": speaker_name,
            "confidence": float(confidence),
            "threshold": threshold,
            "identified": speaker_name is not None
        }

    except Exception as e:
        print(f"Error in speaker identification: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete(
    "/{speaker_name}",
    response_model=SuccessResponse,
    summary="Remove speaker",
    description="Remove a speaker from the enrolled speakers database",
    responses={
        404: {"model": ErrorResponse, "description": "Speaker not found"},
        500: {"model": ErrorResponse, "description": "Server error"}
    }
)
@require_auth
async def delete_speaker(request: Request, speaker_name: str) -> SuccessResponse:
    """Remove a speaker from the database"""
    try:
        from speaker_recognition import get_speaker_recognition_system
        sr_system = get_speaker_recognition_system()

        success = sr_system.remove_speaker(speaker_name)

        if success:
            return SuccessResponse(
                success=True,
                message=f"Removed speaker: {speaker_name}"
            )
        else:
            raise HTTPException(status_code=404, detail="Speaker not found")

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/transcription/{video_hash}/auto_identify_speakers",
    response_model=Dict,
    summary="Auto-identify speakers in video",
    description="Automatically identify speakers in a transcription using enrolled voice prints",
    responses={
        400: {"model": ErrorResponse, "description": "No speakers enrolled"},
        404: {"model": ErrorResponse, "description": "Transcription or video not found"},
        500: {"model": ErrorResponse, "description": "Server error"}
    }
)
@require_auth
async def auto_identify_speakers(request: Request, video_hash: str, threshold: float = 0.7) -> Dict:
    """
    Automatically identify speakers in a transcription using enrolled voice prints
    """
    try:
        from speaker_recognition import get_speaker_recognition_system
        sr_system = get_speaker_recognition_system()

        # Get transcription
        transcription = get_transcription_from_any_source(video_hash)
        if not transcription:
            raise HTTPException(status_code=404, detail="Transcription not found")

        if not sr_system.list_speakers():
            raise HTTPException(
                status_code=400,
                detail="No speakers enrolled. Please enroll speakers first."
            )

        video_path = transcription.get('file_path')
        if not video_path or not os.path.exists(video_path):
            raise HTTPException(status_code=404, detail="Video file not found")

        segments = transcription.get('transcription', {}).get('segments', [])
        identified_count = 0
        updated_segments = []

        print(f"Auto-identifying speakers for {len(segments)} segments...")

        for segment in segments:
            start = segment.get('start', 0)
            end = segment.get('end', start + 1)

            # Identify speaker for this segment
            speaker_name, confidence = sr_system.identify_speaker(
                video_path,
                start,
                end,
                threshold
            )

            if speaker_name:
                segment['speaker'] = speaker_name
                segment['speaker_confidence'] = confidence
                identified_count += 1
                print(f"Segment [{start:.1f}s]: Identified as {speaker_name} ({confidence:.3f})")
            else:
                # Keep original speaker label if no match
                print(f"Segment [{start:.1f}s]: No confident match ({confidence:.3f})")

            updated_segments.append(segment)

        # Update transcription with identified speakers
        transcription['transcription']['segments'] = updated_segments

        # Save to database
        store_transcription(
            video_hash,
            transcription.get('filename', 'unknown'),
            transcription,
            video_path
        )

        return {
            "success": True,
            "total_segments": len(segments),
            "identified_segments": identified_count,
            "message": f"Identified {identified_count}/{len(segments)} segments"
        }

    except HTTPException:
        raise
    except Exception as e:
        print(f"Error in auto-identify: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/transcription/{video_hash}/speaker",
    response_model=Dict,
    summary="Update speaker name",
    description="Update a speaker's name in a transcription",
    responses={
        400: {"model": ErrorResponse, "description": "Invalid request"},
        404: {"model": ErrorResponse, "description": "Transcription not found"},
        500: {"model": ErrorResponse, "description": "Server error"}
    }
)
@require_auth
async def update_speaker_name(request: Request, video_hash: str) -> Dict:
    """Update a speaker's name in a transcription"""
    try:
        body = await request.json()
        original_speaker = body.get("original_speaker")
        new_speaker_name = body.get("new_speaker_name")

        if not original_speaker or not new_speaker_name:
            raise HTTPException(status_code=400, detail="Missing original_speaker or new_speaker_name")

        # Get existing transcription
        transcription_data = get_transcription_from_any_source(video_hash)
        if not transcription_data:
            raise HTTPException(status_code=404, detail="Transcription not found")

        # Update segments
        updated_count = 0
        segments = transcription_data.get("transcription", {}).get("segments", [])

        for segment in segments:
            current_speaker = segment.get("speaker")
            # Match strictly against the internal label (e.g. SPEAKER_00) or previously renamed name
            if current_speaker == original_speaker:
                segment["speaker"] = new_speaker_name
                updated_count += 1

        if updated_count == 0:
            return {
                "success": False,
                "message": f"No segments found for speaker '{original_speaker}'",
                "updated_count": 0
            }

        # Save back to database
        filename = transcription_data.get("filename", "unknown")
        file_path = transcription_data.get("file_path")

        success = store_transcription(video_hash, filename, transcription_data, file_path)
        if not success:
            raise HTTPException(status_code=500, detail="Failed to save updates to database")

        # Update vector store metadata for RAG/chat
        vector_store_updates = {"text_updated": 0, "images_updated": 0}
        try:
            from vector_store import vector_store

            # Only update if the collection exists (video has been indexed)
            if vector_store.collection_exists(video_hash):
                print(f"Updating vector store speaker metadata from '{original_speaker}' to '{new_speaker_name}'...")
                vector_store_updates = vector_store.update_speaker_name(
                    video_hash,
                    original_speaker,
                    new_speaker_name
                )
                print(f"Vector store updated: {vector_store_updates}")
        except Exception as e:
            # Don't fail the entire operation if vector store update fails
            print(f"Warning: Failed to update vector store: {str(e)}")
            import traceback
            traceback.print_exc()

        # Update global cache if it matches
        global _last_transcription_data
        if _last_transcription_data and _last_transcription_data.get("video_hash") == video_hash:
            import dependencies
            dependencies._last_transcription_data = transcription_data
            request.app.state.last_transcription = transcription_data

        return {
            "success": True,
            "message": f"Updated {updated_count} segments from '{original_speaker}' to '{new_speaker_name}'",
            "updated_count": updated_count,
            "video_hash": video_hash,
            "vector_store_updates": vector_store_updates
        }

    except HTTPException:
        raise
    except Exception as e:
        print(f"Error updating speaker name: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
