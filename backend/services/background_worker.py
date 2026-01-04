"""
Background worker for processing transcription jobs
"""
import os
import asyncio
import tempfile
import shutil
import traceback
from typing import Optional, Dict

from config import settings
from services.job_queue_service import JobQueueService
from services.gcs_service import gcs_service
from services.audio_service import AudioService
from services.speaker_service import SpeakerService
from services.subtitle_service import SubtitleService
from services.translation_service import TranslationService
from utils.file_utils import generate_file_hash
from utils.time_utils import format_timestamp
from dependencies import get_whisper_model, get_speaker_diarizer


# Configuration
HEARTBEAT_INTERVAL = 30  # seconds


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
                audio_chunks = AudioService.extract_audio_streaming(
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

                segments, info = whisper_model.transcribe(
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

            # Step 4: Speaker diarization (50-80%)
            JobQueueService.update_progress(job_id, 55, "diarizing", "Starting speaker diarization...")

            if settings.ENABLE_SPEAKER_DIARIZATION:
                try:
                    diarizer = get_speaker_diarizer()

                    if diarizer and len(audio_chunks) > 0:
                        # Use first audio chunk for diarization (representative sample)
                        # For better accuracy, you could concatenate chunks or process separately
                        print(f"[Worker] Performing speaker diarization...")

                        formatted_segments = SpeakerService.add_speaker_labels(
                            audio_path=audio_chunks[0],
                            segments=formatted_segments,
                            diarizer=diarizer,
                            num_speakers=num_speakers,
                            min_speakers=min_speakers,
                            max_speakers=max_speakers
                        )

                        JobQueueService.update_progress(job_id, 75, "diarizing", "Speaker diarization completed")
                    else:
                        print("[Worker] Speaker diarization not available, skipping")
                        # Add default speaker labels
                        for seg in formatted_segments:
                            seg['speaker'] = "SPEAKER_00"
                        JobQueueService.update_progress(job_id, 75, "diarizing", "Skipped (not available)")

                except Exception as e:
                    print(f"[Worker] Speaker diarization failed: {e}")
                    # Add default speaker labels
                    for seg in formatted_segments:
                        seg['speaker'] = "SPEAKER_00"
                    JobQueueService.update_progress(job_id, 75, "diarizing", "Skipped (error)")
            else:
                print("[Worker] Speaker diarization disabled")
                for seg in formatted_segments:
                    seg['speaker'] = "SPEAKER_00"
                JobQueueService.update_progress(job_id, 75, "diarizing", "Skipped (disabled)")

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
                # Translate to English using MarianMT
                JobQueueService.update_progress(job_id, 87, "translating", "Translating to English...")
                try:
                    print(f"[Worker] Translating {len(formatted_segments)} segments from {normalized_lang} to English")
                    formatted_segments = TranslationService.translate_segments(formatted_segments, normalized_lang)
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

            # Step 6: Calculate video hash (90-95%)
            JobQueueService.update_progress(job_id, 92, "processing", "Calculating video hash...")

            # For GCS files, we use the GCS path as a stable identifier
            # (since downloading just for hash would be wasteful)
            import hashlib
            video_hash = hashlib.md5(gcs_path.encode()).hexdigest()

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
