"""
Transcription endpoints - core functionality for video/audio transcription
"""
import os
import tempfile
import shutil
import time
import subprocess
import uuid
import json
from pathlib import Path
from datetime import timedelta
from typing import Dict, List
from fastapi import APIRouter, UploadFile, HTTPException, Request, Form
from fastapi.responses import StreamingResponse

from config import settings
from database import get_transcription, store_transcription, list_transcriptions, delete_transcription as db_delete_transcription
from dependencies import get_whisper_model, get_speaker_diarizer, _last_transcription_data
import dependencies
from models import (
    TranscriptionResponse,
    TranscriptionListResponse,
    TranslationRequest,
    TranslationResponse,
    SummaryRequest,
    SummaryResponse,
    ErrorResponse
)
from services.audio_service import AudioService
from services.video_service import VideoService
from services.translation_service import TranslationService
from services.speaker_service import SpeakerService
from services.summarization_service import SummarizationService
from utils.file_utils import generate_file_hash
from utils.time_utils import format_timestamp, format_eta, time_to_seconds, time_diff_minutes

router = APIRouter(tags=["Transcription"])


@router.get(
    "/current_transcription/",
    response_model=Dict,
    summary="Get current transcription",
    description="Return the most recently processed transcription data",
    responses={
        404: {"model": ErrorResponse, "description": "No transcription available"}
    }
)
async def get_current_transcription(request: Request) -> Dict:
    """Return the current transcription data"""
    if not dependencies._last_transcription_data:
        raise HTTPException(status_code=404, detail="No transcription available. Please transcribe a video first.")

    # Count segments with screenshots
    segment_count = len(dependencies._last_transcription_data['transcription']['segments'])
    screenshots_count = sum(1 for segment in dependencies._last_transcription_data['transcription']['segments']
                          if 'screenshot_url' in segment and segment['screenshot_url'])

    print(f"Sending transcription data: {segment_count} segments total, {screenshots_count} with screenshots")
    return dependencies._last_transcription_data


@router.get(
    "/transcriptions/",
    response_model=TranscriptionListResponse,
    summary="List all transcriptions",
    description="Get a list of all saved transcriptions with metadata",
    responses={
        500: {"model": ErrorResponse, "description": "Failed to list transcriptions"}
    }
)
async def list_all_transcriptions() -> TranscriptionListResponse:
    """List all saved transcriptions with additional metadata"""
    try:
        transcriptions = list_transcriptions()
        return TranscriptionListResponse(transcriptions=transcriptions)
    except Exception as e:
        print(f"Error listing transcriptions: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to list transcriptions")


@router.get(
    "/transcription/{video_hash}",
    response_model=Dict,
    summary="Get transcription by hash",
    description="Retrieve a specific transcription by its video hash",
    responses={
        404: {"model": ErrorResponse, "description": "Transcription not found"}
    }
)
async def get_saved_transcription(video_hash: str, request: Request) -> Dict:
    """Get a specific transcription by hash"""
    transcription = get_transcription(video_hash)
    if not transcription:
        raise HTTPException(status_code=404, detail="Transcription not found")

    # Ensure all translations are present if language is not English
    try:
        lang = transcription.get('transcription', {}).get('language', '').lower()
        segments = transcription.get('transcription', {}).get('segments', [])
        if lang and lang not in ['en', 'english']:
            missing = [s for s in segments if not s.get('translation')]
            if missing:
                print(f"Translating {len(missing)} missing segments for video_hash={video_hash}...")
                translated_segments = TranslationService.translate_segments(segments, lang)
                for i, seg in enumerate(segments):
                    seg['translation'] = translated_segments[i].get('translation', seg.get('text', '[Translation missing]'))
                store_transcription(video_hash, transcription.get('filename', ''), transcription, transcription.get('file_path'))
                print(f"Translation complete and saved for video_hash={video_hash}.")
        else:
            # If English source, ensure all segments have a translation field (set to text for consistency)
            for seg in segments:
                if 'translation' not in seg or not seg.get('translation'):
                    seg['translation'] = seg.get('text', '')
    except Exception as e:
        print(f"Error ensuring translations in /transcription/{{video_hash}}: {e}")

    # Update the last_transcription_data and request state
    dependencies._last_transcription_data = transcription
    request.app.state.last_transcription = transcription

    return transcription


