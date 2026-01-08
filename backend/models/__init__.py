"""
Pydantic models for the API
"""
from models.common import ErrorResponse, SuccessResponse
from models.audio_events import (
    AudioEvent,
    SpeechEmotion,
    AudioAnalysis
)
from models.transcription import (
    TranscriptionSegment,
    TranscriptionData,
    TranslationStats,
    TranscriptionResponse,
    TranscriptionListItem,
    TranscriptionListResponse,
    UpdateSpeakerRequest,
    TranslationRequest,
    TranslationResponse,
    SummaryRequest,
    SummaryResponse
)
from models.speaker import (
    SpeakerInfo,
    EnrollSpeakerResponse,
    ListSpeakersResponse,
    IdentifySpeakerResponse,
    AutoIdentifySpeakersResponse
)
from models.chat import (
    IndexVideoRequest,
    IndexVideoResponse,
    ChatRequest,
    ChatResponse,
    LLMProviderInfo,
    ListLLMProvidersResponse,
    TestLLMRequest,
    TestLLMResponse,
    IndexImagesResponse,
    SearchImagesRequest,
    SearchImagesResponse,
    ImageSearchResult
)
from models.video import (
    CleanupScreenshotsResponse,
    UpdateFilePathResponse,
    DeleteTranscriptionResponse
)

__all__ = [
    # Common
    "ErrorResponse",
    "SuccessResponse",
    # Audio Events
    "AudioEvent",
    "SpeechEmotion",
    "AudioAnalysis",
    # Transcription
    "TranscriptionSegment",
    "TranscriptionData",
    "TranslationStats",
    "TranscriptionResponse",
    "TranscriptionListItem",
    "TranscriptionListResponse",
    "UpdateSpeakerRequest",
    "TranslationRequest",
    "TranslationResponse",
    "SummaryRequest",
    "SummaryResponse",
    # Speaker
    "SpeakerInfo",
    "EnrollSpeakerResponse",
    "ListSpeakersResponse",
    "IdentifySpeakerResponse",
    "AutoIdentifySpeakersResponse",
    # Chat
    "IndexVideoRequest",
    "IndexVideoResponse",
    "ChatRequest",
    "ChatResponse",
    "LLMProviderInfo",
    "ListLLMProvidersResponse",
    "TestLLMRequest",
    "TestLLMResponse",
    "IndexImagesResponse",
    "SearchImagesRequest",
    "SearchImagesResponse",
    "ImageSearchResult",
    # Video
    "CleanupScreenshotsResponse",
    "UpdateFilePathResponse",
    "DeleteTranscriptionResponse",
]
