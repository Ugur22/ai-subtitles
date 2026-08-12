"""
Transcription endpoints - core functionality for video/audio transcription
"""
import os
import shutil
import tempfile
import uuid
from pathlib import Path
from typing import Dict, List, Optional
from fastapi import APIRouter, HTTPException, Request, Query

from config import settings
from middleware.auth import require_auth
from models import (
    TranslationRequest,
    TranslationResponse,
    ErrorResponse
)
from services.video_service import VideoService
from services.translation_service import TranslationService
from services.summarization_service import SummarizationService
from services.audio_analysis_service import AudioAnalysisService
from services.media_storage import get_media_storage
from services.transcription_access import (
    authenticated_user_id,
)
from services.transcription_repository import transcription_repository
from utils.time_utils import format_timestamp, time_to_seconds, time_diff_minutes

router = APIRouter(tags=["Transcription"])


def _refresh_owned_screenshot_urls(
    transcription: Dict, user_id: str, video_hash: str
) -> Dict:
    """Refresh owned screenshot URLs and remove references that fail ownership checks."""
    storage = get_media_storage()
    segments = transcription.get("transcription", {}).get("segments", [])
    for segment in segments:
        reference = segment.get("screenshot_url")
        if not reference:
            continue
        object_key = storage.parse_screenshot_key(reference)
        if not object_key or not storage.is_owned_screenshot_key(
            object_key, user_id, video_hash
        ):
            segment["screenshot_url"] = None
            continue
        try:
            segment["screenshot_url"] = storage.generate_download_url(object_key)
        except Exception:
            segment["screenshot_url"] = None
    return transcription


@router.get(
    "/transcription/{video_hash}",
    response_model=Dict,
    summary="Get transcription by hash",
    description="Retrieve a specific transcription by its video hash",
    responses={
        404: {"model": ErrorResponse, "description": "Transcription not found"}
    }
)
@require_auth
async def get_saved_transcription(request: Request, video_hash: str) -> Dict:
    """Get a specific transcription by hash"""
    user_id = authenticated_user_id(request)
    transcription = transcription_repository.get_transcription(video_hash, user_id)
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
                transcription_repository.update_transcription(video_hash, user_id, transcription)
                print(f"Translation complete and saved for video_hash={video_hash}.")
        else:
            # If English source, ensure all segments have a translation field (set to text for consistency)
            for seg in segments:
                if 'translation' not in seg or not seg.get('translation'):
                    seg['translation'] = seg.get('text', '')
    except Exception as e:
        print(f"Error ensuring translations in /transcription/{{video_hash}}: {e}")

    return _refresh_owned_screenshot_urls(transcription, user_id, video_hash)


@router.post(
    "/translate_local/",
    response_model=TranslationResponse,
    summary="Translate text locally",
    description="Translate text to English using local MarianMT model",
    responses={
        400: {"model": ErrorResponse, "description": "Missing required fields"}
    }
)
@require_auth
async def translate_local_endpoint(http_request: Request, request: TranslationRequest) -> TranslationResponse:
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
@require_auth
async def generate_summary(
    request: Request,
    video_hash: Optional[str] = Query(None, description="Video hash to load from persisted jobs")
) -> Dict:
    """Generate section summaries from transcription using local model.

    Loads the authenticated user's transcription from Supabase jobs.
    """
    if not video_hash:
        raise HTTPException(status_code=400, detail="video_hash is required")
    user_id = authenticated_user_id(request)
    transcription = transcription_repository.get_transcription(video_hash, user_id)
    if transcription:
        transcription = _refresh_owned_screenshot_urls(
            transcription, user_id, video_hash
        )

    # Error if no transcription found
    if not transcription:
        raise HTTPException(
            status_code=404,
            detail="No transcription available. Please provide video_hash or transcribe a video first."
        )

    # Include the filename in the response
    filename = transcription.get('filename', 'unknown_filename')
    print(f"Generating summary for: {filename}")

    segments = transcription['transcription']['segments']
    print(f"Found {len(segments)} segments for summarization")

    # Debug: Check if segments have screenshot_url
    segments_with_screenshots = sum(1 for seg in segments if seg.get('screenshot_url'))
    print(f"[Summary Debug] Segments with screenshot_url: {segments_with_screenshots}/{len(segments)}")

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

            # Get screenshot_url from first segment of the section
            screenshot_url = None
            for seg in section["segments"]:
                if seg.get("screenshot_url"):
                    screenshot_url = seg["screenshot_url"]
                    break

            # Debug log for first few sections
            if section_index < 3:
                print(f"[Summary Debug] Section {section_index}: screenshot_url={screenshot_url}")

            summaries.append({
                "title": title,
                "start": section["start"],
                "end": section["end"],
                "summary": summary,
                "screenshot_url": screenshot_url
            })
        except Exception as e:
            print(f"Error generating summary for section {section['start']}-{section['end']}: {e}")
            # Get screenshot_url even for failed summaries
            screenshot_url = None
            for seg in section["segments"]:
                if seg.get("screenshot_url"):
                    screenshot_url = seg["screenshot_url"]
                    break
            # Add a placeholder for failed summaries
            summaries.append({
                "title": f"Section {section['start']}-{section['end']}",
                "start": section["start"],
                "end": section["end"],
                "summary": "Summary generation failed. Please try again.",
                "screenshot_url": screenshot_url
            })

    # Log summary generation results
    print(f"Generated {len(summaries)} section summaries")

    return {
        "summaries": summaries,
        "filename": filename,
        "sections_count": len(sections)
    }