@router.post(
    "/translate_local/",
    response_model=TranslationResponse,
    summary="Translate text locally",
    description="Translate text to English using local MarianMT model",
    responses={
        400: {"model": ErrorResponse, "description": "Missing required fields"}
    }
)
async def translate_local_endpoint(request: TranslationRequest) -> TranslationResponse:
    """Translate text to English locally using MarianMT."""
    try:
        text = request.text
        source_lang = request.source_lang
        if not text or not source_lang:
            raise HTTPException(status_code=400, detail="Missing text or source language")

        try:
            tokenizer, model = TranslationService.get_marian_model(source_lang)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Unsupported or unavailable language model: {source_lang}")

        # MarianMT expects a list of sentences
        if isinstance(text, str):
            text_list = [text]
        else:
            text_list = text

        inputs = tokenizer(text_list, return_tensors="pt", padding=True)
        translated = model.generate(**inputs)
        translations = [tokenizer.decode(t, skip_special_tokens=True) for t in translated]

        return TranslationResponse(translation=translations[0] if len(translations) == 1 else translations)
    except HTTPException:
        raise
    except Exception as e:
        print(f"Translation error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/generate_summary/",
    response_model=Dict,
    summary="Generate video summary",
    description="Generate section summaries from transcription using local BART model",
    responses={
        404: {"model": ErrorResponse, "description": "No transcription available"}
    }
)
async def generate_summary(request: Request) -> Dict:
    """Generate section summaries from transcription using local model"""
    if not hasattr(request.app.state, 'last_transcription'):
        raise HTTPException(status_code=404, detail="No transcription available. Please transcribe a video first.")

    # Get the latest transcription data
    transcription = request.app.state.last_transcription

    # Include the filename in the response
    filename = transcription.get('filename', 'unknown_filename')
    print(f"Generating summary for: {filename}")

    segments = transcription['transcription']['segments']
    print(f"Found {len(segments)} segments for summarization")

    # Group segments into logical sections (roughly 1-3 minutes each)
    sections = []
    current_section = []
    section_start = "00:00:00"
    min_section_duration = 1  # Minimum section duration in minutes
    max_section_duration = 3  # Maximum section duration in minutes

    for segment in segments:
        # Create new section when we reach desired duration or significant pause
        start_time = segment['start_time']
        if current_section:
            # Check if we've reached minimum duration and have a natural break
            section_duration = time_diff_minutes(section_start, start_time)
            if section_duration >= min_section_duration:
                # Check for natural break (>2 second pause)
                last_segment_end = time_to_seconds(current_section[-1]['end_time'])
                current_segment_start = time_to_seconds(start_time)
                pause_duration = current_segment_start - last_segment_end

                # Create new section if we have a significant pause or reached max duration
                if pause_duration > 2 or section_duration >= max_section_duration:
                    sections.append({
                        "start": section_start,
                        "end": current_section[-1]['end_time'],
                        "segments": current_section.copy()
                    })
                    section_start = start_time
                    current_section = [segment]
                    continue

        current_section.append(segment)

    # Add the last section
    if current_section:
        sections.append({
            "start": section_start,
            "end": current_section[-1]['end_time'],
            "segments": current_section
        })

    print(f"Created {len(sections)} logical sections for summarization")

    # Generate summary for each section
    summaries = []
    for section_index, section in enumerate(sections):
        # Combine text from all segments - safely handling None values
        section_text = " ".join(seg["text"] or "" for seg in section["segments"] if seg.get("text"))

        # Fix: Safely handle translation which might be None or missing
        translated_texts = []
        for seg in section["segments"]:
            if seg.get("translation"):
                translated_texts.append(seg["translation"])
            elif seg.get("text"):
                translated_texts.append(seg["text"])
            else:
                # Skip this segment if both text and translation are missing/None
                continue

        translated_text = " ".join(translated_texts)

        # Only use translation if it's different from the original
        text_to_summarize = translated_text if (
            translated_text != section_text and
            transcription['transcription']['language'].lower() not in ["en", "english"]
        ) else section_text

        # Skip empty sections
        if not text_to_summarize:
            continue

        try:
            # Generate concise summary using local model
            summary = SummarizationService.generate_local_summary(text_to_summarize)

            # Generate descriptive title
            title = f"Section {section['start']}-{section['end']}"

            summaries.append({
                "title": title,
                "start": section["start"],
                "end": section["end"],
                "summary": summary
            })
        except Exception as e:
            print(f"Error generating summary for section {section['start']}-{section['end']}: {e}")
            # Add a placeholder for failed summaries
            summaries.append({
                "title": f"Section {section['start']}-{section['end']}",
                "start": section["start"],
                "end": section["end"],
                "summary": "Summary generation failed. Please try again."
            })

    # Log summary generation results
    print(f"Generated {len(summaries)} section summaries")

    return {
        "summaries": summaries,
        "filename": filename,
        "sections_count": len(sections)
    }


# Helper function wrappers for service modules (to maintain compatibility with endpoint code)
def extract_audio(video_path: str, chunk_duration: int = 600, overlap: int = 5) -> list:
    """Wrapper for AudioService.extract_audio"""
    return AudioService.extract_audio(video_path, chunk_duration, overlap)

def extract_audio_with_ffmpeg(video_path: str, chunk_duration: int = 600, overlap: int = 5) -> list:
    """Wrapper for AudioService.extract_audio_with_ffmpeg"""
    return AudioService.extract_audio_with_ffmpeg(video_path, chunk_duration, overlap)

def compress_audio(input_path: str, output_path: str, file_size_check: bool = True) -> str:
    """Wrapper for AudioService.compress_audio"""
    return AudioService.compress_audio(input_path, output_path, file_size_check)

def translate_segments(segments: List[Dict], source_lang: str) -> List[Dict]:
    """Wrapper for TranslationService.translate_segments"""
    return TranslationService.translate_segments(segments, source_lang)

def add_speaker_labels(audio_path: str, segments: List[Dict], num_speakers: int = None,
                      min_speakers: int = None, max_speakers: int = None) -> List[Dict]:
    """Wrapper for SpeakerService.add_speaker_labels"""
    return SpeakerService.add_speaker_labels(audio_path, segments, num_speakers, min_speakers, max_speakers)

def extract_screenshot(input_path: str, timestamp: float, output_path: str) -> bool:
    """Wrapper for VideoService.extract_screenshot"""
    return VideoService.extract_screenshot(input_path, timestamp, output_path)

def convert_mkv_to_mp4(input_path: str, output_path: str) -> bool:
    """Wrapper for VideoService.convert_mkv_to_mp4"""
    return VideoService.convert_mkv_to_mp4(input_path, output_path)

def get_audio_duration(file_path: str) -> float:
    """Wrapper for AudioService.get_audio_duration"""
    return AudioService.get_audio_duration(file_path)

# Get local whisper model instance
local_whisper_model = get_whisper_model()


# =============================================================================
# COMPLEX TRANSCRIPTION ENDPOINTS
# The following three endpoints are large (300+ lines each) and contain
# complex transcription logic. They are included here to maintain 100%
# backward compatibility with the original implementation.
# =============================================================================


