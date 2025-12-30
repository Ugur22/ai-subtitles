"""
Video processing and screenshot extraction services
"""
import os
import subprocess
import traceback
import concurrent.futures
from typing import Dict, List, Optional, Tuple


class VideoService:
    """Service for video processing operations"""

    @staticmethod
    def extract_screenshot(input_path: str, timestamp: float, output_path: str) -> bool:
        """Extract a screenshot from a video at a specific timestamp."""
        try:
            print(f"\nExtracting screenshot at timestamp {timestamp}...")
            print(f"Input path: {input_path}")
            print(f"Output path: {output_path}")

            # Check if input file exists
            if not os.path.exists(input_path):
                print(f"ERROR: Input file does not exist: {input_path}")
                return False

            # Use FFmpeg to extract the frame
            cmd = [
                'ffmpeg',
                '-ss', str(timestamp),
                '-i', input_path,
                '-vframes', '1',
                '-q:v', '2',  # High quality
                '-vf', 'scale=1280:-1',  # Scale to a larger width (e.g., 1280px)
                output_path,
                '-y'  # Overwrite if exists
            ]
            print(f"Running FFmpeg command: {' '.join(cmd)}")
            result = subprocess.run(cmd, check=True, capture_output=True, text=True)

            # Verify output file was created
            if os.path.exists(output_path):
                file_size = os.path.getsize(output_path)
                print(f"Screenshot extraction completed successfully (size: {file_size} bytes)")
                return True
            else:
                print(f"ERROR: Screenshot file was not created at {output_path}")
                return False

        except subprocess.CalledProcessError as e:
            print(f"ERROR: FFmpeg failed to extract screenshot at {timestamp}")
            print(f"Return code: {e.returncode}")
            print(f"FFmpeg stderr: {e.stderr}")
            print(f"FFmpeg stdout: {e.stdout}")
            return False
        except Exception as e:
            print(f"ERROR: Failed to extract screenshot at {timestamp}")
            print(f"Error type: {type(e).__name__}")
            print(f"Error details: {str(e)}")
            traceback.print_exc()
            return False

    @staticmethod
    def extract_screenshot_from_url(source_url: str, timestamp: float, output_path: str) -> bool:
        """
        Extract a screenshot from a video URL at a specific timestamp.

        Uses FFmpeg's HTTP streaming with input seeking (-ss before -i) for efficient
        random access without downloading the full video. FFmpeg uses HTTP Range requests
        to only download the keyframes needed for the specific timestamp.

        Args:
            source_url: HTTP(S) URL to the video file (e.g., GCS signed URL)
            timestamp: Time in seconds to extract frame from
            output_path: Path where screenshot will be saved

        Returns:
            True if extraction succeeded, False otherwise
        """
        try:
            # Use FFmpeg with input seeking for efficient HTTP range requests
            # -ss before -i: seeks to position before opening input (uses byte-range requests)
            # This is critical for HTTP efficiency - only downloads needed keyframes
            cmd = [
                'ffmpeg',
                '-ss', str(timestamp),        # Seek BEFORE input (critical for HTTP efficiency)
                '-i', source_url,             # Input from URL
                '-vframes', '1',              # Extract exactly one frame
                '-q:v', '2',                  # High quality JPEG
                '-vf', 'scale=1280:-1',       # Scale width to 1280px
                output_path,
                '-y',                         # Overwrite if exists
                '-loglevel', 'error'          # Reduce log verbosity
            ]

            result = subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=60)

            if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
                return True
            return False

        except subprocess.TimeoutExpired:
            print(f"Timeout extracting screenshot at {timestamp}")
            return False
        except subprocess.CalledProcessError as e:
            print(f"FFmpeg error at {timestamp}: {e.stderr}")
            return False
        except Exception as e:
            print(f"Error extracting screenshot from URL at {timestamp}: {e}")
            return False

    @staticmethod
    def extract_screenshots_parallel_from_url(
        source_url: str,
        timestamps: List[float],
        output_dir: str,
        video_hash: str,
        max_workers: int = 4
    ) -> Dict[float, Optional[str]]:
        """
        Extract multiple screenshots in parallel from a video URL.

        Uses a thread pool to extract screenshots concurrently while limiting
        the number of parallel HTTP connections to avoid overwhelming memory.
        Each FFmpeg process uses HTTP Range requests to only download the
        keyframes needed, keeping memory usage low.

        Args:
            source_url: HTTP(S) URL to the video file (e.g., GCS signed URL)
            timestamps: List of timestamps (in seconds) to extract
            output_dir: Directory where screenshots will be saved
            video_hash: Video identifier for filenames
            max_workers: Maximum parallel FFmpeg processes (default 4)

        Returns:
            Dict mapping timestamp -> screenshot_path (or None if failed)
        """
        os.makedirs(output_dir, exist_ok=True)
        results: Dict[float, Optional[str]] = {}

        def extract_single(ts: float) -> Tuple[float, Optional[str]]:
            output_path = os.path.join(output_dir, f"{video_hash}_{ts:.2f}.jpg")
            success = VideoService.extract_screenshot_from_url(
                source_url, ts, output_path
            )
            return (ts, output_path if success else None)

        # Process in parallel with limited workers
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(extract_single, ts): ts for ts in timestamps}

            for future in concurrent.futures.as_completed(futures):
                try:
                    ts, path = future.result(timeout=120)
                    results[ts] = path
                except Exception as e:
                    ts = futures[future]
                    print(f"Failed to extract screenshot at {ts}: {e}")
                    results[ts] = None

        success_count = sum(1 for v in results.values() if v is not None)
        print(f"[URL Screenshots] Extracted {success_count}/{len(timestamps)} screenshots")

        return results

    @staticmethod
    def convert_mkv_to_mp4(input_path: str, output_path: str) -> bool:
        """
        Convert MKV file to MP4 with browser-compatible codecs (H.264 + AAC)
        Returns True if conversion successful, False otherwise
        """
        try:
            print(f"\nConverting MKV to MP4 for browser compatibility...")
            print(f"Input: {input_path}")
            print(f"Output: {output_path}")

            # Check if input file exists
            if not os.path.exists(input_path):
                print(f"ERROR: Input file does not exist: {input_path}")
                return False

            # FFmpeg command to convert to MP4 with H.264 video and AAC audio
            cmd = [
                'ffmpeg',
                '-i', input_path,
                '-c:v', 'libx264',      # H.264 video codec (widely supported)
                '-preset', 'medium',     # Balance between speed and quality
                '-crf', '23',            # Quality (23 is default, lower = better quality)
                '-c:a', 'aac',           # AAC audio codec (widely supported)
                '-b:a', '128k',          # Audio bitrate
                '-movflags', '+faststart',  # Enable streaming
                output_path,
                '-y'  # Overwrite if exists
            ]

            print(f"Running conversion command...")
            result = subprocess.run(cmd, capture_output=True, text=True)

            if result.returncode != 0:
                print(f"ERROR: FFmpeg conversion failed")
                print(f"Return code: {result.returncode}")
                print(f"Stderr: {result.stderr}")
                return False

            # Verify output file was created
            if os.path.exists(output_path):
                file_size = os.path.getsize(output_path)
                print(f"Conversion completed successfully (size: {file_size / (1024*1024):.2f} MB)")
                return True
            else:
                print(f"ERROR: Output file was not created at {output_path}")
                return False

        except Exception as e:
            print(f"ERROR: Failed to convert MKV to MP4")
            print(f"Error type: {type(e).__name__}")
            print(f"Error details: {str(e)}")
            traceback.print_exc()
            return False
