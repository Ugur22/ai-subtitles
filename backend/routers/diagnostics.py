"""
Diagnostics router for checking system status and debugging issues.

Provides endpoints to check speaker diarization status, model availability,
and other diagnostic information useful for troubleshooting production issues.
"""
from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional

from config import settings
from dependencies import (
    get_speaker_diarizer,
    SPEAKER_DIARIZATION_AVAILABLE,
    AUDIO_ANALYSIS_AVAILABLE,
    get_audio_analyzer
)


router = APIRouter(prefix="/api/diagnostics", tags=["Diagnostics"])


# =============================================================================
# Pydantic Models
# =============================================================================

class DiarizationStatus(BaseModel):
    """Response model for diarization status check."""
    module_available: bool
    feature_enabled: bool
    token_present: bool
    token_prefix: Optional[str] = None
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
async def check_diarization_status():
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
        module_available=SPEAKER_DIARIZATION_AVAILABLE,
        feature_enabled=settings.ENABLE_SPEAKER_DIARIZATION,
        token_present=bool(settings.HUGGINGFACE_TOKEN),
        token_prefix=settings.HUGGINGFACE_TOKEN[:10] + "..." if settings.HUGGINGFACE_TOKEN else None,
        diarizer_initialized=False,
        error=None
    )

    # Try to initialize diarizer to check for errors
    try:
        diarizer = get_speaker_diarizer()
        result.diarizer_initialized = diarizer is not None
        if not result.diarizer_initialized and result.module_available and result.feature_enabled and result.token_present:
            result.error = "Diarizer returned None despite all prerequisites being met. Check initialization logs."
    except Exception as e:
        result.error = str(e)

    return result


@router.get("/audio-analysis", response_model=AudioAnalysisStatus)
async def check_audio_analysis_status():
    """
    Check audio analysis status (PANNs, emotion detection, etc.).
    """
    result = AudioAnalysisStatus(
        module_available=AUDIO_ANALYSIS_AVAILABLE,
        feature_enabled=settings.ENABLE_AUDIO_ANALYSIS,
        analyzer_initialized=False,
        error=None
    )

    try:
        analyzer = get_audio_analyzer()
        result.analyzer_initialized = analyzer is not None
    except Exception as e:
        result.error = str(e)

    return result


@router.get("/status", response_model=SystemStatus)
async def check_system_status():
    """
    Get overall system diagnostics status.
    """
    diarization = await check_diarization_status()
    audio_analysis = await check_audio_analysis_status()

    return SystemStatus(
        diarization=diarization,
        audio_analysis=audio_analysis
    )