@router.post("/transcribe/")
async def transcribe_video(
    file: UploadFile, 
    request: Request, 
    file_path: str = None,
    language: str = Form(None)  # Added language parameter
) -> Dict:
    """Handle video upload, extract audio, and transcribe"""
        
    try:
        if not file:
            raise HTTPException(status_code=400, detail="No file provided")

        # Validate file type
        allowed_extensions = {'.mp4', '.mpeg', '.mpga', '.m4a', '.wav', '.webm', '.mp3', '.mov', '.mkv'}
        file_extension = Path(file.filename).suffix.lower()
        if file_extension not in allowed_extensions:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported file format. Supported formats: {', '.join(allowed_extensions)}"
            )

        print(f"\nProcessing video: {file.filename}")
        # Print language if provided
        if language:
            print(f"Language specified: {language}")
        else:
            print("Language: Auto-detect")
            
        start_time = time.time()
        
        # Create a temporary directory for processing
        with tempfile.TemporaryDirectory() as temp_dir:
            # Save uploaded file in chunks to avoid memory issues
            temp_input_path = os.path.join(temp_dir, file.filename)
            temp_output_path = os.path.join(temp_dir, "audio.mp3")
            screenshots_dir = os.path.join("static", "screenshots")
            os.makedirs(screenshots_dir, exist_ok=True)
            
            print(f"Created temp directory: {temp_dir}")
            print(f"Input path: {temp_input_path}")
            print(f"Output path: {temp_output_path}")
            print(f"Screenshots directory: {screenshots_dir}")
            
            # Save file in chunks with a larger chunk size for better performance
            CHUNK_SIZE = 1024 * 1024 * 8  # 8MB chunks
            total_size = 0
            
            print("\nUploading video...")
            try:
                with open(temp_input_path, "wb") as buffer:
                    while chunk := await file.read(CHUNK_SIZE):
                        total_size += len(chunk)
                        if total_size > 10 * 1024 * 1024 * 1024:  # 10GB limit
                            raise HTTPException(
                                status_code=413,
                                detail="File too large. Maximum size is 10GB."
                            )
                        buffer.write(chunk)
                        print(f"Uploaded: {total_size / (1024*1024):.1f} MB", end="\r")
                print(f"\nUpload completed. Total size: {total_size / (1024*1024):.1f} MB")
            except Exception as e:
                print(f"Upload error: {str(e)}")
                raise HTTPException(
                    status_code=400,
                    detail=f"Error uploading file: {str(e)}"
                )
            
            # Generate hash for the file
            video_hash = generate_file_hash(temp_input_path)
            print(f"Generated hash for video: {video_hash}")
            
            # Check if we already have a transcription for this file
            existing_transcription = get_transcription(video_hash)
            if existing_transcription:
                print(f"Found existing transcription for {file.filename} with hash {video_hash}")
                # Update the dependencies._last_transcription_data with the existing data
                dependencies._last_transcription_data = existing_transcription
                return existing_transcription
            
            print("No existing transcription found. Processing video...")
            
            # Save a permanent copy of the video file
            permanent_storage_dir = os.path.join("static", "videos")
            os.makedirs(permanent_storage_dir, exist_ok=True)
            permanent_file_path = os.path.join(permanent_storage_dir, f"{video_hash}{file_extension}")
            # Check if file already exists to avoid unnecessary copy
            if not os.path.exists(permanent_file_path):
                 shutil.copy2(temp_input_path, permanent_file_path)
                 print(f"Saved permanent copy of video to: {permanent_file_path}")
            else:
                 print(f"Permanent copy already exists at: {permanent_file_path}")

            # Convert MKV to MP4 for browser compatibility
            if file_extension == '.mkv':
                mp4_path = os.path.join(permanent_storage_dir, f"{video_hash}.mp4")
                if not os.path.exists(mp4_path):
                    print("\nMKV file detected - converting to MP4 for browser compatibility...")
                    conversion_success = convert_mkv_to_mp4(permanent_file_path, mp4_path)
                    if conversion_success:
                        print(f"Conversion successful! Using MP4 file for playback.")
                        # Update paths to use the MP4 file for processing and serving
                        permanent_file_path = mp4_path
                        temp_input_path = mp4_path  # Use converted file for screenshots
                    else:
                        print(f"WARNING: Conversion failed. Video playback may not work in browser.")
                else:
                    print(f"MP4 version already exists at: {mp4_path}")
                    permanent_file_path = mp4_path
                    temp_input_path = mp4_path

            print("\nExtracting and compressing audio...")
            audio_processed = False
            try:
                # --- Force Chunking --- 
                # We will now always chunk the audio using extract_audio, regardless of initial size,
                # as this seems to help Whisper with long files.
                # The old single-file processing path will be removed.
                
                print("Forcing audio splitting into chunks using moviepy...")
                chunk_duration_seconds = 300 # 5-minute chunks
                chunk_overlap = 5  # seconds, must match extract_audio
                print(f"Using moviepy to extract audio chunks ({chunk_duration_seconds}s duration, {chunk_overlap}s overlap)...")
                
                # Ensure extract_audio handles compression for each chunk
                # Assuming extract_audio compresses each chunk and returns paths
                audio_chunks = extract_audio(temp_input_path, chunk_duration=chunk_duration_seconds, overlap=chunk_overlap)

                if not audio_chunks:
                    raise Exception("Failed to split audio into chunks using moviepy")
                
                print(f"Split audio into {len(audio_chunks)} chunks.")
                
                # Transcribe each chunk and combine results
                all_segments = []
                audio_language = language # Use provided language initially
                full_text = []
                
                total_chunks = len(audio_chunks)
                for i, chunk_path in enumerate(audio_chunks):
                    print(f"\nProcessing chunk {i+1}/{total_chunks}: {os.path.basename(chunk_path)}")
                    chunk_size_mb = 0
                    if os.path.exists(chunk_path):
                        chunk_size_mb = os.path.getsize(chunk_path) / (1024 * 1024)
                        print(f"Chunk size: {chunk_size_mb:.2f} MB")
                    else:
                         print(f"WARNING: Chunk file not found: {chunk_path}. Skipping.")
                         continue
                    if chunk_size_mb > 25:
                        print(f"WARNING: Chunk {i+1} ({chunk_size_mb:.2f} MB) exceeds 25MB limit. Skipping this chunk.")
                        continue
                    with open(chunk_path, "rb") as chunk_file:
                        print(f"Calling Whisper API for chunk {i+1}...")
                        # Always use task="transcribe" to get original language text
                        segments, info = local_whisper_model.transcribe(
                            chunk_path,
                            task="transcribe",
                            language=language if language else None,
                            beam_size=1  # Faster processing
                        )
                        chunk_response = type('obj', (object,), {
                            'text': " ".join([seg.text for seg in segments]),
                            'language': info.language,
                            'segments': [{
                                'start': seg.start,
                                'end': seg.end,
                                'text': seg.text
                            } for seg in segments]
                        })
                        print(f"Transcription received for chunk {i+1}.")
                        detected_language = chunk_response.language
                        print(f"Detected language for chunk {i+1}: {detected_language}")
                        if audio_language is None:
                            audio_language = detected_language
                            print(f"Overall audio language set to: {audio_language}")
                        full_text.append(chunk_response.text)
                        # --- Overlap segment discarding logic ---
                        chunk_offset = i * chunk_duration_seconds
                        chunk_length = chunk_duration_seconds + (chunk_overlap if i < total_chunks - 1 else 0) + (chunk_overlap if i > 0 else 0)
                        segments = chunk_response.segments
                        # Discard first segment if not the first chunk and it starts within overlap
                        if i > 0 and segments and segments[0]['start'] < chunk_overlap:
                            segments = segments[1:]
                        # Discard last segment if not the last chunk and it ends after chunk_length - overlap
                        if i < total_chunks - 1 and segments and segments[-1]['end'] > (chunk_length - chunk_overlap):
                            segments = segments[:-1]
                        # Adjust segment times by chunk offset (minus overlap for all but first chunk)
                        for segment in segments:
                            segment['start'] += chunk_offset - (chunk_overlap if i > 0 else 0)
                            segment['end'] += chunk_offset - (chunk_overlap if i > 0 else 0)
                        # Append to all_segments
                        for segment in segments:
                            segment_text = segment.get('text', '')
                            if segment_text and not segment_text.isspace():
                                all_segments.append(segment)
                            else:
                                all_segments.append({
                                    'start': segment['start'],
                                    'end': segment['end'],
                                    'text': '[No speech detected]',
                                    'translation': '[No speech detected]'
                                })
                
                # Create a synthetic response object to hold the combined results
                class SyntheticResponse:
                    def __init__(self):
                        self.text = ""
                        self.segments = []
                        self.language = "en" # Default language

                response = SyntheticResponse()
                response.text = " ".join(full_text)
                response.segments = all_segments
                # Use the determined language (provided or detected from first chunk)
                response.language = audio_language or "en" 
                print(f"\nCombined transcription from chunks. Total segments: {len(all_segments)}, Language: {response.language}")
                audio_processed = True # Mark as processed via chunks

                # --- Removed the old single-file transcription block --- 
                # elif audio_processed: 
                #     # ... (code that transcribed temp_output_path directly) ...
                
                if not audio_processed: 
                    # This case should not be reached anymore with forced chunking
                    raise Exception("Audio processing failed. Chunk processing did not succeed.")

            except Exception as e:
                print(f"Audio processing or transcription error: {str(e)}")
                # Log traceback for detailed debugging
                import traceback
                traceback.print_exc() 
                if hasattr(e, '__dict__'):
                    print(f"Error details: {e.__dict__}")
                raise HTTPException(
                    status_code=500,
                    detail=f"Error during audio processing or transcription: {str(e)}"
                )

            # Translate if not in English
            try:
                # Use the determined language for translation check
                source_language_for_translation = response.language
                print(f"\nChecking language for translation: {source_language_for_translation}")
                if source_language_for_translation and source_language_for_translation.lower() not in ['en', 'english']:
                    print(f"Language is not English. Translating segments from '{source_language_for_translation}'...")
                    # Ensure segments exist before attempting translation
                    if hasattr(response, 'segments') and response.segments:
                        response.segments = translate_segments(response.segments, source_language_for_translation)
                        print("Translation completed successfully")
                    else:
                         print("No segments found to translate.")
                else:
                    print("Language is English or undetermined. No translation needed.")
            except Exception as e:
                print(f"Translation error: {str(e)}")
                import traceback
                traceback.print_exc()
                # Continue even if translation fails, but log it

            # Continue with the rest of the function
            # Extract screenshots for each segment if it's a video file
            screenshot_count = 0
            if file_extension in {'.mp4', '.mpeg', '.webm', '.mov', '.mkv'}:
                 print("\nExtracting screenshots for video segments...")
                 # Ensure response.segments exists and is iterable
                 if hasattr(response, 'segments') and response.segments:
                    total_segments_for_screenshots = len(response.segments)
                    print(f"Attempting to extract screenshots for {total_segments_for_screenshots} segments.")
                    for i, segment in enumerate(response.segments):
                        #print(f"Processing segment {i+1}/{total_segments_for_screenshots} for screenshot (Start: {segment.start:.2f})")
                        screenshot_filename = f"{video_hash}_{segment['start']:.2f}.jpg" # Use hash to ensure uniqueness
                        screenshot_path = os.path.join(screenshots_dir, screenshot_filename)
                        
                        # Ensure segment.start is a valid number
                        segment_start_time = segment.get('start', None)
                        if segment_start_time is None or not isinstance(segment_start_time, (int, float)):
                             print(f"Warning: Invalid start time for segment {i+1}. Skipping screenshot.")
                             segment['screenshot_url'] = None
                             continue

                        success = extract_screenshot(temp_input_path, segment_start_time, screenshot_path)
                        if success and os.path.exists(screenshot_path):
                            # Add screenshot URL to segment
                            screenshot_url = f"/static/screenshots/{screenshot_filename}"
                            segment['screenshot_url'] = screenshot_url
                            screenshot_count += 1
                            #print(f"Segment {i+1}: Screenshot added - {screenshot_url}")
                        else:
                            segment['screenshot_url'] = None
                            #print(f"Segment {i+1}: Failed to add screenshot.")
                    print(f"\nFinished screenshot extraction. Successfully added {screenshot_count} screenshots.")
                 else:
                      print("No segments available to extract screenshots from.")
            else:
                 print("\nFile is not a video format. Skipping screenshot extraction.")

            # Add speaker diarization
            try:
                print("\n" + "="*60)
                print("Adding speaker labels to segments...")
                print("="*60)

                # Use the original input file for diarization (better quality)
                all_segments = add_speaker_labels(
                    audio_path=temp_input_path,
                    segments=all_segments,
                    num_speakers=None  # Auto-detect number of speakers
                )

                # Update response segments with speaker information
                response.segments = all_segments

                print("Speaker labeling complete!")
            except Exception as e:
                print(f"⚠️  Speaker diarization failed: {str(e)}")
                # Continue without speaker labels
                import traceback
                traceback.print_exc()
                # Ensure all segments have a speaker field
                for seg in all_segments:
                    if 'speaker' not in seg:
                        seg['speaker'] = "SPEAKER_00"

            # Process transcription result
            print("\nProcessing final transcription result...")
            result = {
                "filename": file.filename,
                "video_hash": video_hash, # Include hash in response
                "transcription": {
                    "text": getattr(response, 'text', ''), # Safely get text
                    # Store the determined language (provided or detected)
                    "language": getattr(response, 'language', 'unknown'), # Safely get language
                    "segments": []
                }
            }

            # Convert segments to dictionary format
            if hasattr(response, 'segments') and response.segments:
                for segment in response.segments:
                    # Use dict access for all fields
                    segment_id = segment.get('id', None)
                    segment_start = segment.get('start', 0.0)
                    segment_end = segment.get('end', 0.0)
                    segment_text = segment.get('text', '')
                    segment_translation = segment.get('translation', None)
                    segment_screenshot_url = segment.get('screenshot_url', None)
                    segment_speaker = segment.get('speaker', 'SPEAKER_00')  # Get speaker label
                    segment_dict = {
                        "id": segment_id,
                        "start": segment_start,
                        "end": segment_end,
                        "start_time": format_timestamp(segment_start),
                        "end_time": format_timestamp(segment_end),
                        "text": segment_text,
                        "translation": segment_translation,  # Always include translation field
                        "speaker": segment_speaker  # Add speaker field
                    }
                    if segment_screenshot_url:
                        segment_dict["screenshot_url"] = segment_screenshot_url
                    result["transcription"]["segments"].append(segment_dict)
            else:
                print("Warning: No segments found in the final response object.")

            # --- Ensure unique IDs for all segments --- 
            print("\nEnsuring unique IDs for all segments before storing...")
            assigned_ids = set()
            final_segments = []
            for segment_dict in result["transcription"]["segments"]:
                # Always generate a new UUID to guarantee uniqueness across chunks
                new_id = str(uuid.uuid4())
                # Ensure the generated UUID is truly unique (highly unlikely collision, but safe)
                while new_id in assigned_ids:
                    new_id = str(uuid.uuid4())
                
                segment_dict["id"] = new_id # Assign the guaranteed unique ID
                assigned_ids.add(new_id)
                final_segments.append(segment_dict) # Add to the final list
            
            # Replace the segments list with the one containing guaranteed unique IDs
            result["transcription"]["segments"] = final_segments
            print(f"Assigned unique UUIDs to {len(result['transcription']['segments'])} segments.")
            # --- End of unique ID assignment --- 

            # Store the transcription data, including the permanent file path
            print(f"\nStoring transcription in database with hash: {video_hash}")
            store_transcription(video_hash, file.filename, result, permanent_file_path)
            
            # Store as last transcription
            dependencies._last_transcription_data = result
            request.app.state.last_transcription = result
            
            total_duration = time.time() - start_time
            result["processing_time"] = format_eta(int(total_duration))
            
            # Add video URL to the result using the hash
            result["video_url"] = f"/video/{video_hash}"
            
            print(f"\nTranscription processing completed successfully in {result['processing_time']}.")
            print(f"Returning result for {result['filename']} (Hash: {result['video_hash']})")
            return result
    except HTTPException as e:
        print(f"HTTP Exception: {e.detail}")
        raise e
    except Exception as e:
        print(f"Unexpected error: {str(e)}")
        if hasattr(e, '__dict__'):
            print(f"Error details: {e.__dict__}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/transcribe_local/")