@router.post(
    "/analyze_audio/{video_hash}",
    summary="Analyze audio for existing video",
    description="Run audio analysis (events, emotions) on an already-transcribed video without re-transcribing",
    tags=["Transcription"]
)
@require_auth
async def analyze_audio_for_video(request: Request, video_hash: str, force_reindex: bool = False):
    """
    Analyze audio events and emotions for an existing transcription.

    This allows adding audio analysis to videos that were transcribed before
    audio analysis was available, without needing to re-transcribe.

    Args:
        video_hash: The video hash to analyze
        force_reindex: If True, re-analyze even if already done
    """
    materialized_audio = None
    try:
        # Get existing transcription
        user_id = authenticated_user_id(request)
        transcription = transcription_repository.get_transcription(video_hash, user_id)
        if not transcription:
            raise HTTPException(status_code=404, detail="Transcription not found")

        # Check if audio analysis is enabled
        if not settings.ENABLE_AUDIO_ANALYSIS:
            raise HTTPException(status_code=400, detail="Audio analysis is disabled in settings")

        job = transcription_repository.get_job(video_hash, user_id)
        if not job:
            raise HTTPException(status_code=404, detail="Video media is not available")
        result_json = job.get("result_json") or {}
        media_key = job.get("gcs_path") or result_json.get("gcs_path")
        if not media_key:
            raise HTTPException(status_code=404, detail="Video media is not available")
        media_storage = get_media_storage()
        if not media_storage.is_owned_media_key(media_key, user_id):
            raise HTTPException(status_code=403, detail="Video media is not owned by this user")
        if not media_storage.file_exists(media_key):
            raise HTTPException(status_code=404, detail="Video media is not available")
        materialized_audio = media_storage.download_to_temp(
            media_key,
            suffix=Path(job.get("filename") or "media.mp4").suffix,
        )

        # Get segments
        segments = transcription.get('transcription', {}).get('segments', [])
        if not segments:
            raise HTTPException(status_code=400, detail="No segments found in transcription")

        print(f"Analyzing audio for video {video_hash} with {len(segments)} segments...")

        # Run audio analysis
        from services.audio_analysis_service import AudioAnalysisService

        analyzed_segments = AudioAnalysisService.analyze_segments(
            audio_path=materialized_audio,
            segments=segments,
            video_hash=video_hash
        )

        # Also analyze silent segments
        analyzed_segments = AudioAnalysisService.analyze_silent_segments(
            audio_path=materialized_audio,
            segments=analyzed_segments
        )

        # Update transcription in database
        transcription['transcription']['segments'] = analyzed_segments
        if not transcription_repository.update_transcription(video_hash, user_id, transcription):
            raise HTTPException(status_code=404, detail="Transcription not found")

        # Index audio events in vector store
        from services.transcript_embedding_service import transcript_embedding_service
        audio_indexed = transcript_embedding_service.index_audio_events(
            video_hash, analyzed_segments, user_id, force_reindex=force_reindex
        )

        # Create summary
        summary = AudioAnalysisService.create_audio_summary(analyzed_segments)

        return {
            "success": True,
            "video_hash": video_hash,
            "segments_analyzed": len(analyzed_segments),
            "audio_events_indexed": audio_indexed,
            "summary": summary,
            "message": f"Successfully analyzed audio for {len(analyzed_segments)} segments"
        }

    except HTTPException:
        raise
    except Exception as e:
        print(f"Error analyzing audio: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Audio analysis failed: {str(e)}")
    finally:
        if materialized_audio:
            try:
                os.unlink(materialized_audio)
            except OSError:
                pass


