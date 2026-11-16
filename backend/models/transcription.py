"""
Transcription-related Pydantic models
"""
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field
from models.audio_events import AudioEvent, SpeechEmotion, AudioAnalysis


class TranscriptionSegment(BaseModel):
    """Individual transcription segment"""
    id: str = Field(..., description="Unique segment identifier")
    start: float = Field(..., description="Start time in seconds")
    end: float = Field(..., description="End time in seconds")
    start_time: str = Field(..., description="Formatted start time (HH:MM:SS.mmm)")
    end_time: str = Field(..., description="Formatted end time (HH:MM:SS.mmm)")
    text: str = Field(..., description="Transcribed text in original language")
    translation: Optional[str] = Field(None, description="English translation (if applicable)")
    speaker: Optional[str] = Field(None, description="Speaker label (e.g., SPEAKER_00)")
    screenshot_url: Optional[str] = Field(None, description="URL to segment screenshot")
    translation_error: Optional[str] = Field(None, description="Translation error message if any")
    is_silent: bool = Field(False, description="Whether this segment is a silent period")
    audio_events: Optional[List[AudioEvent]] = Field(None, description="Detected audio events in this segment")
    speech_emotion: Optional[SpeechEmotion] = Field(None, description="Detected emotion in speech")
    audio_analysis: Optional[AudioAnalysis] = Field(None, description="Complete audio analysis for this segment")

    model_config = {
        "json_schema_extra": {
            "example": {
                "id": "550e8400-e29b-41d4-a716-446655440000",
                "start": 0.0,
                "end": 5.5,
                "start_time": "00:00:00.000",
                "end_time": "00:00:05.500",
                "text": "Hello, world!",
                "translation": "Hello, world!",
                "speaker": "SPEAKER_00",
                "screenshot_url": "/static/screenshots/abc123_0.00.jpg"
            }
        }
    }


class TranscriptionData(BaseModel):
    """Transcription data container"""
    text: str = Field(..., description="Full transcription text")
    language: str = Field(..., description="Detected language code")
    duration: str = Field(..., description="Video duration")
    segments: List[TranscriptionSegment] = Field(..., description="List of transcription segments")
    processing_time: str = Field(..., description="Time taken to process")

    model_config = {
        "json_schema_extra": {
            "example": {
                "text": "Hello, world! This is a test.",
                "language": "en",
                "duration": "0:00:10",
                "segments": [],
                "processing_time": "5s"
            }
        }
    }


class TranslationStats(BaseModel):
    """Translation statistics"""
    total_segments: int = Field(..., description="Total number of segments")
    segments_translated: int = Field(..., description="Number of successfully translated segments")
    translation_errors: int = Field(..., description="Number of translation errors")
    detected_language: str = Field(..., description="Language detected by Whisper")
    normalized_language: str = Field(..., description="Normalized language code")
    translation_attempted: bool = Field(..., description="Whether translation was attempted")


class TranscriptionResponse(BaseModel):
    """Complete transcription response"""
    filename: str = Field(..., description="Original filename")
    video_hash: str = Field(..., description="Unique hash of the video file")
    transcription: TranscriptionData = Field(..., description="Transcription data")
    translation_stats: Optional[TranslationStats] = Field(None, description="Translation statistics")
    video_url: Optional[str] = Field(None, description="URL to access the video")
    file_path: Optional[str] = Field(None, description="Server file path")

    model_config = {
        "json_schema_extra": {
            "example": {
                "filename": "sample.mp4",
                "video_hash": "abc123def456",
                "transcription": {
                    "text": "Hello, world!",
                    "language": "en",
                    "duration": "0:00:10",
                    "segments": [],
                    "processing_time": "5s"
                },
                "video_url": "/video/abc123def456"
            }
        }
    }


class TranscriptionListItem(BaseModel):
    """Transcription list item with metadata"""
    video_hash: str = Field(..., description="Unique hash of the video file")
    filename: str = Field(..., description="Original filename")
    created_at: str = Field(..., description="Creation timestamp")
    file_path: Optional[str] = Field(None, description="Server file path")
    thumbnail_url: Optional[str] = Field(None, description="Thumbnail URL")


class TranscriptionListResponse(BaseModel):
    """List of all transcriptions"""
    transcriptions: List[TranscriptionListItem] = Field(..., description="List of transcriptions")

    model_config = {
        "json_schema_extra": {
            "example": {
                "transcriptions": [
                    {
                        "video_hash": "abc123",
                        "filename": "sample.mp4",
                        "created_at": "2024-01-15 10:30:00",
                        "file_path": "/static/videos/abc123.mp4",
                        "thumbnail_url": "/static/screenshots/abc123_5.00.jpg"
                    }
                ]
            }
        }
    }


class UpdateSpeakerRequest(BaseModel):
    """Request to update speaker name"""
    segment_id: str = Field(..., description="Segment ID to update")
    speaker_name: str = Field(..., description="New speaker name")

    model_config = {
        "json_schema_extra": {
            "example": {
                "segment_id": "550e8400-e29b-41d4-a716-446655440000",
                "speaker_name": "John Doe"
            }
        }
    }


class TranslationRequest(BaseModel):
    """Request to translate text"""
    text: str = Field(..., description="Text to translate")
    source_lang: str = Field(..., description="Source language code (e.g., 'es', 'it')")

    model_config = {
        "json_schema_extra": {
            "example": {
                "text": "Hola mundo",
                "source_lang": "es"
            }
        }
    }


class TranslationResponse(BaseModel):
    """Translation response"""
    translation: str = Field(..., description="Translated text")

    model_config = {
        "json_schema_extra": {
            "example": {
                "translation": "Hello world"
            }
        }
    }


class SummaryRequest(BaseModel):
    """Request to generate summary"""
    video_hash: str = Field(..., description="Video hash to summarize")
    max_length: Optional[int] = Field(150, description="Maximum summary length")
    min_length: Optional[int] = Field(50, description="Minimum summary length")


class SummaryResponse(BaseModel):
    """Summary generation response"""
    summary: str = Field(..., description="Generated summary")
    video_hash: str = Field(..., description="Video hash")

    model_config = {
        "json_schema_extra": {
            "example": {
                "summary": "This video discusses artificial intelligence and its applications.",
                "video_hash": "abc123"
            }
        }
    }
