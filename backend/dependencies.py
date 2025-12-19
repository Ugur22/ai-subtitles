"""
FastAPI dependency injection for model instances
"""
from typing import Optional
from faster_whisper import WhisperModel

from config import settings

# Import speaker diarization module
try:
    from speaker_diarization import SpeakerDiarizer
    SPEAKER_DIARIZATION_AVAILABLE = True
except ImportError as e:
    print(f"Warning: Speaker diarization not available: {str(e)}")
    SPEAKER_DIARIZATION_AVAILABLE = False

# Import audio analyzer module
try:
    from audio_analyzer import AudioAnalyzer
    AUDIO_ANALYSIS_AVAILABLE = True
except ImportError as e:
    print(f"Warning: Audio analysis not available: {str(e)}")
    AUDIO_ANALYSIS_AVAILABLE = False

# Global model instances (lazy loaded)
_whisper_model: Optional[WhisperModel] = None
_speaker_diarizer: Optional['SpeakerDiarizer'] = None
_audio_analyzer: Optional['AudioAnalyzer'] = None

# Global variable to store the last transcription
_last_transcription_data = None


def get_whisper_model() -> WhisperModel:
    """Get or initialize the faster-whisper model (singleton)"""
    global _whisper_model

    if _whisper_model is None:
        print(f"Initializing Whisper model: {settings.FASTWHISPER_MODEL} on {settings.FASTWHISPER_DEVICE}")
        _whisper_model = WhisperModel(
            settings.FASTWHISPER_MODEL,
            device=settings.FASTWHISPER_DEVICE,
            compute_type=settings.FASTWHISPER_COMPUTE_TYPE
        )
        print("Whisper model initialized successfully")

    return _whisper_model


def get_speaker_diarizer() -> Optional['SpeakerDiarizer']:
    """Get or initialize the speaker diarization pipeline (singleton)"""
    global _speaker_diarizer

    if not SPEAKER_DIARIZATION_AVAILABLE:
        print("Speaker diarization module not available")
        return None

    # Check if feature is enabled
    if not settings.ENABLE_SPEAKER_DIARIZATION:
        print("Speaker diarization is disabled in .env")
        return None

    if _speaker_diarizer is None:
        try:
            if not settings.HUGGINGFACE_TOKEN:
                print("Warning: HUGGINGFACE_TOKEN not found in .env file")
                print("Speaker diarization will be disabled")
                print("Get token from: https://huggingface.co/settings/tokens")
                print("Accept conditions at: https://huggingface.co/pyannote/speaker-diarization")
                return None

            _speaker_diarizer = SpeakerDiarizer(use_auth_token=settings.HUGGINGFACE_TOKEN)
            print("Speaker diarization module initialized successfully")
        except Exception as e:
            print(f"Error initializing speaker diarization: {str(e)}")
            return None

    return _speaker_diarizer


def get_audio_analyzer() -> Optional['AudioAnalyzer']:
    """Get or initialize the audio analyzer (singleton)"""
    global _audio_analyzer

    if not AUDIO_ANALYSIS_AVAILABLE:
        print("Audio analysis module not available")
        return None

    # Check if feature is enabled
    if not settings.ENABLE_AUDIO_ANALYSIS:
        print("Audio analysis is disabled in .env")
        return None

    if _audio_analyzer is None:
        try:
            _audio_analyzer = AudioAnalyzer()
            print("Audio analyzer initialized successfully")
        except Exception as e:
            print(f"Error initializing audio analyzer: {str(e)}")
            return None

    return _audio_analyzer
