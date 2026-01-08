"""
Audio event and emotion detection Pydantic models
"""
from typing import List, Optional, Dict
from pydantic import BaseModel, Field


class AudioEvent(BaseModel):
    """Single detected audio event (laughter, applause, music, etc.)"""
    event_type: str = Field(..., description="Type of audio event (laughter, applause, music, etc.)")
    confidence: float = Field(..., description="Confidence score between 0 and 1", ge=0.0, le=1.0)
    original_label: Optional[str] = Field(None, description="Original AudioSet label if available")
    start_offset: Optional[float] = Field(None, description="Start time offset within segment in seconds", ge=0.0)
    end_offset: Optional[float] = Field(None, description="End time offset within segment in seconds", ge=0.0)

    model_config = {
        "json_schema_extra": {
            "example": {
                "event_type": "laughter",
                "confidence": 0.85,
                "original_label": "Laughter",
                "start_offset": 1.2,
                "end_offset": 3.5
            }
        }
    }


class SpeechEmotion(BaseModel):
    """Detected emotion in speech segment"""
    emotion: str = Field(
        ...,
        description="Primary detected emotion (happy, sad, angry, neutral, fearful, disgust, surprised, calm)"
    )
    confidence: float = Field(..., description="Confidence score between 0 and 1", ge=0.0, le=1.0)
    all_emotions: Optional[Dict[str, float]] = Field(
        None,
        description="Dictionary of all detected emotions with their confidence scores"
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "emotion": "happy",
                "confidence": 0.78,
                "all_emotions": {
                    "happy": 0.78,
                    "neutral": 0.15,
                    "surprised": 0.05,
                    "calm": 0.02
                }
            }
        }
    }


class AudioAnalysis(BaseModel):
    """Complete audio analysis for a transcription segment"""
    has_speech: bool = Field(..., description="Whether speech was detected in this segment")
    speech_ratio: float = Field(
        ...,
        description="Ratio of speech to total audio duration (0-1)",
        ge=0.0,
        le=1.0
    )
    audio_events: List[AudioEvent] = Field(
        default_factory=list,
        description="List of detected audio events (non-speech sounds)"
    )
    speech_emotion: Optional[SpeechEmotion] = Field(
        None,
        description="Detected emotion in speech (if speech present)"
    )
    ambient_description: Optional[str] = Field(
        None,
        description="Description of ambient audio characteristics"
    )
    energy_level: Optional[float] = Field(
        None,
        description="Overall audio energy level (0-1)",
        ge=0.0,
        le=1.0
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "has_speech": True,
                "speech_ratio": 0.85,
                "audio_events": [
                    {
                        "event_type": "background_music",
                        "confidence": 0.65,
                        "original_label": "Music",
                        "start_offset": 0.0,
                        "end_offset": 5.0
                    }
                ],
                "speech_emotion": {
                    "emotion": "happy",
                    "confidence": 0.78,
                    "all_emotions": {
                        "happy": 0.78,
                        "neutral": 0.15,
                        "surprised": 0.05,
                        "calm": 0.02
                    }
                },
                "ambient_description": "Indoor environment with soft background music",
                "energy_level": 0.72
            }
        }
    }
