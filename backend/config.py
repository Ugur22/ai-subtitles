"""
Configuration management using Pydantic Settings
"""
import os
from typing import Optional
from pydantic_settings import BaseSettings
from dotenv import load_dotenv

# Load environment variables
load_dotenv()


class Settings(BaseSettings):
    """Application settings loaded from environment variables"""

    # API Configuration
    API_TITLE: str = "Video Transcription API"
    API_VERSION: str = "1.0.0"
    API_DESCRIPTION: str = "API for video transcription with Whisper, speaker diarization, and LLM features"

    # CORS Configuration
    CORS_ORIGINS: list = ["http://localhost:5173"]

    # File Upload Configuration
    MAX_UPLOAD_SIZE: int = 10 * 1024 * 1024 * 1024  # 10GB

    # Directory Configuration
    VIDEOS_DIR: str = os.path.join("static", "videos")
    SCREENSHOTS_DIR: str = os.path.join("static", "screenshots")
    STATIC_DIR: str = "static"

    # Database Configuration
    DATABASE_PATH: str = "transcriptions.db"

    # Whisper Model Configuration
    FASTWHISPER_MODEL: str = os.getenv("FASTWHISPER_MODEL", "small")
    FASTWHISPER_DEVICE: str = os.getenv("FASTWHISPER_DEVICE", "cpu")
    FASTWHISPER_COMPUTE_TYPE: str = os.getenv("FASTWHISPER_COMPUTE_TYPE", "int8")

    # Speaker Diarization Configuration
    ENABLE_SPEAKER_DIARIZATION: bool = os.getenv("ENABLE_SPEAKER_DIARIZATION", "true").lower() == "true"
    HUGGINGFACE_TOKEN: Optional[str] = os.getenv("HUGGINGFACE_TOKEN")
    MIN_SPEAKERS: int = int(os.getenv("MIN_SPEAKERS", "1"))
    MAX_SPEAKERS: int = int(os.getenv("MAX_SPEAKERS", "5"))

    # LLM Configuration
    DEFAULT_LLM_PROVIDER: str = os.getenv("DEFAULT_LLM_PROVIDER", "ollama")
    OLLAMA_BASE_URL: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    OLLAMA_MODEL: str = os.getenv("OLLAMA_MODEL", "llama3.2:3b")
    GROQ_API_KEY: Optional[str] = os.getenv("GROQ_API_KEY")
    GROQ_MODEL: str = os.getenv("GROQ_MODEL", "llama-3.1-70b-versatile")
    OPENAI_API_KEY: Optional[str] = os.getenv("OPENAI_API_KEY")
    OPENAI_MODEL: str = os.getenv("OPENAI_MODEL", "gpt-4")
    ANTHROPIC_API_KEY: Optional[str] = os.getenv("ANTHROPIC_API_KEY")
    ANTHROPIC_MODEL: str = os.getenv("ANTHROPIC_MODEL", "claude-3-5-sonnet-20241022")
    XAI_API_KEY: Optional[str] = os.getenv("XAI_API_KEY")
    XAI_MODEL: str = os.getenv("XAI_MODEL", "grok-beta")

    # ChromaDB Configuration
    CHROMA_DB_PATH: str = os.getenv("CHROMA_DB_PATH", "./chroma_db")

    # CLIP Visual Search Configuration
    ENABLE_VISUAL_SEARCH: bool = os.getenv("ENABLE_VISUAL_SEARCH", "true").lower() == "true"
    CLIP_MODEL: str = os.getenv("CLIP_MODEL", "clip-ViT-B-32")

    class Config:
        case_sensitive = True
        env_file = ".env"
        extra = "ignore"  # Allow extra environment variables


# Create singleton instance
settings = Settings()
