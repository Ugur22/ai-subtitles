"""
Audio extraction and processing services
"""
import os
import subprocess
import shutil
import math
import tempfile
from typing import List
from moviepy.editor import VideoFileClip
import ffmpeg


class AudioService:
    """Service for audio extraction and processing operations"""

    @staticmethod
    def extract_audio_streaming(source_url: str, output_dir: str, segment_duration: int = 300) -> List[str]:
        """
        Extract audio directly from a URL using FFmpeg streaming without downloading the full video.

        This method uses FFmpeg's native HTTP streaming capabilities to extract audio directly
        from a remote URL (e.g., GCS signed URL) without downloading the entire video file first.
        This significantly reduces memory usage and improves performance for large videos.

        Args:
            source_url: HTTP(S) URL to the video file (e.g., GCS signed URL)
            output_dir: Directory where audio segments will be saved
            segment_duration: Duration of each audio segment in seconds (default: 300 = 5 minutes)

        Returns:
            List of paths to the created audio segment files

        Raises:
            Exception: If FFmpeg is not available or extraction fails

        Notes:
            - Uses -vn flag to skip video decoding (critical for memory savings)
            - Outputs WAV segments with pcm_s16le codec, 16000 Hz, mono
            - Segments are numbered sequentially (e.g., audio_000.wav, audio_001.wav)
        """
        try:
            # Check if ffmpeg is available
            if not shutil.which('ffmpeg'):
                raise Exception("ffmpeg is not installed. Please install ffmpeg first.")

            # Create output directory if it doesn't exist
            os.makedirs(output_dir, exist_ok=True)

            # Generate output file pattern
            output_pattern = os.path.join(output_dir, "audio_%03d.wav")

            print(f"Starting streaming audio extraction from URL...")
            print(f"Source: {source_url[:100]}...")  # Log first 100 chars of URL
            print(f"Output directory: {output_dir}")
            print(f"Segment duration: {segment_duration} seconds")

            # Build FFmpeg command for streaming extraction with segmentation
            # -vn: Skip video decoding (critical for memory savings)
            # -acodec pcm_s16le: 16-bit PCM audio (uncompressed, good for transcription)
            # -ar 16000: 16kHz sample rate (standard for speech recognition)
            # -ac 1: Mono channel (reduces size, sufficient for transcription)
            # -f segment: Enable segmentation
            # -segment_time: Duration of each segment
            # -reset_timestamps 1: Reset timestamps for each segment
            command = [
                'ffmpeg',
                '-i', source_url,           # Input from URL
                '-vn',                       # Skip video decoding
                '-acodec', 'pcm_s16le',     # PCM 16-bit little-endian
                '-ar', '16000',              # 16kHz sample rate
                '-ac', '1',                  # Mono channel
                '-f', 'segment',             # Use segmenter
                '-segment_time', str(segment_duration),  # Segment duration
                '-reset_timestamps', '1',    # Reset timestamps for each segment
                output_pattern,              # Output file pattern
                '-y'                         # Overwrite if exists
            ]

            # Run FFmpeg command
            print(f"Running FFmpeg command: {' '.join(command[:3])}...")  # Log command without full URL
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                check=True
            )

            # Log FFmpeg output for debugging
            if result.stderr:
                print(f"FFmpeg output: {result.stderr[-500:]}")  # Log last 500 chars

            # Find all created audio segments
            audio_chunks = []
            segment_index = 0
            while True:
                segment_path = os.path.join(output_dir, f"audio_{segment_index:03d}.wav")
                if os.path.exists(segment_path):
                    file_size_mb = os.path.getsize(segment_path) / (1024 * 1024)
                    print(f"Created segment {segment_index}: {segment_path} ({file_size_mb:.2f} MB)")
                    audio_chunks.append(segment_path)
                    segment_index += 1
                else:
                    break

            if not audio_chunks:
                raise Exception("No audio segments were created. The video may not contain audio.")

            print(f"Successfully extracted {len(audio_chunks)} audio segments")
            return audio_chunks

        except subprocess.CalledProcessError as e:
            error_msg = e.stderr if e.stderr else str(e)
            print(f"FFmpeg error during streaming extraction: {error_msg}")
            raise Exception(f"Failed to extract audio from URL: {error_msg}")
        except Exception as e:
            print(f"Error in extract_audio_streaming: {str(e)}")
            raise

    @staticmethod
    def extract_audio_with_ffmpeg(video_path: str, chunk_duration: int = 600, overlap: int = 5) -> List[str]:
        """
        Extract audio using ffmpeg directly - more reliable for various codecs
        """
        audio_chunks = []

        try:
            # First, get the duration using ffprobe
            probe_cmd = [
                'ffprobe', '-v', 'error',
                '-show_entries', 'format=duration',
                '-of', 'default=noprint_wrappers=1:nokey=1',
                video_path
            ]
            probe_result = subprocess.run(probe_cmd, capture_output=True, text=True, check=True)
            duration = float(probe_result.stdout.strip())
            print(f"Video duration: {duration:.2f} seconds")

            # If duration is short enough, extract as a single chunk
            if duration <= chunk_duration:
                output_path = video_path + ".wav"
                temp_path = video_path + "_temp.wav"

                # Extract audio
                extract_cmd = [
                    'ffmpeg', '-i', video_path,
                    '-vn',  # No video
                    '-acodec', 'pcm_s16le',  # PCM 16-bit little-endian
                    '-ar', '16000',  # 16kHz sample rate
                    '-ac', '1',  # Mono
                    temp_path,
                    '-y'
                ]
                subprocess.run(extract_cmd, check=True, capture_output=True)

                # Compress the audio
                AudioService.compress_audio(temp_path, output_path, file_size_check=False)
                os.unlink(temp_path)
                audio_chunks.append(output_path)
            else:
                # Extract in chunks with overlap
                num_chunks = math.ceil(duration / chunk_duration)
                for i in range(num_chunks):
                    start_time = max(0, i * chunk_duration - (overlap if i > 0 else 0))
                    end_time = min((i + 1) * chunk_duration + (overlap if i < num_chunks - 1 else 0), duration)

                    chunk_output = f"{video_path}_chunk_{i}.wav"
                    chunk_temp = f"{video_path}_chunk_{i}_temp.wav"

                    # Extract chunk
                    extract_cmd = [
                        'ffmpeg',
                        '-ss', str(start_time),
                        '-t', str(end_time - start_time),
                        '-i', video_path,
                        '-vn',
                        '-acodec', 'pcm_s16le',
                        '-ar', '16000',
                        '-ac', '1',
                        chunk_temp,
                        '-y'
                    ]
                    subprocess.run(extract_cmd, check=True, capture_output=True)

                    # Compress
                    AudioService.compress_audio(chunk_temp, chunk_output, file_size_check=False)
                    os.unlink(chunk_temp)
                    audio_chunks.append(chunk_output)

        except Exception as e:
            print(f"Error in extract_audio_with_ffmpeg: {str(e)}")
            raise

        return audio_chunks

    @staticmethod
    def extract_audio(video_path: str, chunk_duration: int = 600, overlap: int = 5) -> List[str]:
        """
        Extract audio from video and split into chunks if needed, with overlap
        Returns list of paths to compressed audio chunks
        """
        audio_chunks = []

        # Check if this is an MKV file - use ffmpeg directly for better codec support
        file_ext = os.path.splitext(video_path)[1].lower()
        if file_ext == '.mkv':
            print(f"Detected MKV file, using ffmpeg for audio extraction...")
            return AudioService.extract_audio_with_ffmpeg(video_path, chunk_duration, overlap)

        try:
            with VideoFileClip(video_path) as video:
                # Check if video has audio
                if video.audio is None:
                    print(f"WARNING: Video file {video_path} has no audio track!")
                    raise Exception("Video file has no audio track")

                duration = video.duration
                if duration <= chunk_duration:
                    temp_audio_path = video_path + "_temp.wav"
                    compressed_audio_path = video_path + ".wav"
                    video.audio.write_audiofile(temp_audio_path, codec='pcm_s16le')
                    AudioService.compress_audio(temp_audio_path, compressed_audio_path)
                    os.unlink(temp_audio_path)
                    audio_chunks.append(compressed_audio_path)
                else:
                    num_chunks = math.ceil(duration / chunk_duration)
                    for i in range(num_chunks):
                        # Add overlap: previous chunk ends at (i * chunk_duration), next chunk starts overlap seconds before
                        start_time = max(0, i * chunk_duration - (overlap if i > 0 else 0))
                        end_time = min((i + 1) * chunk_duration + (overlap if i < num_chunks - 1 else 0), duration)
                        chunk = video.subclip(start_time, end_time)
                        temp_chunk_path = f"{video_path}_chunk_{i}_temp.wav"
                        compressed_chunk_path = f"{video_path}_chunk_{i}.wav"
                        if chunk.audio is None:
                            print(f"WARNING: Chunk {i} has no audio!")
                            continue
                        chunk.audio.write_audiofile(temp_chunk_path, codec='pcm_s16le')
                        AudioService.compress_audio(temp_chunk_path, compressed_chunk_path)
                        os.unlink(temp_chunk_path)
                        audio_chunks.append(compressed_chunk_path)
        except Exception as e:
            print(f"ERROR in extract_audio: {str(e)}")
            print(f"Falling back to ffmpeg for audio extraction...")
            return AudioService.extract_audio_with_ffmpeg(video_path, chunk_duration, overlap)

        return audio_chunks

    @staticmethod
    def compress_audio(input_path: str, output_path: str, file_size_check: bool = True) -> str:
        """Compress audio file to reduce size while maintaining quality"""
        try:
            # Check if ffmpeg is available
            if not shutil.which('ffmpeg'):
                raise Exception("ffmpeg is not installed. Please install ffmpeg first.")

            # Default compression settings - good quality
            bitrate = '32k'  # Default bitrate
            sample_rate = '16000'  # Default sample rate

            # For larger files, check if we need stronger compression
            if file_size_check:
                file_size = os.path.getsize(input_path)
                # If file is close to or above 25MB (OpenAI's limit)
                if file_size > 20 * 1024 * 1024:  # 20MB threshold
                    bitrate = '24k'  # Lower bitrate

                # If file is still very large
                if file_size > 30 * 1024 * 1024:  # 30MB threshold
                    bitrate = '16k'  # Even lower bitrate

            # Convert to mono, reduce quality, and compress
            command = [
                'ffmpeg', '-i', input_path,
                '-ac', '1',  # Convert to mono
                '-ar', sample_rate,  # Sample rate 16kHz
                '-b:a', bitrate,  # Bitrate (adaptive based on size)
                output_path,
                '-y'  # Overwrite output file if it exists
            ]

            subprocess.run(command, check=True, capture_output=True)

            # If file is still too large for OpenAI (25MB limit), compress more aggressively
            if file_size_check and os.path.getsize(output_path) > 25 * 1024 * 1024:
                print(f"Audio still too large ({os.path.getsize(output_path) / (1024 * 1024):.1f} MB). Applying stronger compression...")
                # Try again with more aggressive settings
                command = [
                    'ffmpeg', '-i', input_path,
                    '-ac', '1',  # Convert to mono
                    '-ar', '12000',  # Lower sample rate
                    '-b:a', '10k',  # Much lower bitrate
                    output_path,
                    '-y'  # Overwrite output file if it exists
                ]
                subprocess.run(command, check=True, capture_output=True)

            return output_path
        except subprocess.CalledProcessError as e:
            raise Exception(f"Error compressing audio: {e.stderr.decode()}")

    @staticmethod
    def get_audio_duration(file_path: str) -> float:
        """Get the duration of an audio/video file using ffmpeg."""
        try:
            probe = ffmpeg.probe(file_path)
            duration = float(probe['format']['duration'])
            return duration
        except Exception as e:
            print(f"Error probing file duration: {e}")
            return 0.0

    @staticmethod
    def process_video_with_ffmpeg(input_path: str, output_path: str) -> None:
        """Process video and extract compressed audio using ffmpeg"""
        try:
            # Check if ffmpeg is available
            if not shutil.which('ffmpeg'):
                raise Exception("ffmpeg is not installed")

            initial_bitrate = '32k'
            initial_sample_rate = '16000'

            # First extract audio with standard compression settings
            command = [
                'ffmpeg',
                '-i', input_path,
                '-vn',  # Skip video
                '-ac', '1',  # Convert to mono
                '-ar', initial_sample_rate,
                '-b:a', initial_bitrate,
                output_path,
                '-y'  # Overwrite output file if it exists
            ]

            subprocess.run(command, check=True, capture_output=True)

            # Check if the resulting file is too large for OpenAI's Whisper API (25MB limit)
            if os.path.exists(output_path):
                output_size_mb = os.path.getsize(output_path) / (1024 * 1024)
                print(f"Audio extracted. Size: {output_size_mb:.1f} MB")

                if output_size_mb > 25:
                    print(f"Audio file too large ({output_size_mb:.1f} MB). Applying stronger compression...")
                    stronger_bitrate = '16k'
                    stronger_sample_rate = '12000'
                    print(f"Applying stronger compression: bitrate={stronger_bitrate}, sample_rate={stronger_sample_rate}")
                    # Try again with more aggressive settings
                    command = [
                        'ffmpeg',
                        '-i', input_path,
                        '-vn',  # Skip video
                        '-ac', '1',  # Convert to mono
                        '-ar', stronger_sample_rate,
                        '-b:a', stronger_bitrate,
                        output_path,
                        '-y'  # Overwrite output file if it exists
                    ]
                    subprocess.run(command, check=True, capture_output=True)
                    output_size_mb = os.path.getsize(output_path) / (1024 * 1024)
                    print(f"Audio size after stronger compression: {output_size_mb:.1f} MB")

                    # If still too large, compress even more aggressively
                    if output_size_mb > 25:
                        print(f"Audio still too large ({output_size_mb:.1f} MB). Applying maximum compression...")
                        max_bitrate = '10k'
                        max_sample_rate = '8000'
                        print(f"Applying maximum compression: bitrate={max_bitrate}, sample_rate={max_sample_rate}")
                        command = [
                            'ffmpeg',
                            '-i', input_path,
                            '-vn',  # Skip video
                            '-ac', '1',  # Convert to mono
                            '-ar', max_sample_rate,
                            '-b:a', max_bitrate,
                            output_path,
                            '-y'  # Overwrite output file if it exists
                        ]
                        subprocess.run(command, check=True, capture_output=True)

                        # Log final size
                        final_size_mb = os.path.getsize(output_path) / (1024 * 1024)
                        print(f"Final audio size after maximum compression: {final_size_mb:.1f} MB")

                        if final_size_mb > 25:
                            print("WARNING: Audio still exceeds OpenAI's 25MB limit after maximum compression. Transcription might fail or be inaccurate.")
            else:
                print("WARNING: Output audio file does not exist after initial extraction attempt.")

        except subprocess.CalledProcessError as e:
            raise Exception(f"Error processing video with ffmpeg: {e.stderr.decode()}")
