"""
Speaker Diarization Module using pyannote.audio

This module provides speaker diarization functionality to identify
different speakers in audio/video files.
"""

import os
import torch

# Fix for PyTorch 2.6+ which changed weights_only default to True
# This is needed for pyannote models to load properly
# Must be set BEFORE importing pyannote
os.environ.setdefault("TORCH_FORCE_WEIGHTS_ONLY_LOAD", "0")

# Monkey-patch torch.load to use weights_only=False for pyannote compatibility
_original_torch_load = torch.load
def _patched_torch_load(*args, **kwargs):
    if 'weights_only' not in kwargs:
        kwargs['weights_only'] = False
    return _original_torch_load(*args, **kwargs)
torch.load = _patched_torch_load

from pyannote.audio import Pipeline
from typing import List, Dict, Tuple


class SpeakerDiarizer:
    """
    Handle speaker diarization using pyannote.audio
    """

    def __init__(self, use_auth_token: str = None):
        """
        Initialize the speaker diarization pipeline

        Args:
            use_auth_token: Hugging Face authentication token (required for pyannote models)
                          Get it from: https://huggingface.co/settings/tokens
                          Accept pyannote conditions at: https://huggingface.co/pyannote/speaker-diarization
        """
        self.pipeline = None
        self.use_auth_token = use_auth_token

    def load_pipeline(self):
        """Load the diarization pipeline (lazy loading)"""
        if self.pipeline is None:
            print("Loading speaker diarization pipeline...")
            try:
                # Load the latest pyannote speaker diarization model
                self.pipeline = Pipeline.from_pretrained(
                    "pyannote/speaker-diarization-3.1",
                    use_auth_token=self.use_auth_token
                )

                # Use GPU if available
                # Check for CUDA (NVIDIA) first
                if torch.cuda.is_available():
                    device = torch.device("cuda")
                    print("Using CUDA (NVIDIA) for speaker diarization")
                # Check for MPS (Apple Silicon M1/M2/M3)
                elif torch.backends.mps.is_available():
                    device = torch.device("mps")
                    print("Using MPS (Apple Silicon) for speaker diarization")
                else:
                    device = torch.device("cpu")
                    print("Using CPU for speaker diarization")
                    
                self.pipeline.to(device)
                print(f"Speaker diarization pipeline loaded on {device}")
            except Exception as e:
                print(f"Error loading speaker diarization pipeline: {str(e)}")
                print("Make sure you have:")
                print("1. A Hugging Face token: https://huggingface.co/settings/tokens")
                print("2. Accepted pyannote conditions: https://huggingface.co/pyannote/speaker-diarization")
                raise

    def diarize(self, audio_path: str, num_speakers: int = None, min_speakers: int = None, max_speakers: int = None) -> List[Dict]:
        """
        Perform speaker diarization on an audio file

        Args:
            audio_path: Path to the audio file
            num_speakers: Exact number of speakers (optional, if known)
            min_speakers: Minimum number of speakers (optional)
            max_speakers: Maximum number of speakers (optional)

        Returns:
            List of diarization segments with speaker labels and timestamps
            Format: [{"start": 0.5, "end": 3.2, "speaker": "SPEAKER_00"}, ...]
        """
        if self.pipeline is None:
            self.load_pipeline()

        print(f"Performing speaker diarization on: {audio_path}")

        # Prepare diarization parameters
        diarization_params = {}
        if num_speakers is not None:
            diarization_params["num_speakers"] = num_speakers
        else:
            if min_speakers is not None:
                diarization_params["min_speakers"] = min_speakers
            if max_speakers is not None:
                diarization_params["max_speakers"] = max_speakers

        # Run diarization
        try:
            diarization = self.pipeline(audio_path, **diarization_params)
        except Exception as e:
            print(f"Error during diarization: {str(e)}")
            raise

        # Convert diarization result to list of segments
        speaker_segments = []
        for turn, _, speaker in diarization.itertracks(yield_label=True):
            speaker_segments.append({
                "start": turn.start,
                "end": turn.end,
                "speaker": speaker
            })

        print(f"Diarization complete. Found {len(set(seg['speaker'] for seg in speaker_segments))} speakers in {len(speaker_segments)} segments")

        return speaker_segments

    def assign_speakers_to_transcription(
        self,
        transcription_segments: List[Dict],
        speaker_segments: List[Dict]
    ) -> List[Dict]:
        """
        Assign speaker labels to transcription segments based on time overlap

        Args:
            transcription_segments: List of transcription segments with 'start' and 'end' times
            speaker_segments: List of speaker diarization segments with 'start', 'end', and 'speaker'

        Returns:
            Transcription segments with added 'speaker' field
        """
        print(f"Assigning speakers to {len(transcription_segments)} transcription segments...")

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
        print(f"Speaker assignment complete. Identified {len(unique_speakers)} unique speakers")

        return transcription_segments


def format_speaker_label(speaker: str, custom_names: Dict[str, str] = None) -> str:
    """
    Format speaker label for display

    Args:
        speaker: Raw speaker label (e.g., "SPEAKER_00")
        custom_names: Optional dict mapping speaker IDs to custom names (e.g., {"SPEAKER_00": "John"})

    Returns:
        Formatted speaker label
    """
    if custom_names and speaker in custom_names:
        return custom_names[speaker]

    # Convert SPEAKER_00 to Speaker 1, SPEAKER_01 to Speaker 2, etc.
    if speaker.startswith("SPEAKER_"):
        try:
            speaker_num = int(speaker.split("_")[1]) + 1
            return f"Speaker {speaker_num}"
        except (IndexError, ValueError):
            pass

    return speaker
