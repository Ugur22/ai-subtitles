"""
Video processing and screenshot extraction services
"""
import os
import subprocess
import traceback


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
