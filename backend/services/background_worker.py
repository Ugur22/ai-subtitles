"""
Background worker for processing transcription jobs
"""
import os
import subprocess
import asyncio
import tempfile
import shutil
import traceback
from typing import Optional, Dict, Callable, Any
from concurrent.futures import ThreadPoolExecutor

# Single worker executor for CPU/GPU-bound tasks
# This prevents blocking the event loop while allowing other requests (auth, status) to be served
_transcription_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="transcribe")


async def _run_in_executor(func: Callable, *args, **kwargs) -> Any:
    """
    Run a blocking function in a thread pool to avoid blocking the event loop.
    This ensures that login/auth requests can be processed even during transcription.
    """
    loop = asyncio.get_event_loop()
    if kwargs:
        return await loop.run_in_executor(
            _transcription_executor,
            lambda: func(*args, **kwargs)
        )
    return await loop.run_in_executor(_transcription_executor, func, *args)

from config import settings
from services.job_queue_service import JobQueueService
from services.gcs_service import gcs_service
from services.audio_service import AudioService
from services.speaker_service import SpeakerService
from services.subtitle_service import SubtitleService
from services.translation_service import TranslationService
from services.video_service import VideoService
from utils.file_utils import generate_file_hash
from utils.time_utils import format_timestamp
from utils.memory_utils import clear_gpu_memory, log_gpu_memory, log_all_memory
from dependencies import get_whisper_model, get_speaker_diarizer, unload_whisper_model
from routers.transcription import create_silent_segments_for_gaps
from speaker_diarization import ChunkedSpeakerDiarizer


# Configuration
HEARTBEAT_INTERVAL = 30  # seconds


def assign_speakers_to_segments(transcription_segments: list, speaker_segments: list) -> list:
    """
    Assign speaker labels from diarization to transcription segments based on time overlap.

    Args:
        transcription_segments: List of transcription segments with 'start' and 'end' times
        speaker_segments: List of speaker diarization segments with 'start', 'end', and 'speaker'

    Returns:
        Transcription segments with added 'speaker' field
    """
    print(f"[Worker] Assigning speakers to {len(transcription_segments)} transcription segments...")

    for trans_seg in transcription_segments:
        # Get the start and end times of the transcription segment
        trans_start = trans_seg.get('start', 0.0)
        trans_end = trans_seg.get('end', 0.0)
        trans_mid = (trans_start + trans_end) / 2

        # Find the speaker segment with maximum overlap
        best_speaker = "UNKNOWN"
        max_overlap = 0

        for spk_seg in speaker_segments:
            spk_start = spk_seg['start']
            spk_end = spk_seg['end']

            # Calculate overlap
            overlap_start = max(trans_start, spk_start)
            overlap_end = min(trans_end, spk_end)
            overlap = max(0, overlap_end - overlap_start)

            if overlap > max_overlap:
                max_overlap = overlap
                best_speaker = spk_seg['speaker']

            # Alternative: Check if midpoint falls within speaker segment
            # This can be faster and often more accurate
            if spk_start <= trans_mid <= spk_end:
                best_speaker = spk_seg['speaker']
                break

        # Assign the speaker to the transcription segment
        trans_seg['speaker'] = best_speaker

    # Count speakers
    unique_speakers = set(seg.get('speaker', 'UNKNOWN') for seg in transcription_segments)
    print(f"[Worker] Speaker assignment complete. Identified {len(unique_speakers)} unique speakers")

    return transcription_segments


