"""
Diagnostics router for checking system status and debugging issues.

Provides endpoints to check speaker diarization status, model availability,
and other diagnostic information useful for troubleshooting production issues.
"""
from fastapi import APIRouter, Request
from pydantic import BaseModel
from typing import Optional

from config import settings
import dependencies
from middleware.auth import require_admin


router = APIRouter(prefix="/api/diagnostics", tags=["Diagnostics"])


# =============================================================================
# Pydantic Models
# =============================================================================

class DiarizationStatus(BaseModel):
    """Response model for diarization status check."""
    module_available: bool
    feature_enabled: bool
    token_present: bool
    diarizer_initialized: bool
    error: Optional[str] = None


class AudioAnalysisStatus(BaseModel):
    """Response model for audio analysis status check."""
    module_available: bool
    feature_enabled: bool
    analyzer_initialized: bool
    error: Optional[str] = None


class SystemStatus(BaseModel):
    """Response model for overall system status."""
    diarization: DiarizationStatus
    audio_analysis: AudioAnalysisStatus


# =============================================================================
# Endpoints
# =============================================================================

@router.get("/diarization", response_model=DiarizationStatus)
@require_admin
async def check_diarization_status(request: Request):
    """
    Check speaker diarization status and identify why it may not be working.

    Returns detailed information about:
    - Module availability (pyannote import status)
    - Feature enabled status (from settings)
    - HuggingFace token presence
    - Diarizer initialization status
    - Any error messages
    """
    result = DiarizationStatus(
        module_available=dependencies.SPEAKER_DIARIZATION_AVAILABLE,
        feature_enabled=settings.ENABLE_SPEAKER_DIARIZATION,
        token_present=bool(settings.HUGGINGFACE_TOKEN),
        diarizer_initialized=dependencies._speaker_diarizer is not None,
        error=None
    )
    return result


@router.get("/audio-analysis", response_model=AudioAnalysisStatus)
@require_admin
async def check_audio_analysis_status(request: Request):
    """
    Check audio analysis status (PANNs, emotion detection, etc.).
    """
    result = AudioAnalysisStatus(
        module_available=dependencies.AUDIO_ANALYSIS_AVAILABLE,
        feature_enabled=settings.ENABLE_AUDIO_ANALYSIS,
        analyzer_initialized=dependencies._audio_analyzer is not None,
        error=None
    )
    return result


@router.get("/status", response_model=SystemStatus)
@require_admin
async def check_system_status(request: Request):
    """
    Get overall system diagnostics status.
    """
    return SystemStatus(
        diarization=DiarizationStatus(
            module_available=dependencies.SPEAKER_DIARIZATION_AVAILABLE,
            feature_enabled=settings.ENABLE_SPEAKER_DIARIZATION,
            token_present=bool(settings.HUGGINGFACE_TOKEN),
            diarizer_initialized=dependencies._speaker_diarizer is not None,
        ),
        audio_analysis=AudioAnalysisStatus(
            module_available=dependencies.AUDIO_ANALYSIS_AVAILABLE,
            feature_enabled=settings.ENABLE_AUDIO_ANALYSIS,
            analyzer_initialized=dependencies._audio_analyzer is not None,
        ),
    )