@router.post(
    "/regenerate_screenshots/{video_hash}",
    summary="Regenerate screenshots for existing video",
    description="Extract and upload screenshots for an already-transcribed video without re-transcribing",
    tags=["Transcription"]
)
@require_auth
async def regenerate_screenshots_for_video(request: Request, video_hash: str):
    """
    Regenerate screenshots for an existing transcription.

    This is useful when:
    - Screenshots were lost (e.g., stored on ephemeral storage)
    - GCS uploads were not enabled during original transcription
    - Screenshots need to be refreshed

    Args:
        video_hash: The video hash to regenerate screenshots for
    """
    materialized_video = None
    screenshots_dir = None
    try:
        from services.supabase_service import supabase
        user_id = authenticated_user_id(request)
        media_storage = get_media_storage()

        # Get job data from Supabase
        client = supabase()
        job = transcription_repository.get_job(video_hash, user_id)

        if not job:
            raise HTTPException(status_code=404, detail="No completed job found for this video_hash")

        job_id = job.get("id")
        result_json = job.get("result_json")
        gcs_path = job.get("gcs_path") or (result_json.get("gcs_path") if result_json else None)

        if not result_json:
            raise HTTPException(status_code=404, detail="Job result not available")

        if not gcs_path:
            raise HTTPException(status_code=404, detail="Video file path not found in job result")

        if not media_storage.is_owned_media_key(gcs_path, user_id):
            raise HTTPException(status_code=403, detail="Video media is not owned by this user")
        if not media_storage.file_exists(gcs_path):
            raise HTTPException(status_code=404, detail="Video file not found in storage")

        # Get segments from transcription
        segments = result_json.get("transcription", {}).get("segments", [])
        if not segments:
            raise HTTPException(status_code=400, detail="No segments found in transcription")

        print(f"[Screenshots] Regenerating screenshots for {len(segments)} segments, video_hash={video_hash}")

        materialized_video = media_storage.download_to_temp(
            gcs_path, suffix=Path(job.get("filename") or "video.mp4").suffix
        )

        # Get timestamps for all segments
        # Silent segments use screenshot_timestamp (midpoint) for better thumbnails
        timestamps = []
        for seg in segments:
            if seg.get("is_silent") and seg.get("screenshot_timestamp"):
                timestamps.append(seg["screenshot_timestamp"])
            elif seg.get("is_silent"):
                # Legacy silent segments without screenshot_timestamp - use midpoint
                midpoint = (seg.get("start", 0) + seg.get("end", 0)) / 2
                seg["screenshot_timestamp"] = midpoint
                timestamps.append(midpoint)
            else:
                timestamps.append(seg.get("start", 0))

        screenshots_dir = tempfile.mkdtemp(prefix="ai-subs-screenshots-")

        print(f"[Screenshots] Extracting {len(timestamps)} screenshots from video URL...")

        # Extract screenshots in batches using parallel extraction
        batch_size = 20
        screenshot_results = {}

        for batch_start in range(0, len(timestamps), batch_size):
            batch_timestamps = timestamps[batch_start:batch_start + batch_size]

            batch_results = VideoService.extract_screenshots_parallel_from_url(
                source_url=materialized_video,
                timestamps=batch_timestamps,
                output_dir=screenshots_dir,
                video_hash=video_hash,
                max_workers=4
            )
            screenshot_results.update(batch_results)

            print(f"[Screenshots] Extracted batch {batch_start // batch_size + 1}: {len([v for v in batch_results.values() if v])} successful")

        print(f"[Screenshots] Storing {len(screenshot_results)} screenshots...")

        screenshot_urls = media_storage.upload_screenshots_batch(
            screenshot_paths=screenshot_results,
            video_hash=video_hash,
            user_id=user_id,
        )

        # Update segments with new screenshot URLs
        screenshot_count = 0
        for segment in segments:
            if segment.get("is_silent") and segment.get("screenshot_timestamp"):
                ts = segment["screenshot_timestamp"]
            else:
                ts = segment.get("start", 0)
            screenshot_url = screenshot_urls.get(ts)
            if screenshot_url:
                segment["screenshot_url"] = screenshot_url
                screenshot_count += 1
            # Don't null out screenshot_url on miss — keep whatever URL is already there

        print(f"[Screenshots] Updated {screenshot_count}/{len(segments)} screenshot URLs")

        # Update result_json in Supabase
        result_json["transcription"]["segments"] = segments

        update_response = (
            client.table("jobs")
            .update({"result_json": result_json})
            .eq("id", job_id)
            .eq("user_id", user_id)
            .execute()
        )

        print(f"[Screenshots] Updated job {job_id} in Supabase")

        return {
            "success": True,
            "video_hash": video_hash,
            "total_segments": len(segments),
            "screenshots_generated": screenshot_count,
            "message": f"Successfully regenerated {screenshot_count} screenshots for {len(segments)} segments"
        }

    except HTTPException:
        raise
    except Exception as e:
        print(f"Error regenerating screenshots: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Screenshot regeneration failed: {str(e)}")
    finally:
        if materialized_video:
            try:
                os.unlink(materialized_video)
            except OSError:
                pass
        if screenshots_dir:
            shutil.rmtree(screenshots_dir, ignore_errors=True)


