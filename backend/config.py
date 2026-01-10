"""
Configuration management using Pydantic Settings
"""
import os
import json
from typing import Optional, List
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
    @property
    def CORS_ORIGINS(self) -> List[str]:
        """
        Load CORS origins from environment variable.
        Expects a JSON array string, e.g., CORS_ORIGINS='["https://myapp.vercel.app","https://app.example.com"]'
        Defaults to localhost for development if not set.
        """
        cors_env = os.getenv("CORS_ORIGINS")
        if cors_env:
            try:
                origins = json.loads(cors_env)
                if isinstance(origins, list):
                    return origins
                else:
                    print(f"Warning: CORS_ORIGINS is not a list, using default")
                    return ["http://localhost:5173"]
            except json.JSONDecodeError as e:
                print(f"Warning: Failed to parse CORS_ORIGINS as JSON: {e}, using default")
                return ["http://localhost:5173"]
        return ["http://localhost:5173"]

    # File Upload Configuration
    MAX_UPLOAD_SIZE: int = 10 * 1024 * 1024 * 1024  # 10GB

    # Directory Configuration - Support Railway persistent volumes via env vars
    # Railway mounts volumes to /data, local dev uses relative paths
    VIDEOS_DIR: str = os.getenv("VIDEOS_DIR", os.path.join("static", "videos"))
    SCREENSHOTS_DIR: str = os.getenv("SCREENSHOTS_DIR", os.path.join("static", "screenshots"))
    STATIC_DIR: str = os.getenv("STATIC_DIR", "static")

    # Database Configuration - Support Railway persistent volumes
    DATABASE_PATH: str = os.getenv("DATABASE_PATH", "transcriptions.db")
    DATABASE_TYPE: str = os.getenv("DATABASE_TYPE", "sqlite")  # "sqlite" or "firestore"
    FIRESTORE_COLLECTION: str = os.getenv("FIRESTORE_COLLECTION", "transcriptions")

    # Whisper Model Configuration
    FASTWHISPER_MODEL: str = os.getenv("FASTWHISPER_MODEL", "small")
    FASTWHISPER_DEVICE: str = os.getenv("FASTWHISPER_DEVICE", "cpu")
    FASTWHISPER_COMPUTE_TYPE: str = os.getenv("FASTWHISPER_COMPUTE_TYPE", "int8")

    # Speaker Diarization Configuration
    ENABLE_SPEAKER_DIARIZATION: bool = os.getenv("ENABLE_SPEAKER_DIARIZATION", "true").lower() == "true"
    HUGGINGFACE_TOKEN: Optional[str] = os.getenv("HUGGINGFACE_TOKEN")
    MIN_SPEAKERS: int = int(os.getenv("MIN_SPEAKERS", "1"))
    MAX_SPEAKERS: int = int(os.getenv("MAX_SPEAKERS", "0"))  # 0 = unlimited/auto-detect

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

    # Audio Analysis Configuration
    ENABLE_AUDIO_ANALYSIS: bool = os.getenv("ENABLE_AUDIO_ANALYSIS", "true").lower() == "true"
    PANNS_MODEL: str = os.getenv("PANNS_MODEL", "Cnn14_mAP=0.431")
    AUDIO_EVENT_THRESHOLD: float = float(os.getenv("AUDIO_EVENT_THRESHOLD", "0.3"))
    ENABLE_SPEECH_EMOTION: bool = os.getenv("ENABLE_SPEECH_EMOTION", "true").lower() == "true"
    SER_MODEL: str = os.getenv("SER_MODEL", "ehcalabres/wav2vec2-lg-xlsr-en-speech-emotion-recognition")

    # VAD (Voice Activity Detection) Configuration
    VAD_ENABLED: bool = os.getenv("VAD_ENABLED", "true").lower() == "true"
    VAD_THRESHOLD: float = float(os.getenv("VAD_THRESHOLD", "0.2"))  # Lower = more permissive (default was 0.5, too aggressive)
    VAD_MIN_SILENCE_DURATION_MS: int = int(os.getenv("VAD_MIN_SILENCE_DURATION_MS", "500"))

    # GCS Upload Configuration
    ENABLE_GCS_UPLOADS: bool = os.getenv("ENABLE_GCS_UPLOADS", "false").lower() == "true"
    GCS_BUCKET_NAME: str = os.getenv("GCS_BUCKET_NAME", "ai-subs-uploads")
    GCS_UPLOAD_PREFIX: str = os.getenv("GCS_UPLOAD_PREFIX", "uploads/")
    GCS_PROCESSED_PREFIX: str = os.getenv("GCS_PROCESSED_PREFIX", "processed/")
    GCS_SCREENSHOTS_PREFIX: str = os.getenv("GCS_SCREENSHOTS_PREFIX", "screenshots/")
    GCS_SIGNED_URL_EXPIRY: int = int(os.getenv("GCS_SIGNED_URL_EXPIRY", "3600"))  # 1 hour for uploads
    GCS_DOWNLOAD_URL_EXPIRY: int = int(os.getenv("GCS_DOWNLOAD_URL_EXPIRY", "86400"))  # 24 hours for playback
    GCS_SCREENSHOT_URL_EXPIRY: int = int(os.getenv("GCS_SCREENSHOT_URL_EXPIRY", "604800"))  # 7 days for screenshots

    # Supabase Configuration
    SUPABASE_URL: str = os.getenv("SUPABASE_URL", "")
    SUPABASE_SERVICE_KEY: str = os.getenv("SUPABASE_SERVICE_KEY", "")

    # App Password Protection
    # Generate hash with: python -c "import hashlib; print(hashlib.sha256('your_password'.encode()).hexdigest())"
    # Leave empty to disable password protection
    APP_PASSWORD_HASH: Optional[str] = os.getenv("APP_PASSWORD_HASH")

    class Config:
        case_sensitive = True
        env_file = ".env"
        extra = "ignore"  # Allow extra environment variables


# Create singleton instance
settings = Settings()
