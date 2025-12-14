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
    provider: Optional[str] = Field(None, description="LLM provider (ollama, groq, openai, anthropic)")
    n_results: Optional[int] = Field(8, description="Number of context chunks to retrieve")

    model_config = {
        "json_schema_extra": {
            "example": {
                "question": "What happens in this video?",
                "video_hash": "abc123",
                "provider": "ollama",
                "n_results": 8
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