async def transcribe_local(
    file: UploadFile,
    request: Request,
    num_speakers: int = Form(None),
    min_speakers: int = Form(None),
    max_speakers: int = Form(None),
    language: str = Form(None),
    force_language: bool = Form(False)
) -> Dict:
    """Transcribe uploaded audio/video file locally using faster-whisper.

    Args:
        file: Audio/video file to transcribe
        num_speakers: Exact number of speakers (if known)
        min_speakers: Minimum number of speakers for diarization
        max_speakers: Maximum number of speakers for diarization
        language: Optional language code (e.g., 'es', 'it', 'en'). If provided,
                  Whisper will use this instead of auto-detection.
        force_language: If True, completely override Whisper's detection with provided language
    """
    
    print(f"[INFO] Using local faster-whisper. Params: num_speakers={num_speakers}, min={min_speakers}, max={max_speakers}, language={language}, force_language={force_language}")
    try:
        suffix = Path(file.filename).suffix
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            content = await file.read()
            tmp.write(content)
            temp_path = tmp.name

        # Generate hash for the file
        video_hash = generate_file_hash(temp_path)
        print(f"Generated hash for video: {video_hash}")
        
        # Check if we already have a transcription for this file
        existing_transcription = get_transcription(video_hash)
        if existing_transcription:
            # Check if the cached transcription is valid (has segments)
            segments_count = len(existing_transcription.get('transcription', {}).get('segments', []))
            if segments_count == 0:
                print(f"⚠ WARNING: Found cached transcription with 0 segments. Deleting and re-transcribing...")
                # Delete the invalid cached transcription
                try:
                    conn = sqlite3.connect('transcriptions.db')
                    cursor = conn.cursor()
                    cursor.execute("DELETE FROM transcriptions WHERE video_hash = ?", (video_hash,))
                    conn.commit()
                    conn.close()
                    print(f"Deleted invalid cached transcription for {video_hash}")
                except Exception as e:
                    print(f"Error deleting invalid transcription: {str(e)}")
                # Continue with new transcription (don't return, fall through)
            else:
                print(f"Found existing transcription for {file.filename} with hash {video_hash} ({segments_count} segments)")
                dependencies._last_transcription_data = existing_transcription
                request.app.state.last_transcription = existing_transcription
                return existing_transcription

        # Save a permanent copy of the video file
        permanent_storage_dir = os.path.join("static", "videos")
        os.makedirs(permanent_storage_dir, exist_ok=True)
        permanent_file_path = os.path.join(permanent_storage_dir, f"{video_hash}{suffix}")
        if not os.path.exists(permanent_file_path):
            shutil.copy2(temp_path, permanent_file_path)
            print(f"Saved permanent copy of video to: {permanent_file_path}")
        else:
            print(f"Permanent copy already exists at: {permanent_file_path}")

        # Convert MKV to MP4 for browser compatibility
        if suffix == '.mkv':
            mp4_path = os.path.join(permanent_storage_dir, f"{video_hash}.mp4")
            if not os.path.exists(mp4_path):
                print("\nMKV file detected - converting to MP4 for browser compatibility...")
                conversion_success = convert_mkv_to_mp4(permanent_file_path, mp4_path)
                if conversion_success:
                    print(f"Conversion successful! Using MP4 file for playback.")
                    permanent_file_path = mp4_path
                    temp_path = mp4_path  # Use converted file for screenshots
                else:
                    print(f"WARNING: Conversion failed. Video playback may not work in browser.")
            else:
                print(f"MP4 version already exists at: {mp4_path}")
                permanent_file_path = mp4_path
                temp_path = mp4_path

        # Get audio duration
        duration = 0.0
        try:
            duration = get_audio_duration(temp_path)
            duration_str = str(timedelta(seconds=int(duration)))
        except Exception as e:
            print(f"Error getting duration: {e}")
            duration_str = "Unknown"

        # Intelligently determine max_speakers based on duration if not provided
        if max_speakers is None and num_speakers is None:
            if duration < 300: # Less than 5 minutes
                print(f"Short video detected ({duration}s). Setting max_speakers=5.")
                max_speakers = 5
            else:
                print(f"Long video detected ({duration}s). Setting max_speakers=20.")
                max_speakers = 20

        start_time = time.time()
        
        # Convert to WAV first to avoid 'av' decoding issues with MP4
        # Create a temporary WAV file
        wav_suffix = ".wav"
        temp_wav_path = None
        with tempfile.NamedTemporaryFile(suffix=wav_suffix, delete=False) as wav_tmp:
            temp_wav_path = wav_tmp.name
            
        print(f"Converting input to WAV: {temp_wav_path}")
        try:
            # Convert to mono 16kHz WAV using ffmpeg
            command = [
                'ffmpeg', '-i', temp_path,
                '-vn', '-ac', '1', '-ar', '16000',
                temp_wav_path, '-y'
            ]
            result = subprocess.run(command, check=True, capture_output=True)
            print("Conversion to WAV successful")
            transcribe_input = temp_wav_path
        except subprocess.CalledProcessError as e:
            print(f"FFmpeg conversion failed with exit code {e.returncode}")
            print(f"FFmpeg stderr: {e.stderr.decode()}")
            raise HTTPException(status_code=400, detail=f"Failed to process audio: {e.stderr.decode()}")
        except Exception as e:
            print(f"Unexpected error during audio conversion: {e}")
            raise HTTPException(status_code=500, detail=f"Audio conversion error: {str(e)}")

        # --- KEY: Transcribe to original language, then translate if needed ---
        # Build transcription parameters
        transcribe_params = {
            "task": "transcribe",
            "beam_size": 5,  # Improved: Increase from 1 to 5 for better accuracy
            "vad_filter": True,  # Add Voice Activity Detection for better timing
            "vad_parameters": dict(
                min_silence_duration_ms=500,
                threshold=0.5
            )
        }

        # Add language parameter if provided
        if language:
            transcribe_params["language"] = language
            print(f"[INFO] Using specified language: {language}")

        segments, info = local_whisper_model.transcribe(
            transcribe_input,
            **transcribe_params
        )
        processing_time = time.time() - start_time

        # Detect language from transcription
        detected_language = info.language
        print(f"[INFO] Whisper detected language: {detected_language}")

        # Validate and potentially override detected language
        if language and not force_language:
            if detected_language != language:
                print(f"[WARNING] Language mismatch! Specified: {language}, Detected: {detected_language}")
                print(f"[WARNING] Using specified language: {language}")
                detected_language = language
        elif force_language and language:
            print(f"[INFO] Force override - using: {language}")
            detected_language = language
        
        # Format segments to match expected structure and preserve original language
        # IMPORTANT: Convert generator to list first, as generators can only be consumed once
        segments_list = list(segments)
        print(f"Total segments from Whisper: {len(segments_list)}")
        
        formatted_segments = []
        for i, seg in enumerate(segments_list):
            formatted_segments.append({
                "id": str(uuid.uuid4()),
                "start": seg.start,
                "end": seg.end,
                "start_time": format_timestamp(seg.start),
                "end_time": format_timestamp(seg.end),
                "text": seg.text,    # Original language text
                "translation": None,  # Will be populated by translate_segments if needed
            })
        
        print(f"Formatted {len(formatted_segments)} segments")

        # Language code normalization map
        language_code_map = {
            'spanish': 'es', 'español': 'es', 'es': 'es',
            'italian': 'it', 'italiano': 'it', 'it': 'it',
            'french': 'fr', 'français': 'fr', 'fr': 'fr',
            'german': 'de', 'deutsch': 'de', 'de': 'de',
            'portuguese': 'pt', 'português': 'pt', 'pt': 'pt',
            'russian': 'ru', 'русский': 'ru', 'ru': 'ru',
            'chinese': 'zh', 'zh': 'zh',
            'japanese': 'ja', 'ja': 'ja',
            'korean': 'ko', 'ko': 'ko',
            'english': 'en', 'en': 'en'
        }

        # Normalize language code
        normalized_lang = language_code_map.get(detected_language.lower(), detected_language.lower())
        print(f"[INFO] Normalized language code: '{detected_language}' -> '{normalized_lang}'")

        # Translate if source language is not English
        should_translate = normalized_lang not in ['en', 'english']

        if should_translate:
            print(f"[INFO] Detected language: {normalized_lang}. Translating {len(formatted_segments)} segments to English...")

            try:
                # Check if MarianMT model exists for this language
                model_name = f"Helsinki-NLP/opus-mt-{normalized_lang}-en"
                print(f"[INFO] Using translation model: {model_name}")

                formatted_segments = translate_segments(formatted_segments, normalized_lang)

                # Validate translations were actually generated
                translated_count = sum(1 for s in formatted_segments if s.get('translation'))
                if translated_count == 0:
                    raise Exception(f"Translation generated 0 translations for {len(formatted_segments)} segments!")

                print(f"[SUCCESS] Translation completed: {translated_count}/{len(formatted_segments)} segments translated")

            except Exception as e:
                error_msg = f"Translation failed: {str(e)}"
                print(f"[ERROR] {error_msg}")
                import traceback
                traceback.print_exc()

                # Store error in segments for user visibility
                for segment in formatted_segments:
                    segment['translation'] = f"[Translation Error: {normalized_lang}->en model not available]"
                    segment['translation_error'] = str(e)
        else:
            print("[INFO] Language is English. No translation needed.")
            # Populate translation field with same text for consistency
            for segment in formatted_segments:
                segment['translation'] = segment['text']

        # Extract screenshots if it's a video file
        screenshots_dir = os.path.join("static", "screenshots")
        os.makedirs(screenshots_dir, exist_ok=True)
        screenshot_count = 0
        
        if suffix.lower() in {'.mp4', '.mpeg', '.webm', '.mov', '.mkv'}:
            print("\nExtracting screenshots for video segments...")
            for segment in formatted_segments:
                screenshot_filename = f"{video_hash}_{segment['start']:.2f}.jpg"
                screenshot_path = os.path.join(screenshots_dir, screenshot_filename)
                
                success = extract_screenshot(temp_path, segment['start'], screenshot_path)
                if success and os.path.exists(screenshot_path):
                    screenshot_url = f"/static/screenshots/{screenshot_filename}"
                    segment["screenshot_url"] = screenshot_url
                    screenshot_count += 1
                else:
                    segment["screenshot_url"] = None
            
            print(f"\nFinished screenshot extraction. Successfully added {screenshot_count} screenshots.")

        # Add speaker diarization
        try:
            print("\nAdding speaker labels...")
            formatted_segments = add_speaker_labels(
                audio_path=temp_path,
                segments=formatted_segments,
                num_speakers=num_speakers,
                min_speakers=min_speakers,
                max_speakers=max_speakers
            )
            print("Speaker labeling complete")
        except Exception as e:
            print(f"⚠️  Speaker diarization failed: {str(e)}")
            # Continue without speaker labels - ensure all segments have speaker field
            for seg in formatted_segments:
                if 'speaker' not in seg:
                    seg['speaker'] = "SPEAKER_00"

        # Calculate translation statistics for user feedback
        translation_stats = {
            'total_segments': len(formatted_segments),
            'segments_translated': sum(1 for s in formatted_segments if s.get('translation') and not s.get('translation_error')),
            'translation_errors': sum(1 for s in formatted_segments if s.get('translation_error')),
            'detected_language': detected_language,
            'normalized_language': normalized_lang,
            'translation_attempted': should_translate
        }
        print(f"[STATS] Translation: {translation_stats['segments_translated']}/{translation_stats['total_segments']} successful")

        result = {
            "filename": file.filename,
            "video_hash": video_hash,
            "transcription": {
                "text": "".join([seg.text for seg in segments_list]),
                "language": info.language,
                "duration": duration_str,
                "segments": formatted_segments,
                "processing_time": format_eta(int(processing_time))
            },
            "translation_stats": translation_stats
        }

        # Store the transcription data
        store_transcription(video_hash, file.filename, result, permanent_file_path)
        
        # Store as last transcription in both global variable and request state
        dependencies._last_transcription_data = result
        request.app.state.last_transcription = result
        
        # Add video URL to the result
        result["video_url"] = f"/video/{video_hash}"

        # Clean up temporary files
        try:
            if os.path.exists(temp_path):
                os.unlink(temp_path)
            if temp_wav_path and os.path.exists(temp_wav_path):
                os.unlink(temp_wav_path)
        except Exception as e:
            print(f"Error cleaning up temp file: {e}")

        return result
    except Exception as e:
        print(f"Error in local transcription: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))



@router.post("/transcribe_local_stream/")
async def transcribe_local_stream(
    file: UploadFile,
    request: Request,
    num_speakers: int = Form(None),
    min_speakers: int = Form(None),
    max_speakers: int = Form(None),
    language: str = Form(None),
    force_language: bool = Form(False)
):
    """Transcribe with real-time progress updates via Server-Sent Events.

    Args:
        language: Optional language code (e.g., 'es', 'it', 'en')
        force_language: If True, override Whisper's detection with provided language
    """

    async def generate_progress():
        
        try:
            # Progress helper
            def emit(stage: str, progress: int, message: str = ""):
                return f"data: {json.dumps({'stage': stage, 'progress': progress, 'message': message})}\n\n"

            yield emit("uploading", 10, "Receiving file...")

            # Save uploaded file
            suffix = Path(file.filename).suffix
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
                content = await file.read()
                tmp.write(content)
                temp_path = tmp.name

            yield emit("uploading", 20, "File uploaded successfully")

            # Generate hash and check cache
            video_hash = generate_file_hash(temp_path)
            existing_transcription = get_transcription(video_hash)

            if existing_transcription:
                segments_count = len(existing_transcription.get('transcription', {}).get('segments', []))
                if segments_count > 0:
                    print(f"Found cached transcription with {segments_count} segments")
                    yield emit("complete", 100, "Loaded from cache")
                    yield f"data: {json.dumps({'stage': 'complete', 'progress': 100, 'result': existing_transcription})}\n\n"
                    return

            # Save permanent copy
            permanent_storage_dir = os.path.join("static", "videos")
            os.makedirs(permanent_storage_dir, exist_ok=True)
            permanent_file_path = os.path.join(permanent_storage_dir, f"{video_hash}{suffix}")
            if not os.path.exists(permanent_file_path):
                shutil.copy2(temp_path, permanent_file_path)

            # Get duration
            duration = 0.0
            try:
                duration = get_audio_duration(temp_path)
                duration_str = str(timedelta(seconds=int(duration)))
            except Exception as e:
                duration_str = "Unknown"

            # Determine max_speakers
            computed_max_speakers = max_speakers
            if computed_max_speakers is None and num_speakers is None:
                computed_max_speakers = 5 if duration < 300 else 20

            yield emit("extracting", 30, "Converting audio to WAV format...")

            # Convert to WAV
            wav_suffix = ".wav"
            temp_wav_path = None
            with tempfile.NamedTemporaryFile(suffix=wav_suffix, delete=False) as wav_tmp:
                temp_wav_path = wav_tmp.name

            command = [
                'ffmpeg', '-i', temp_path,
                '-vn', '-ac', '1', '-ar', '16000',
                temp_wav_path, '-y'
            ]
            subprocess.run(command, check=True, capture_output=True)

            yield emit("transcribing", 45, "Starting AI transcription...")

            start_time = time.time()

            # Build transcription parameters
            transcribe_params = {
                "task": "transcribe",
                "beam_size": 5,  # Better accuracy
                "vad_filter": True,
                "vad_parameters": dict(
                    min_silence_duration_ms=500,
                    threshold=0.5
                )
            }

            # Add language parameter if provided
            if language:
                transcribe_params["language"] = language
                print(f"[INFO] Stream: Using specified language: {language}")

            segments, info = local_whisper_model.transcribe(
                temp_wav_path,
                **transcribe_params
            )

            yield emit("transcribing", 60, "Processing transcription segments...")

            segments_list = list(segments)
            detected_language = info.language
            print(f"[INFO] Stream: Whisper detected language: {detected_language}")

            # Validate and potentially override detected language
            if language and not force_language:
                if detected_language != language:
                    print(f"[WARNING] Stream: Language mismatch! Specified: {language}, Detected: {detected_language}")
                    detected_language = language
            elif force_language and language:
                print(f"[INFO] Stream: Force override - using: {language}")
                detected_language = language

            formatted_segments = []
            total_segments = len(segments_list)
            for i, seg in enumerate(segments_list):
                formatted_segments.append({
                    "id": str(uuid.uuid4()),
                    "start": seg.start,
                    "end": seg.end,
                    "start_time": format_timestamp(seg.start),
                    "end_time": format_timestamp(seg.end),
                    "text": seg.text,
                    "translation": None,
                })

                # Emit progress every 10 segments
                if i % 10 == 0:
                    segment_progress = 60 + int((i / total_segments) * 10)
                    yield emit("transcribing", segment_progress, f"Processed {i}/{total_segments} segments...")

            processing_time = time.time() - start_time

            yield emit("transcribing", 70, "Translating if needed...")

            # Language code normalization
            language_code_map = {
                'spanish': 'es', 'español': 'es', 'es': 'es',
                'italian': 'it', 'italiano': 'it', 'it': 'it',
                'french': 'fr', 'français': 'fr', 'fr': 'fr',
                'german': 'de', 'deutsch': 'de', 'de': 'de',
                'portuguese': 'pt', 'português': 'pt', 'pt': 'pt',
                'russian': 'ru', 'русский': 'ru', 'ru': 'ru',
                'chinese': 'zh', 'zh': 'zh',
                'japanese': 'ja', 'ja': 'ja',
                'korean': 'ko', 'ko': 'ko',
                'english': 'en', 'en': 'en'
            }

            normalized_lang = language_code_map.get(detected_language.lower(), detected_language.lower())
            print(f"[INFO] Stream: Normalized language: '{detected_language}' -> '{normalized_lang}'")
            should_translate = normalized_lang not in ['en', 'english']

            # Translate if not English
            if should_translate:
                try:
                    formatted_segments = translate_segments(formatted_segments, normalized_lang)
                    translated_count = sum(1 for s in formatted_segments if s.get('translation'))
                    print(f"[SUCCESS] Stream: Translated {translated_count}/{len(formatted_segments)} segments")
                except Exception as e:
                    print(f"[ERROR] Stream: Translation failed: {str(e)}")
                    for segment in formatted_segments:
                        segment['translation'] = f"[Translation Error: {normalized_lang}->en]"
                        segment['translation_error'] = str(e)
            else:
                print("[INFO] Stream: Language is English, no translation needed")
                for segment in formatted_segments:
                    segment['translation'] = segment['text']

            yield emit("extracting", 75, "Extracting video screenshots...")

            # Extract screenshots
            screenshots_dir = os.path.join("static", "screenshots")
            os.makedirs(screenshots_dir, exist_ok=True)
            screenshot_count = 0

            if suffix.lower() in {'.mp4', '.mpeg', '.webm', '.mov', '.mkv'}:
                for idx, segment in enumerate(formatted_segments):
                    screenshot_filename = f"{video_hash}_{segment['start']:.2f}.jpg"
                    screenshot_path = os.path.join(screenshots_dir, screenshot_filename)

                    success = extract_screenshot(temp_path, segment['start'], screenshot_path)
                    if success and os.path.exists(screenshot_path):
                        segment["screenshot_url"] = f"/static/screenshots/{screenshot_filename}"
                        screenshot_count += 1
                    else:
                        segment["screenshot_url"] = None

                    # Progress update every 5 screenshots
                    if idx % 5 == 0:
                        screenshot_progress = 75 + int((idx / len(formatted_segments)) * 10)
                        yield emit("extracting", screenshot_progress, f"Screenshots: {idx}/{len(formatted_segments)}")

            yield emit("transcribing", 85, "Identifying speakers...")

            # Speaker diarization
            try:
                formatted_segments = add_speaker_labels(
                    audio_path=temp_path,
                    segments=formatted_segments,
                    num_speakers=num_speakers,
                    min_speakers=min_speakers,
                    max_speakers=computed_max_speakers
                )
            except Exception as e:
                print(f"Speaker diarization failed: {str(e)}")
                for seg in formatted_segments:
                    if 'speaker' not in seg:
                        seg['speaker'] = "SPEAKER_00"

            yield emit("complete", 95, "Finalizing transcription...")

            # Build result
            result = {
                "filename": file.filename,
                "video_hash": video_hash,
                "transcription": {
                    "text": "".join([seg.text for seg in segments_list]),
                    "language": info.language,
                    "duration": duration_str,
                    "segments": formatted_segments,
                    "processing_time": format_eta(int(processing_time))
                }
            }

            # Store transcription
            store_transcription(video_hash, file.filename, result, permanent_file_path)
            dependencies._last_transcription_data = result
            request.app.state.last_transcription = result
            result["video_url"] = f"/video/{video_hash}"

            # Clean up
            try:
                if os.path.exists(temp_path):
                    os.unlink(temp_path)
                if temp_wav_path and os.path.exists(temp_wav_path):
                    os.unlink(temp_wav_path)
            except Exception as e:
                print(f"Error cleaning up: {e}")

            # Send final result
            yield emit("complete", 100, "Transcription complete!")
            yield f"data: {json.dumps({'stage': 'complete', 'progress': 100, 'result': result})}\n\n"

        except Exception as e:
            print(f"Error in streaming transcription: {e}")
            import traceback
            traceback.print_exc()
            yield f"data: {json.dumps({'stage': 'error', 'progress': 0, 'error': str(e)})}\n\n"

    return StreamingResponse(generate_progress(), media_type="text/event-stream")
