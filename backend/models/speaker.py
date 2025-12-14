"""
Speaker recognition Pydantic models
"""
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field


class SpeakerInfo(BaseModel):
    """Speaker information"""
    name: str = Field(..., description="Speaker name")
    enrollment_date: Optional[str] = Field(None, description="Date speaker was enrolled")
    sample_count: Optional[int] = Field(None, description="Number of voice samples")

    model_config = {
        "json_schema_extra": {
            "example": {
                "name": "John Doe",
                "enrollment_date": "2024-01-15",
                "sample_count": 3
            }
        }
    }


class EnrollSpeakerResponse(BaseModel):
    """Response after enrolling a speaker"""
    success: bool = Field(..., description="Operation success status")
    message: str = Field(..., description="Success message")
    speaker_info: Optional[SpeakerInfo] = Field(None, description="Enrolled speaker information")

    model_config = {
        "json_schema_extra": {
            "example": {
                "success": True,
                "message": "Successfully enrolled speaker: John Doe",
                "speaker_info": {
                    "name": "John Doe",
                    "enrollment_date": "2024-01-15",
                    "sample_count": 1
                }
            }
        }
    }


class ListSpeakersResponse(BaseModel):
    """Response listing all speakers"""
    speakers: List[SpeakerInfo] = Field(..., description="List of enrolled speakers")
    count: int = Field(..., description="Total number of speakers")

    model_config = {
        "json_schema_extra": {
            "example": {
                "speakers": [
                    {"name": "John Doe", "enrollment_date": "2024-01-15", "sample_count": 3},
                    {"name": "Jane Smith", "enrollment_date": "2024-01-16", "sample_count": 2}
                ],
                "count": 2
            }
        }
    }


class IdentifySpeakerResponse(BaseModel):
    """Response from speaker identification"""
    speaker_name: Optional[str] = Field(None, description="Identified speaker name")
    confidence: float = Field(..., description="Confidence score (0-1)")
    message: str = Field(..., description="Result message")

    model_config = {
        "json_schema_extra": {
            "example": {
                "speaker_name": "John Doe",
                "confidence": 0.85,
                "message": "Identified speaker: John Doe (confidence: 0.85)"
            }
        }
    }


class AutoIdentifySpeakersResponse(BaseModel):
    """Response from auto-identifying all speakers in a video"""
    success: bool = Field(..., description="Operation success status")
    video_hash: str = Field(..., description="Video hash")
    segments_processed: int = Field(..., description="Number of segments processed")
    speakers_identified: int = Field(..., description="Number of speakers identified")
    updated_transcription: Dict[str, Any] = Field(..., description="Updated transcription data")

    model_config = {
        "json_schema_extra": {
            "example": {
                "success": True,
                "video_hash": "abc123",
                "segments_processed": 50,
                "speakers_identified": 3,
                "updated_transcription": {}
            }
        }
    }