def create_silent_segments_for_gaps(segments: List[Dict],
                                     min_gap_duration: float = 2.0,
                                     silent_chunk_duration: float = 10.0) -> List[Dict]:
    """
    Detect timeline gaps between speech segments and create silent segments.

    Pure computation - no screenshot extraction. Each silent segment gets a
    `screenshot_timestamp` field (chunk midpoint) for later parallel extraction.

    Args:
        segments: List of existing speech segments (sorted by start time)
        min_gap_duration: Minimum gap duration (in seconds) to create a silent segment
        silent_chunk_duration: Duration of each silent segment chunk (default: 10 seconds)

    Returns:
        List of segments including both original and new silent segments, sorted by start time
    """
    if not segments:
        return segments

    sorted_segments = sorted(segments, key=lambda s: s['start'])
    result_segments = []
    gaps_found = 0
    total_silent_segments_created = 0

    print(f"\nDetecting silent gaps (minimum duration: {min_gap_duration}s, chunk size: {silent_chunk_duration}s)...")

    for i in range(len(sorted_segments)):
        result_segments.append(sorted_segments[i])

        if i < len(sorted_segments) - 1:
            current_end = sorted_segments[i]['end']
            next_start = sorted_segments[i + 1]['start']
            gap_duration = next_start - current_end

            if gap_duration >= min_gap_duration:
                gaps_found += 1
                num_chunks = max(1, int(gap_duration / silent_chunk_duration))
                chunk_size = gap_duration / num_chunks

                print(f"  Gap {gaps_found}: {current_end:.2f}s - {next_start:.2f}s ({gap_duration:.2f}s) - Creating {num_chunks} silent segments")

                for chunk_idx in range(num_chunks):
                    chunk_start = current_end + (chunk_idx * chunk_size)
                    chunk_end = current_end + ((chunk_idx + 1) * chunk_size)
                    chunk_midpoint = chunk_start + (chunk_size / 2)

                    silent_segment = {
                        "id": str(uuid.uuid4()),
                        "start": chunk_start,
                        "end": chunk_end,
                        "start_time": format_timestamp(chunk_start),
                        "end_time": format_timestamp(chunk_end),
                        "text": "[No speech]",
                        "translation": "[No speech]",
                        "speaker": "VISUAL",
                        "is_silent": True,
                        "screenshot_timestamp": chunk_midpoint
                    }
                    result_segments.append(silent_segment)
                    total_silent_segments_created += 1

    if gaps_found > 0:
        print(f"Created {total_silent_segments_created} silent segments across {gaps_found} timeline gaps")
    else:
        print("No significant gaps found between speech segments")

    return sorted(result_segments, key=lambda s: s['start'])


# =============================================================================
# Search Endpoint
# =============================================================================

