"""
Chat and RAG Pydantic models
"""
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field


class IndexVideoRequest(BaseModel):
    """Request to index a video for chat"""
    video_hash: Optional[str] = Field(None, description="Video hash to index (uses last transcription if not provided)")

    model_config = {
        "json_schema_extra": {
            "example": {
                "video_hash": "abc123"
            }
        }
    }


class IndexVideoResponse(BaseModel):
    """Response after indexing a video"""
    success: bool = Field(..., description="Operation success status")
    video_hash: str = Field(..., description="Video hash")
    segments_count: int = Field(..., description="Number of segments in transcription")
    chunks_indexed: int = Field(..., description="Number of chunks indexed")
    message: str = Field(..., description="Success message")

    model_config = {
        "json_schema_extra": {
            "example": {
                "success": True,
                "video_hash": "abc123",
                "segments_count": 50,
                "chunks_indexed": 15,
                "message": "Successfully indexed 15 chunks from 50 segments"
            }
        }
    }


class ChatRequest(BaseModel):
    """Request to chat with a video"""
    question: str = Field(..., description="Question to ask about the video")
    video_hash: Optional[str] = Field(None, description="Video hash (uses last transcription if not provided)")
    provider: Optional[str] = Field(None, description="LLM provider (ollama, groq, openai, anthropic, grok)")
    n_results: Optional[int] = Field(8, description="Number of context chunks to retrieve")
    include_visuals: Optional[bool] = Field(False, description="Include visual analysis from video screenshots (requires vision-capable model)")
    n_images: Optional[int] = Field(3, description="Number of relevant images to include when include_visuals=True")
    custom_instructions: Optional[str] = Field(None, description="Custom instructions for how the AI should respond (e.g., 'respond in Spanish', 'be brief')")

    model_config = {
        "json_schema_extra": {
            "example": {
                "question": "What happens in this video?",
                "video_hash": "abc123",
                "provider": "ollama",
                "n_results": 8,
                "include_visuals": False,
                "n_images": 3,
                "custom_instructions": "Respond in Spanish and be concise"
            }
        }
    }


class ChatResponse(BaseModel):
    """Response from chat with video"""
    answer: str = Field(..., description="LLM's answer to the question")
    sources: Optional[List[Dict[str, Any]]] = Field(None, description="Source segments used for context")
    video_hash: str = Field(..., description="Video hash")
    provider_used: Optional[str] = Field(None, description="LLM provider used")

    model_config = {
        "json_schema_extra": {
            "example": {
                "answer": "The video discusses artificial intelligence and its applications in modern technology.",
                "sources": [
                    {"text": "AI is transforming technology", "timestamp": "00:01:30"}
                ],
                "video_hash": "abc123",
                "provider_used": "ollama"
            }
        }
    }


class LLMProviderInfo(BaseModel):
    """Information about an LLM provider"""
    name: str = Field(..., description="Provider name")
    available: bool = Field(..., description="Whether provider is available")
    model: Optional[str] = Field(None, description="Model name being used")
    error: Optional[str] = Field(None, description="Error message if unavailable")

    model_config = {
        "json_schema_extra": {
            "example": {
                "name": "ollama",
                "available": True,
                "model": "llama2",
                "error": None
            }
        }
    }


class ListLLMProvidersResponse(BaseModel):
    """Response listing all LLM providers"""
    providers: List[LLMProviderInfo] = Field(..., description="List of LLM providers")

    model_config = {
        "json_schema_extra": {
            "example": {
                "providers": [
                    {"name": "ollama", "available": True, "model": "llama2", "error": None},
                    {"name": "groq", "available": False, "model": None, "error": "API key not configured"}
                ]
            }
        }
    }


class TestLLMRequest(BaseModel):
    """Request to test an LLM provider"""
    provider: str = Field(..., description="Provider name to test")
    prompt: Optional[str] = Field("Hello, how are you?", description="Test prompt")

    model_config = {
        "json_schema_extra": {
            "example": {
                "provider": "ollama",
                "prompt": "Hello, how are you?"
            }
        }
    }


class TestLLMResponse(BaseModel):
    """Response from LLM provider test"""
    success: bool = Field(..., description="Whether test was successful")
    provider: str = Field(..., description="Provider name")
    response: Optional[str] = Field(None, description="LLM's response to test prompt")
    error: Optional[str] = Field(None, description="Error message if test failed")

    model_config = {
        "json_schema_extra": {
            "example": {
                "success": True,
                "provider": "ollama",
                "response": "I'm doing well, thank you for asking!",
                "error": None
            }
        }
    }


class IndexImagesResponse(BaseModel):
    """Response after indexing video images"""
    success: bool = Field(..., description="Operation success status")
    video_hash: str = Field(..., description="Video hash")
    images_indexed: int = Field(..., description="Number of images indexed")
    message: str = Field(..., description="Success message")

    model_config = {
        "json_schema_extra": {
            "example": {
                "success": True,
                "video_hash": "abc123",
                "images_indexed": 42,
                "message": "Successfully indexed 42 images"
            }
        }
    }


class SearchImagesRequest(BaseModel):
    """Request to search video images"""
    query: str = Field(..., description="Text query to search for in images (e.g., 'person pointing at screen')")
    video_hash: Optional[str] = Field(None, description="Video hash (uses last transcription if not provided)")
    n_results: Optional[int] = Field(5, description="Number of results to return")

    model_config = {
        "json_schema_extra": {
            "example": {
                "query": "person writing on whiteboard",
                "video_hash": "abc123",
                "n_results": 5
            }
        }
    }


class ImageSearchResult(BaseModel):
    """Single image search result"""
    screenshot_path: str = Field(..., description="Path to the screenshot image")
    segment_id: str = Field(..., description="Segment ID")
    start: float = Field(..., description="Start time in seconds")
    end: float = Field(..., description="End time in seconds")
    speaker: str = Field(..., description="Speaker at this timestamp")
    distance: Optional[float] = Field(None, description="Distance score (lower is better)")

    model_config = {
        "json_schema_extra": {
            "example": {
                "screenshot_path": "/path/to/screenshot_001.jpg",
                "segment_id": "seg_001",
                "start": 5.0,
                "end": 10.0,
                "speaker": "SPEAKER_00",
                "distance": 0.234
            }
        }
    }


class SearchImagesResponse(BaseModel):
    """Response from image search"""
    results: List[ImageSearchResult] = Field(..., description="List of matching images")
    video_hash: str = Field(..., description="Video hash")
    query: str = Field(..., description="Search query used")

    model_config = {
        "json_schema_extra": {
            "example": {
                "results": [
                    {
                        "screenshot_path": "/path/to/screenshot_001.jpg",
                        "segment_id": "seg_001",
                        "start": 5.0,
                        "end": 10.0,
                        "speaker": "SPEAKER_00",
                        "distance": 0.234
                    }
                ],
                "video_hash": "abc123",
                "query": "person writing on whiteboard"
            }
        }
    }
