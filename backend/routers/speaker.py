"""
Speaker recognition endpoints
"""
import os
import tempfile
from typing import Dict
from fastapi import APIRouter, HTTPException, UploadFile, Form, Request

from middleware.auth import require_auth
from services.transcription_access import (
    authenticated_user_id,
)
from services.transcription_repository import transcription_repository
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
        user_id = authenticated_user_id(request)
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
            transcription = transcription_repository.get_transcription(video_hash, user_id)
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
            user_id,
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
                speaker_info=sr_system.get_speaker_info(user_id, speaker_name)
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
        user_id = authenticated_user_id(request)
        from speaker_recognition import get_speaker_recognition_system
        sr_system = get_speaker_recognition_system()

        speakers = sr_system.list_speakers(user_id)
        speaker_info = [sr_system.get_speaker_info(user_id, name) for name in speakers]

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
        user_id = authenticated_user_id(request)
        from speaker_recognition import get_speaker_recognition_system
        sr_system = get_speaker_recognition_system()

        # Determine audio source
        if audio_file:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp:
                content = await audio_file.read()
                tmp.write(content)
                audio_path = tmp.name
        elif video_hash:
            transcription = transcription_repository.get_transcription(video_hash, user_id)
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
            user_id,
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
        user_id = authenticated_user_id(request)
        from speaker_recognition import get_speaker_recognition_system
        sr_system = get_speaker_recognition_system()

        success = sr_system.remove_speaker(user_id, speaker_name)

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
        user_id = authenticated_user_id(request)
        from speaker_recognition import get_speaker_recognition_system
        sr_system = get_speaker_recognition_system()

        # Get transcription
        transcription = transcription_repository.get_transcription(video_hash, user_id)
        if not transcription:
            raise HTTPException(status_code=404, detail="Transcription not found")

        if not sr_system.list_speakers(user_id):
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
                user_id,
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
        if not transcription_repository.update_transcription(video_hash, user_id, transcription):
            raise HTTPException(status_code=404, detail="Transcription not found")

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
        user_id = authenticated_user_id(request)
        body = await request.json()
        original_speaker = body.get("original_speaker")
        new_speaker_name = body.get("new_speaker_name")

        if not original_speaker or not new_speaker_name:
            raise HTTPException(status_code=400, detail="Missing original_speaker or new_speaker_name")

        # Get existing transcription
        transcription_data = transcription_repository.get_transcription(video_hash, user_id)
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
        success = transcription_repository.update_transcription(video_hash, user_id, transcription_data)
        if not success:
            raise HTTPException(status_code=500, detail="Failed to save updates to database")

        # Update vector store metadata for RAG/chat
        vector_store_updates = {"text_updated": 0, "audio_updated": 0}
        try:
            from services.transcript_embedding_service import transcript_embedding_service

            # Only update if transcript chunks exist (video has been indexed)
            if transcript_embedding_service.transcript_chunks_exist(video_hash, user_id):
                print(f"Updating vector store speaker metadata from '{original_speaker}' to '{new_speaker_name}'...")
                vector_store_updates = transcript_embedding_service.update_speaker_name(
                    video_hash,
                    user_id,
                    original_speaker,
                    new_speaker_name
                )
                print(f"Vector store updated: {vector_store_updates}")
        except Exception as e:
            # Don't fail the entire operation if vector store update fails
            print(f"Warning: Failed to update vector store: {str(e)}")
            import traceback
            traceback.print_exc()

        # Also update Supabase jobs table if the transcription came from there
        try:
            from services.supabase_service import supabase
            client = supabase()

            job = transcription_repository.get_job(video_hash, user_id)

            if job:
                job_id = job["id"]

                # Update result_json with new speaker names
                update_response = (
                    client.table("jobs")
                    .update({"result_json": transcription_data})
                    .eq("id", job_id)
                    .eq("user_id", user_id)
                    .execute()
                )
                print(f"[Speaker] Updated job {job_id} in Supabase with new speaker name")
        except Exception as e:
            # Don't fail the whole operation if Supabase update fails
            print(f"[Speaker] Warning: Could not update Supabase jobs table: {e}")

        try:
            from services.supabase_service import supabase
            face_client = supabase()
            face_update = face_client.table("face_tags").update(
                {"speaker_name": new_speaker_name}
            ).eq("user_id", user_id).eq("video_hash", video_hash).eq(
                "speaker_name", original_speaker
            ).execute()
            face_count = len(face_update.data) if face_update.data else 0
            if face_count > 0:
                print(f"[Speaker] Updated {face_count} face tags from '{original_speaker}' to '{new_speaker_name}'")
        except Exception as e:
            print(f"[Speaker] Warning: Could not update face_tags: {e}")

        # Keep Supabase image embedding speaker metadata aligned with the
        # renamed transcript speaker. Visual search can use this field for
        # filtering/ranking in pgvector mode.
        try:
            from services.supabase_service import supabase
            image_client = supabase()
            image_update = image_client.table("image_embeddings").update(
                {"speaker": new_speaker_name}
            ).eq("user_id", user_id).eq("video_hash", video_hash).eq(
                "speaker", original_speaker
            ).execute()
            image_count = len(image_update.data) if image_update.data else 0
            if image_count > 0:
                print(
                    f"[Speaker] Updated {image_count} image embeddings from "
                    f"'{original_speaker}' to '{new_speaker_name}'"
                )
        except Exception as e:
            print(f"[Speaker] Warning: Could not update image_embeddings: {e}")

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