class BackgroundWorker:
    """Worker for processing transcription jobs in the background"""

    def __init__(self):
        self.running = False
        self._heartbeat_tasks = {}  # job_id -> asyncio.Task

    async def process_job(self, job_id: str) -> bool:
        """
        Main processing function for a transcription job.

        Workflow:
        1. Get job and verify pending status
        2. Mark as processing
        3. Start heartbeat task
        4. Download from GCS (10% progress)
        5. Extract audio (30% progress)
        6. Transcribe (50% progress)
        7. Speaker diarization (80% progress)
        8. Generate SRT/VTT formats (95% progress)
        9. Calculate video hash
        10. Mark completed
        11. On error: mark failed with user-friendly message
        12. Finally: cancel heartbeat, cleanup temp files

        Args:
            job_id: Job ID to process

        Returns:
            True if successful, False if failed
        """
        temp_files = []
        temp_dirs = []
        heartbeat_task = None

        try:
            # Get job
            job = JobQueueService.get_job(job_id)
            if not job:
                print(f"[Worker] Job {job_id} not found")
                return False

            # Verify pending status
            if job["status"] != "pending":
                print(f"[Worker] Job {job_id} is not pending (status: {job['status']})")
                return False

            # Mark as processing
            JobQueueService.mark_processing(job_id)

            # Start heartbeat task
            heartbeat_task = asyncio.create_task(self._heartbeat_loop(job_id))
            self._heartbeat_tasks[job_id] = heartbeat_task

            # Extract job parameters
            filename = job["filename"]
            gcs_path = job["gcs_path"]
            file_size_bytes = job["file_size_bytes"]
            user_id = job.get("user_id")  # For RLS policy compliance
            params = job.get("params", {})

            num_speakers = params.get("num_speakers")
            min_speakers = params.get("min_speakers")
            max_speakers = params.get("max_speakers")
            language = params.get("language")
            force_language = params.get("force_language", False)

            print(f"[Worker] Processing job {job_id}: {filename} ({file_size_bytes / (1024*1024):.1f} MB)")

            # Step 1: Download from GCS (0-10%)
            JobQueueService.update_progress(job_id, 5, "downloading", "Downloading video from cloud storage...")

            if not gcs_service.file_exists(gcs_path):
                raise Exception("Video file not found in cloud storage")

            # Generate signed URL for streaming
            read_url = gcs_service.generate_download_signed_url(gcs_path)
            print(f"[Worker] Generated read URL for streaming: {gcs_path}")

            JobQueueService.update_progress(job_id, 10, "downloading", "Download verified")

            # Step 2: Extract audio via streaming (10-30%)
            JobQueueService.update_progress(job_id, 15, "extracting", "Extracting audio from video...")

            # Create temp directory for audio chunks
            temp_dir = tempfile.mkdtemp()
            temp_dirs.append(temp_dir)
            print(f"[Worker] Created temp directory for audio: {temp_dir}")

            try:
                # Run in executor to avoid blocking event loop
                audio_chunks = await _run_in_executor(
                    AudioService.extract_audio_streaming,
                    source_url=read_url,
                    output_dir=temp_dir,
                    segment_duration=300  # 5-minute segments
                )
                temp_files.extend(audio_chunks)
                print(f"[Worker] Extracted {len(audio_chunks)} audio chunks")
            except Exception as e:
                raise Exception(f"Failed to extract audio: {str(e)}")

            JobQueueService.update_progress(job_id, 30, "extracting", f"Extracted {len(audio_chunks)} audio segments")

            # Step 3: Transcribe (30-50%)
            JobQueueService.update_progress(job_id, 35, "transcribing", "Starting transcription...")

            # Get Whisper model
            whisper_model = get_whisper_model()

            # Build transcription parameters
            transcribe_params = {
                "task": "transcribe",
                "beam_size": 5,
                "vad_filter": settings.VAD_ENABLED,
                "vad_parameters": dict(
                    min_silence_duration_ms=settings.VAD_MIN_SILENCE_DURATION_MS,
                    threshold=settings.VAD_THRESHOLD
                )
            }

            if language:
                transcribe_params["language"] = language
                print(f"[Worker] Using specified language: {language}")

            # Transcribe each audio chunk and combine results
            all_segments = []
            detected_language = None
            chunk_duration_seconds = 300  # Must match segment_duration above

            total_chunks = len(audio_chunks)
            for i, chunk_path in enumerate(audio_chunks):
                progress = 35 + int((i / total_chunks) * 15)  # 35-50% progress
                JobQueueService.update_progress(
                    job_id, progress, "transcribing",
                    f"Transcribing chunk {i+1}/{total_chunks}..."
                )

                print(f"[Worker] Transcribing chunk {i+1}/{total_chunks}: {chunk_path}")

                # Run in executor to avoid blocking event loop (critical for auth responsiveness)
                segments, info = await _run_in_executor(
                    whisper_model.transcribe,
                    chunk_path,
                    **transcribe_params
                )

                chunk_segments = list(segments)

                # Use language from first chunk
                if detected_language is None:
                    detected_language = info.language
                    print(f"[Worker] Whisper detected language: {detected_language}")

                # Adjust segment times based on chunk offset
                chunk_offset = i * chunk_duration_seconds
                for seg in chunk_segments:
                    # Adjust segment times to be relative to the full video
                    seg.start += chunk_offset
                    seg.end += chunk_offset

                all_segments.extend(chunk_segments)

            JobQueueService.update_progress(job_id, 50, "transcribing", "Processing transcription segments...")

            # Validate and potentially override detected language
            if language and not force_language:
                if detected_language != language:
                    print(f"[Worker] Language mismatch! Specified: {language}, Detected: {detected_language}")
                    detected_language = language
            elif force_language and language:
                print(f"[Worker] Force override - using: {language}")
                detected_language = language

            # Format segments
            import uuid
            formatted_segments = []
            for seg in all_segments:
                formatted_segments.append({
                    "id": str(uuid.uuid4()),
                    "start": seg.start,
                    "end": seg.end,
                    "start_time": format_timestamp(seg.start),
                    "end_time": format_timestamp(seg.end),
                    "text": seg.text,
                    "translation": None,
                })

            print(f"[Worker] Combined {len(formatted_segments)} segments from {total_chunks} chunks")

            # === MEMORY CLEANUP: Unload Whisper before diarization ===
            print("[Worker] Cleaning up GPU memory before diarization...")
            log_gpu_memory("Worker:BeforeWhisperUnload")
            unload_whisper_model()
            clear_gpu_memory("Worker:AfterWhisperUnload")

            # Step 4: Speaker diarization (50-80%)
            JobQueueService.update_progress(job_id, 55, "diarizing", "Starting speaker diarization...")

            if settings.ENABLE_SPEAKER_DIARIZATION:
                try:
                    # Calculate total video duration to decide on chunked vs. standard diarization
                    total_duration = len(audio_chunks) * 300  # 5 minutes per chunk

                    # Use chunked diarization for long videos (configurable threshold)
                    if total_duration > settings.USE_CHUNKED_DIARIZATION_ABOVE:
                        print(f"[Worker] Using chunked diarization for {total_duration}s ({total_duration/60:.1f} min) video")
                        JobQueueService.update_progress(job_id, 60, "diarizing", "Using chunked diarization for long video...")

                        # Initialize chunked diarizer
                        chunked_diarizer = ChunkedSpeakerDiarizer(
                            chunk_duration=settings.DIARIZATION_CHUNK_DURATION,
                            similarity_threshold=settings.DIARIZATION_SIMILARITY_THRESHOLD,
                            use_auth_token=settings.HUGGINGFACE_TOKEN
                        )

                        # Run chunked diarization in executor to avoid blocking event loop
                        speaker_segments = await _run_in_executor(
                            chunked_diarizer.diarize_chunked,
                            audio_chunks=audio_chunks,
                            chunk_duration=300,  # 5-min chunks
                            num_speakers=num_speakers,
                            min_speakers=min_speakers,
                            max_speakers=max_speakers
                        )

                        # Apply speaker labels to transcription segments
                        formatted_segments = assign_speakers_to_segments(formatted_segments, speaker_segments)

                        # Clean up chunked diarizer to free GPU memory
                        chunked_diarizer.unload_pipeline()
                        del chunked_diarizer
                        clear_gpu_memory("Worker:AfterChunkedDiarization")

                        JobQueueService.update_progress(job_id, 75, "diarizing", "Chunked diarization completed")

                    else:
                        # Standard full-video diarization for shorter videos
                        print(f"[Worker] Using standard full-video diarization for {total_duration}s ({total_duration/60:.1f} min) video")

                        diarizer = get_speaker_diarizer()

                        if diarizer and len(audio_chunks) > 0:
                            # Concatenate all audio chunks for full-video diarization
                            print(f"[Worker] Performing speaker diarization on full video...")

                            if len(audio_chunks) == 1:
                                # Single chunk - use directly
                                diarization_audio_path = audio_chunks[0]
                                print("[Worker] Using single audio chunk for diarization")
                            else:
                                # Multiple chunks - concatenate them with ffmpeg
                                concat_audio_path = os.path.join(temp_dir, "concat_for_diarization.wav")
                                concat_list_path = os.path.join(temp_dir, "concat_list.txt")

                                with open(concat_list_path, 'w') as f:
                                    for chunk in audio_chunks:
                                        f.write(f"file '{chunk}'\n")

                                concat_cmd = [
                                    'ffmpeg', '-f', 'concat', '-safe', '0',
                                    '-i', concat_list_path,
                                    '-c', 'copy', concat_audio_path, '-y'
                                ]
                                subprocess.run(concat_cmd, check=True, capture_output=True)
                                diarization_audio_path = concat_audio_path
                                temp_files.append(concat_audio_path)
                                print(f"[Worker] Concatenated {len(audio_chunks)} chunks for full-video diarization")

                            # Run in executor to avoid blocking event loop
                            formatted_segments = await _run_in_executor(
                                SpeakerService.add_speaker_labels,
                                audio_path=diarization_audio_path,
                                segments=formatted_segments,
                                diarizer=diarizer,
                                num_speakers=num_speakers,
                                min_speakers=min_speakers,
                                max_speakers=max_speakers
                            )

                            # Clean up standard diarizer
                            clear_gpu_memory("Worker:AfterStandardDiarization")

                            JobQueueService.update_progress(job_id, 75, "diarizing", "Speaker diarization completed")
                        else:
                            print("[Worker] Speaker diarization not available, skipping")
                            # Add default speaker labels
                            for seg in formatted_segments:
                                seg['speaker'] = "SPEAKER_00"
                            JobQueueService.update_progress(job_id, 75, "diarizing", "Skipped (not available)")

                except Exception as e:
                    print(f"[Worker] Speaker diarization failed: {e}")
                    traceback.print_exc()
                    # Add default speaker labels
                    for seg in formatted_segments:
                        seg['speaker'] = "SPEAKER_00"
                    JobQueueService.update_progress(job_id, 75, "diarizing", "Skipped (error)")
            else:
                print("[Worker] Speaker diarization disabled")
                for seg in formatted_segments:
                    seg['speaker'] = "SPEAKER_00"
                JobQueueService.update_progress(job_id, 75, "diarizing", "Skipped (disabled)")

            # Calculate video hash early (used for screenshots and final result)
            import hashlib
            video_hash = hashlib.md5(gcs_path.encode()).hexdigest()

            # Step 4.5: Screenshot extraction (75-80%)
            # Check if file is a video format that supports screenshots
            suffix = os.path.splitext(filename)[1].lower()
            if suffix in {'.mp4', '.mpeg', '.webm', '.mov', '.mkv'}:
                try:
                    JobQueueService.update_progress(job_id, 76, "extracting", "Extracting screenshots...")

                    screenshots_dir = os.path.join("static", "screenshots")
                    os.makedirs(screenshots_dir, exist_ok=True)

                    # Get timestamps for all segments
                    timestamps = [seg['start'] for seg in formatted_segments]

                    print(f"[Worker] Extracting {len(timestamps)} screenshots from video...")
                    log_all_memory("Worker:BeforeScreenshotExtraction")

                    # Extract screenshots from GCS URL (streaming, no full download)
                    # Run in executor to avoid blocking event loop
                    screenshot_results = await _run_in_executor(
                        VideoService.extract_screenshots_parallel_from_url,
                        source_url=read_url,
                        timestamps=timestamps,
                        output_dir=screenshots_dir,
                        video_hash=video_hash,
                        max_workers=4
                    )

                    log_all_memory("Worker:AfterScreenshotExtraction")
                    JobQueueService.update_progress(job_id, 78, "extracting", "Uploading screenshots to cloud...")

                    # Upload to GCS and update segments
                    if settings.ENABLE_GCS_UPLOADS:
                        print(f"[Worker] Uploading {len(screenshot_results)} screenshots to GCS...")
                        log_all_memory("Worker:BeforeGCSUpload")

                        gcs_urls = gcs_service.upload_screenshots_batch(
                            screenshot_paths=screenshot_results,
                            video_hash=video_hash
                        )

                        screenshot_count = 0
                        for seg in formatted_segments:
                            ts = seg['start']
                            gcs_url = gcs_urls.get(ts)
                            if gcs_url:
                                seg['screenshot_url'] = gcs_url
                                screenshot_count += 1
                            else:
                                seg['screenshot_url'] = None

                        print(f"[Worker] Uploaded {screenshot_count}/{len(formatted_segments)} screenshots to GCS")
                        log_all_memory("Worker:AfterGCSUpload")

                        # Clean up local screenshots after upload
                        for local_path in screenshot_results.values():
                            if local_path and os.path.exists(local_path):
                                try:
                                    os.unlink(local_path)
                                except Exception:
                                    pass
                    else:
                        # Use local URLs (development mode)
                        screenshot_count = 0
                        for seg in formatted_segments:
                            ts = seg['start']
                            screenshot_path = screenshot_results.get(ts)
                            if screenshot_path and os.path.exists(screenshot_path):
                                screenshot_filename = os.path.basename(screenshot_path)
                                seg['screenshot_url'] = f"/static/screenshots/{screenshot_filename}"
                                screenshot_count += 1
                            else:
                                seg['screenshot_url'] = None

                        print(f"[Worker] Extracted {screenshot_count}/{len(formatted_segments)} screenshots (local)")

                    JobQueueService.update_progress(job_id, 79, "extracting", f"Extracted {screenshot_count} screenshots")

                    # Step 4.6: Create silent segments for timeline gaps (visual moments without speech)
                    JobQueueService.update_progress(job_id, 79, "extracting", "Detecting silent visual moments...")
                    print(f"[Worker] Detecting timeline gaps and creating silent segments...")
                    log_all_memory("Worker:BeforeSilentSegments")

                    # Run in executor to avoid blocking event loop
                    formatted_segments = await _run_in_executor(
                        create_silent_segments_for_gaps,
                        segments=formatted_segments,
                        video_path=None,
                        video_hash=video_hash,
                        min_gap_duration=2.0,
                        silent_chunk_duration=10.0,
                        source_url=read_url  # Use GCS URL for streaming screenshot extraction
                    )

                    log_all_memory("Worker:AfterSilentSegments")

                    # Upload silent segment screenshots to GCS
                    silent_segments = [s for s in formatted_segments if s.get('is_silent')]
                    if silent_segments and settings.ENABLE_GCS_UPLOADS:
                        print(f"[Worker] Uploading {len(silent_segments)} silent segment screenshots to GCS...")
                        silent_screenshot_count = 0

                        for seg in silent_segments:
                            screenshot_url = seg.get('screenshot_url', '')
                            # Check if it's a local path that needs GCS upload
                            if screenshot_url and screenshot_url.startswith('/static/screenshots/'):
                                local_filename = screenshot_url.replace('/static/screenshots/', '')
                                local_path = os.path.join('static', 'screenshots', local_filename)

                                if os.path.exists(local_path):
                                    try:
                                        gcs_url = gcs_service.upload_screenshot(
                                            local_path=local_path,
                                            video_hash=video_hash,
                                            timestamp=seg['start']
                                        )
                                        seg['screenshot_url'] = gcs_url
                                        silent_screenshot_count += 1

                                        # Clean up local file after upload
                                        os.unlink(local_path)
                                    except Exception as e:
                                        print(f"[Worker] Failed to upload silent screenshot at {seg['start']:.2f}s: {e}")

                        print(f"[Worker] Uploaded {silent_screenshot_count}/{len(silent_segments)} silent screenshots to GCS")
                        log_all_memory("Worker:AfterSilentGCSUpload")
                        screenshot_count += silent_screenshot_count

                    # Auto-index images into Supabase pgvector if GCS uploads are enabled
                    if settings.ENABLE_GCS_UPLOADS and screenshot_count > 0:
                        try:
                            from services.image_embedding_service import image_embedding_service
                            JobQueueService.update_progress(job_id, 80, "indexing", "Indexing images for visual search...")
                            print(f"[Worker] Auto-indexing {screenshot_count} images for visual search...")
                            log_all_memory("Worker:BeforeImageIndexing")
                            indexed_count = image_embedding_service.index_video_images(video_hash, formatted_segments, force_reindex=False, user_id=user_id)
                            log_all_memory("Worker:AfterImageIndexing")
                            print(f"[Worker] Successfully indexed {indexed_count} images for visual search")
                        except Exception as e:
                            print(f"[Worker] Image indexing failed (non-critical): {e}")
                            # Non-critical - visual search just won't work until manually indexed

                except Exception as e:
                    print(f"[Worker] Screenshot extraction failed (non-critical): {e}")
                    # Non-critical error - continue without screenshots
                    for seg in formatted_segments:
                        seg['screenshot_url'] = None
            else:
                print(f"[Worker] Skipping screenshots for audio-only file: {suffix}")
                for seg in formatted_segments:
                    seg['screenshot_url'] = None

            JobQueueService.update_progress(job_id, 80, "processing", "Finalizing transcription...")

            # Step 5: Generate SRT/VTT formats (80-95%)
            JobQueueService.update_progress(job_id, 85, "processing", "Generating subtitle formats...")

            # For non-English, add translation field
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

            # Translate non-English content to English
            if normalized_lang in ['en', 'english']:
                # For English, translation equals original text
                for segment in formatted_segments:
                    segment['translation'] = segment['text']
            else:
                # Translate to English using MarianMT with progress updates
                JobQueueService.update_progress(job_id, 87, "translating", "Translating to English...")
                try:
                    total_segments = len(formatted_segments)
                    print(f"[Worker] Translating {total_segments} segments from {normalized_lang} to English")

                    # Progress callback to update job progress during translation (87% -> 92%)
                    def translation_progress(translated: int, total: int):
                        # Map translation progress to job progress (87% to 92%)
                        progress = 87 + int((translated / total) * 5) if total > 0 else 87
                        percent = int((translated / total) * 100) if total > 0 else 0
                        JobQueueService.update_progress(
                            job_id,
                            progress,
                            "translating",
                            f"Translating to English... {translated}/{total} ({percent}%)"
                        )

                    # Run in executor to avoid blocking event loop
                    formatted_segments = await _run_in_executor(
                        TranslationService.translate_segments,
                        formatted_segments,
                        normalized_lang,
                        progress_callback=translation_progress
                    )
                    print(f"[Worker] Translation completed")
                except Exception as e:
                    print(f"[Worker] Translation failed: {e}")
                    # If translation fails, set placeholder translations
                    for segment in formatted_segments:
                        segment['translation'] = None

            # Generate SRT and VTT
            srt_content = SubtitleService.generate_srt(formatted_segments, use_translation=False)
            vtt_content = self._generate_vtt(formatted_segments, use_translation=False)

            JobQueueService.update_progress(job_id, 90, "processing", "Generating subtitle formats...")

            # Step 6: Finalize results (90-95%)
            # Note: video_hash was already calculated earlier for screenshot naming
            JobQueueService.update_progress(job_id, 95, "processing", "Finalizing results...")

            # Build result JSON
            result_json = {
                "filename": filename,
                "gcs_path": gcs_path,
                "file_size_bytes": file_size_bytes,
                "video_hash": video_hash,
                "video_url": f"/video/{video_hash}",
                "transcription": {
                    "language": detected_language,
                    "segments": formatted_segments,
                },
            }

            # Step 7: Mark completed (95-100%)
            JobQueueService.mark_completed(
                job_id=job_id,
                video_hash=video_hash,
                result_json=result_json,
                result_srt=srt_content,
                result_vtt=vtt_content
            )

            print(f"[Worker] Job {job_id} completed successfully")
            return True

        except Exception as e:
            # Extract user-friendly error message
            error_message = str(e)
            error_code = "processing_error"

            # Categorize common errors
            if "not found" in error_message.lower():
                error_code = "file_not_found"
            elif "audio" in error_message.lower():
                error_code = "audio_extraction_error"
            elif "transcrib" in error_message.lower():
                error_code = "transcription_error"
            elif "diariz" in error_message.lower():
                error_code = "diarization_error"
            elif "storage" in error_message.lower() or "gcs" in error_message.lower():
                error_code = "storage_error"

            print(f"[Worker] Job {job_id} failed: {error_message}")
            traceback.print_exc()

            # Mark as failed
            JobQueueService.mark_failed(job_id, error_message, error_code)
            return False

        finally:
            # Cancel heartbeat task
            if heartbeat_task and not heartbeat_task.done():
                heartbeat_task.cancel()
                try:
                    await heartbeat_task
                except asyncio.CancelledError:
                    pass

            if job_id in self._heartbeat_tasks:
                del self._heartbeat_tasks[job_id]

            # Cleanup temp files
            for temp_file in temp_files:
                try:
                    if os.path.exists(temp_file):
                        os.unlink(temp_file)
                        print(f"[Worker] Cleaned up temp file: {temp_file}")
                except Exception as e:
                    print(f"[Worker] Failed to cleanup temp file {temp_file}: {e}")

            # Cleanup temp directories
            for temp_dir in temp_dirs:
                try:
                    if os.path.exists(temp_dir):
                        shutil.rmtree(temp_dir)
                        print(f"[Worker] Cleaned up temp directory: {temp_dir}")
                except Exception as e:
                    print(f"[Worker] Failed to cleanup temp directory {temp_dir}: {e}")

    async def _heartbeat_loop(self, job_id: str):
        """
        Update heartbeat every 30 seconds to indicate the job is still processing.

        Args:
            job_id: Job ID
        """
        try:
            while True:
                await asyncio.sleep(HEARTBEAT_INTERVAL)
                success = JobQueueService.update_heartbeat(job_id)
                if success:
                    print(f"[Worker] Heartbeat sent for job {job_id}")
                else:
                    print(f"[Worker] Failed to send heartbeat for job {job_id}")
        except asyncio.CancelledError:
            print(f"[Worker] Heartbeat loop cancelled for job {job_id}")
            raise

    def _generate_vtt(self, segments: list, use_translation: bool = False) -> str:
        """
        Generate VTT format subtitles from segments.

        Args:
            segments: List of segment dictionaries
            use_translation: Whether to use translation instead of original text

        Returns:
            VTT format string
        """
        vtt_content = ["WEBVTT", ""]

        for i, segment in enumerate(segments, 1):
            try:
                # Convert timestamps to VTT format (HH:MM:SS.mmm)
                start_seconds = float(segment.get('start', 0.0))
                end_seconds = float(segment.get('end', 0.0))

                # Get text content
                text_content = None
                if use_translation:
                    text_content = segment.get('translation')
                    if not text_content or text_content.isspace():
                        text_content = '[Translation Missing]'
                else:
                    text_content = segment.get('text')
                    if not text_content or text_content.isspace():
                        text_content = '[No Text Available]'

                # Format subtitle entry
                vtt_content.extend([
                    f"{format_timestamp(start_seconds)} --> {format_timestamp(end_seconds)}",
                    text_content.strip(),
                    ""  # Empty line between entries
                ])
            except Exception as e:
                print(f"Error processing segment {i} for VTT: {str(e)}")
                vtt_content.extend([
                    "00:00:00.000 --> 00:00:00.001",
                    f"[Error: Failed to process segment {i}]",
                    ""
                ])

        return "\n".join(vtt_content)


# Singleton instance
background_worker = BackgroundWorker()