from models import SearchResponse, SearchMatch, SearchTimestamp, SearchContext

@router.post(
    "/api/search/",
    response_model=SearchResponse,
    summary="Search transcription",
    description="Search the current transcription for keywords or semantic matches"
)
@require_auth
async def search_transcription(
    request: Request,
    topic: str = Query(..., description="Search query"),
    semantic_search: bool = Query(True, description="Use semantic search"),
    video_hash: Optional[str] = Query(None, description="Video hash to search in")
) -> SearchResponse:
    """Search transcription for keywords or semantic matches"""

    # Get transcription data
    transcription_data = None

    if not video_hash:
        raise HTTPException(status_code=400, detail="video_hash is required")
    user_id = authenticated_user_id(request)
    transcription_data = transcription_repository.get_transcription(
        video_hash,
        user_id,
    )

    if not transcription_data:
        raise HTTPException(
            status_code=404,
            detail="No transcription available. Please provide video_hash or transcribe a video first."
        )

    segments = transcription_data.get('transcription', {}).get('segments', [])
    if not segments:
        return SearchResponse(
            topic=topic,
            total_matches=0,
            semantic_search_used=semantic_search,
            matches=[]
        )

    matches = []
    used_semantic = False

    # Try semantic search first if requested
    if semantic_search:
        try:
            from services.transcript_embedding_service import transcript_embedding_service

            # Get video hash for lookup
            v_hash = video_hash or transcription_data.get('video_hash')
            if v_hash and transcript_embedding_service.transcript_chunks_exist(v_hash, user_id):
                search_results = transcript_embedding_service.search_transcript_chunks(
                    v_hash, topic, user_id, n_results=10
                )
                used_semantic = True

                for result in search_results:
                    metadata = result.get('metadata', {})
                    hit_start = float(metadata.get('start', 0) or 0)
                    hit_end = float(metadata.get('end', hit_start) or hit_start)

                    # Chunks span multiple segments, so resolve the hit to the
                    # transcript segment(s) overlapping its time range rather than
                    # a segment index (the RPC returns start/end times, not one).
                    segment_idx = None
                    for idx, seg in enumerate(segments):
                        seg_start = float(seg.get('start', 0) or 0)
                        seg_end = float(seg.get('end', seg_start) or seg_start)
                        if seg_start <= hit_end and seg_end >= hit_start:
                            segment_idx = idx
                            break

                    if segment_idx is not None:
                        seg = segments[segment_idx]

                        # Get context (1 segment before and after)
                        before_ctx = []
                        after_ctx = []

                        if segment_idx > 0:
                            before_ctx = [segments[segment_idx - 1].get('text', '')]
                        if segment_idx < len(segments) - 1:
                            after_ctx = [segments[segment_idx + 1].get('text', '')]

                        matches.append(SearchMatch(
                            timestamp=SearchTimestamp(
                                start=seg.get('start_time', '00:00:00.000'),
                                end=seg.get('end_time', '00:00:00.000')
                            ),
                            original_text=seg.get('text', ''),
                            translated_text=seg.get('translation'),
                            context=SearchContext(before=before_ctx, after=after_ctx)
                        ))
        except Exception as e:
            print(f"Semantic search failed, falling back to keyword: {e}")
            used_semantic = False

    # Keyword search fallback (or if semantic not requested)
    if not used_semantic or not matches:
        topic_lower = topic.lower()

        for idx, seg in enumerate(segments):
            text = seg.get('text', '')
            translation = seg.get('translation', '')

            if topic_lower in text.lower() or (translation and topic_lower in translation.lower()):
                # Get context
                before_ctx = [segments[idx - 1].get('text', '')] if idx > 0 else []
                after_ctx = [segments[idx + 1].get('text', '')] if idx < len(segments) - 1 else []

                matches.append(SearchMatch(
                    timestamp=SearchTimestamp(
                        start=seg.get('start_time', '00:00:00.000'),
                        end=seg.get('end_time', '00:00:00.000')
                    ),
                    original_text=text,
                    translated_text=translation if translation else None,
                    context=SearchContext(before=before_ctx, after=after_ctx)
                ))

        used_semantic = False

    return SearchResponse(
        topic=topic,
        total_matches=len(matches),
        semantic_search_used=used_semantic,
        matches=matches
    )
