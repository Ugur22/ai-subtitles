"""
Speaker diarization service
"""
import os
import subprocess
import tempfile
import traceback
from typing import List, Dict, Optional

from config import settings

try:
    from speaker_diarization import format_speaker_label
    SPEAKER_DIARIZATION_AVAILABLE = True
except ImportError:
    SPEAKER_DIARIZATION_AVAILABLE = False


class SpeakerService:
    """Service for speaker diarization operations"""

    @staticmethod
    def add_speaker_labels(
        audio_path: str,
        segments: List[Dict],
        diarizer,
        num_speakers: Optional[int] = None,
        min_speakers: Optional[int] = None,
        max_speakers: Optional[int] = None
    ) -> List[Dict]:
        """
        Add speaker labels to transcription segments

        Args:
            audio_path: Path to the audio file
            segments: List of transcription segments
            diarizer: Speaker diarizer instance (from dependencies)
            num_speakers: Optional number of speakers (if known)
            min_speakers: Optional minimum number of speakers
            max_speakers: Optional maximum number of speakers

        Returns:
            Segments with speaker labels added
        """
        try:
            if diarizer is None:
                print("Speaker diarization not available, adding default speaker labels...")
                # Add default speaker to all segments
                for seg in segments:
                    seg['speaker'] = "SPEAKER_00"
                return segments

            print(f"\n{'='*60}")
            print("Starting speaker diarization...")
            print(f"{'='*60}")

            # Get min/max speakers from settings or use defaults
            # PRIORITIZE function arguments over settings
            final_min_speakers = min_speakers if min_speakers is not None else settings.MIN_SPEAKERS
            final_max_speakers = max_speakers if max_speakers is not None else settings.MAX_SPEAKERS

            # Prepare audio for diarization
            # Pyannote prefers WAV files and sometimes fails with MP4/other containers
            temp_wav_path = None
            diarization_input_path = audio_path

            try:
                # Check if conversion is needed (if not .wav or if we just want to be safe)
                if not audio_path.lower().endswith('.wav'):
                    print("Converting input to WAV for speaker diarization...")
                    # Create a temporary WAV file
                    fd, temp_wav_path = tempfile.mkstemp(suffix='.wav')
                    os.close(fd)

                    # Convert to mono 16kHz WAV using ffmpeg
                    command = [
                        'ffmpeg', '-i', audio_path,
                        '-vn', '-ac', '1', '-ar', '16000',
                        temp_wav_path, '-y'
                    ]
                    subprocess.run(command, check=True, capture_output=True)
                    diarization_input_path = temp_wav_path
                    print(f"Created temporary WAV file for diarization: {temp_wav_path}")

                # Perform diarization
                speaker_segments = diarizer.diarize(
                    diarization_input_path,
                    num_speakers=num_speakers,
                    min_speakers=final_min_speakers if num_speakers is None else None,
                    max_speakers=final_max_speakers if num_speakers is None else None
                )

                # Assign speakers to transcription segments
                segments_with_speakers = diarizer.assign_speakers_to_transcription(
                    segments,
                    speaker_segments
                )

                # Print statistics
                unique_speakers = set(seg.get('speaker', 'UNKNOWN') for seg in segments_with_speakers)
                speaker_counts = {}
                for seg in segments_with_speakers:
                    spk = seg.get('speaker', 'UNKNOWN')
                    speaker_counts[spk] = speaker_counts.get(spk, 0) + 1

                print(f"\n{'='*60}")
                print(f"Speaker diarization complete!")
                print(f"Found {len(unique_speakers)} unique speakers:")
                for spk in sorted(unique_speakers):
                    if SPEAKER_DIARIZATION_AVAILABLE:
                        formatted_name = format_speaker_label(spk)
                    else:
                        formatted_name = spk
                    print(f"  - {formatted_name}: {speaker_counts.get(spk, 0)} segments")
                print(f"{'='*60}\n")

                return segments_with_speakers

            finally:
                # Clean up temporary WAV file
                if temp_wav_path and os.path.exists(temp_wav_path):
                    try:
                        os.unlink(temp_wav_path)
                        print(f"Cleaned up temporary diarization file: {temp_wav_path}")
                    except Exception as e:
                        print(f"Warning: Failed to delete temp file {temp_wav_path}: {e}")

        except Exception as e:
            error_msg = str(e)
            print(f"\n{'='*60}")
            print(f"SPEAKER DIARIZATION FAILED")
            print(f"{'='*60}")
            print(f"Error: {error_msg}")

            # Log more context about common failure modes
            if "timeout" in error_msg.lower() or "timed out" in error_msg.lower():
                print("CAUSE: Processing timed out - video may be too long for CPU processing")
                print("SOLUTION: Consider enabling GPU or reducing video length")
            elif "memory" in error_msg.lower() or "oom" in error_msg.lower():
                print("CAUSE: Out of memory - video requires more RAM")
                print("SOLUTION: Increase memory allocation or reduce video length")
            elif "cuda" in error_msg.lower() or "gpu" in error_msg.lower():
                print("CAUSE: GPU/CUDA error")
                print("SOLUTION: Check GPU availability or fall back to CPU")
            elif "authentication" in error_msg.lower() or "token" in error_msg.lower():
                print("CAUSE: HuggingFace authentication failed")
                print("SOLUTION: Check HUGGINGFACE_TOKEN is set correctly")

            print("\nFull traceback:")
            traceback.print_exc()
            print(f"{'='*60}\n")

            # If diarization fails, mark all segments as UNKNOWN (not SPEAKER_00)
            # This makes it clear in the UI that diarization failed
            print("Falling back to UNKNOWN speaker labels...")
            for seg in segments:
                seg['speaker'] = "UNKNOWN"
                seg['diarization_failed'] = True  # Flag to indicate diarization failure
            return segments
