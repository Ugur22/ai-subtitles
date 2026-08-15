"""
Configuration management using Pydantic Settings
"""
import os
import json
from typing import Optional, List
from pydantic_settings import BaseSettings, SettingsConfigDict
from dotenv import load_dotenv

# Load environment variables
load_dotenv()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        case_sensitive=True,
        env_file=".env",
        extra="ignore",
    )
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

    # Runtime mode is explicit: production uses GCS + Cloud Run Jobs, while
    # local development uses filesystem media + detached worker processes.
    LOCAL_MODE: bool = os.getenv("LOCAL_MODE", "false").lower() == "true"
    LOCAL_STORAGE_ROOT: str = os.getenv(
        "LOCAL_STORAGE_ROOT", os.path.join(os.path.dirname(__file__), "local_data", "media")
    )
    LOCAL_API_BASE_URL: str = os.getenv("LOCAL_API_BASE_URL", "http://localhost:8000")

    # Directory Configuration - Support Railway persistent volumes via env vars
    # Railway mounts volumes to /data, local dev uses relative paths
    VIDEOS_DIR: str = os.getenv("VIDEOS_DIR", os.path.join("static", "videos"))
    SCREENSHOTS_DIR: str = os.getenv("SCREENSHOTS_DIR", os.path.join("static", "screenshots"))
    STATIC_DIR: str = os.getenv("STATIC_DIR", "static")

    # Whisper Model Configuration
    FASTWHISPER_MODEL: str = os.getenv("FASTWHISPER_MODEL", "small")
    FASTWHISPER_DEVICE: str = os.getenv("FASTWHISPER_DEVICE", "cpu")
    FASTWHISPER_COMPUTE_TYPE: str = os.getenv("FASTWHISPER_COMPUTE_TYPE", "int8")

    # Speaker Diarization Configuration
    ENABLE_SPEAKER_DIARIZATION: bool = os.getenv("ENABLE_SPEAKER_DIARIZATION", "true").lower() == "true"
    HUGGINGFACE_TOKEN: Optional[str] = os.getenv("HUGGINGFACE_TOKEN")
    MIN_SPEAKERS: int = int(os.getenv("MIN_SPEAKERS", "1"))
    MAX_SPEAKERS: int = int(os.getenv("MAX_SPEAKERS", "0"))  # 0 = unlimited/auto-detect

    # Chunked Diarization Configuration
    # For long videos, process diarization in chunks to reduce memory usage
    DIARIZATION_CHUNK_DURATION: int = int(os.getenv("DIARIZATION_CHUNK_DURATION", "900"))  # 15 minutes in seconds
    DIARIZATION_SIMILARITY_THRESHOLD: float = float(os.getenv("DIARIZATION_SIMILARITY_THRESHOLD", "0.7"))  # Speaker embedding similarity threshold
    USE_CHUNKED_DIARIZATION_ABOVE: int = int(os.getenv("USE_CHUNKED_DIARIZATION_ABOVE", "1800"))  # 30 minutes - use chunked processing for videos longer than this

    # Memory Management Configuration
    EMBEDDING_SEGMENTS_PER_SPEAKER: int = int(os.getenv("EMBEDDING_SEGMENTS_PER_SPEAKER", "5"))
    ENABLE_MEMORY_LOGGING: bool = os.getenv("ENABLE_MEMORY_LOGGING", "true").lower() == "true"

    # LLM Configuration
    DEFAULT_LLM_PROVIDER: str = os.getenv("DEFAULT_LLM_PROVIDER", "grok")
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
    DEEPSEEK_API_KEY: Optional[str] = os.getenv("DEEPSEEK_API_KEY")
    DEEPSEEK_MODEL: str = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-pro")
    DEEPSEEK_BASE_URL: str = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")

    # CLIP Visual Search Configuration
    ENABLE_VISUAL_SEARCH: bool = os.getenv("ENABLE_VISUAL_SEARCH", "true").lower() == "true"
    CLIP_MODEL: str = os.getenv("CLIP_MODEL", "clip-ViT-B-32")

    # Vision Caption Index Configuration
    # Captions are generated with the xAI vision API at index time and searched
    # via all-MiniLM text embeddings; CLIP alone cannot recognize many actions.
    ENABLE_VISION_CAPTIONS: bool = os.getenv("ENABLE_VISION_CAPTIONS", "true").lower() == "true"
    XAI_CAPTION_MODEL: str = os.getenv("XAI_CAPTION_MODEL", "grok-4.3")
    XAI_CAPTION_CONCURRENCY: int = int(os.getenv("XAI_CAPTION_CONCURRENCY", "4"))
    # Dense frames fill the gaps between transcript-anchored screenshots so
    # low-dialogue scenes are searchable. 0 disables dense sampling.
    DENSE_FRAME_INTERVAL_SECONDS: float = float(os.getenv("DENSE_FRAME_INTERVAL_SECONDS", "10"))
    DENSE_FRAME_MIN_GAP_SECONDS: float = float(os.getenv("DENSE_FRAME_MIN_GAP_SECONDS", "2"))
    # MiniLM cosine noise floor below which caption matches are discarded.
    CAPTION_MIN_SIMILARITY: float = float(os.getenv("CAPTION_MIN_SIMILARITY", "0.30"))

    # Face Presence Index Configuration
    # Cosine similarity threshold for matching a detected face against a
    # speaker's reference embedding. 0.5 is a reasonable default for ArcFace.
    FACE_PRESENCE_SIMILARITY_THRESHOLD: float = float(os.getenv("FACE_PRESENCE_SIMILARITY_THRESHOLD", "0.5"))

    # Relaxed cosine threshold used ONLY for the A/B person-comparison candidate
    # pool, so faint faces (low light, profile, distance - e.g. dim/intimate
    # scenes) still surface as selectable "other moments". Lower than the global
    # 0.5 on purpose; auto-pick still favors confident frames via avg_identity.
    FACE_PRESENCE_COMPARISON_THRESHOLD: float = float(os.getenv("FACE_PRESENCE_COMPARISON_THRESHOLD", "0.38"))

    # Verbose per-query debug logging from the chat retrieval pipeline
    # (overlap_score=0 diagnostics, per-result hybrid score dumps). Off in prod.
    CHAT_DEBUG_LOGS: bool = os.getenv("CHAT_DEBUG_LOGS", "false").lower() == "true"

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
    GCS_DOWNLOAD_URL_EXPIRY: int = int(os.getenv("GCS_DOWNLOAD_URL_EXPIRY", "604800"))  # 7 days for playback
    # 30-day target retention is achieved via daily refresh-screenshot-urls cron;
    # the underlying V4 sign call clamps to 7 days per GCS limit.
    GCS_SCREENSHOT_URL_EXPIRY: int = int(os.getenv("GCS_SCREENSHOT_URL_EXPIRY", "2592000"))
    # Background URL refresh job: V4 signed URLs cap at 7 days, so a daily
    # scheduler call re-signs URLs in jobs.result_json and image_embeddings
    # so anything completed within the cutoff window never goes stale at rest.
    URL_REFRESH_CUTOFF_DAYS: int = int(os.getenv("URL_REFRESH_CUTOFF_DAYS", "30"))
    URL_REFRESH_BATCH_SIZE: int = int(os.getenv("URL_REFRESH_BATCH_SIZE", "100"))

    # Local Mode Configuration
    # LOCAL_MODE=true swaps Supabase for a SQLite-backed fake client
    # (services/local_db.py), GCS media storage for LOCAL_STORAGE_ROOT-rooted
    # disk storage (services/local_storage_service.py), Cloud Run Job dispatch
    # for a detached subprocess, and auth for a fixed local admin user.
    # Mutually exclusive with ENABLE_GCS_UPLOADS (enforced in validate_runtime
    # below) — LOCAL_MODE has its own storage path, it doesn't need GCS.
    # LOCAL_DATA_DIR is a separate root from LOCAL_STORAGE_ROOT: it holds app
    # state (local_db.py's SQLite file, the BYOK encryption key, worker logs),
    # not media blobs.
    LOCAL_DATA_DIR: str = os.getenv("LOCAL_DATA_DIR", "./local_data")
    LOCAL_ENCRYPTION_KEY: Optional[str] = os.getenv("LOCAL_ENCRYPTION_KEY")

    # Supabase Configuration
    SUPABASE_URL: str = os.getenv("SUPABASE_URL", "")
    SUPABASE_SERVICE_KEY: str = os.getenv("SUPABASE_SERVICE_KEY", "")

    # App Password Protection
    # Generate hash with: python -c "import hashlib; print(hashlib.sha256('your_password'.encode()).hexdigest())"
    # Leave empty to disable password protection
    APP_PASSWORD_HASH: Optional[str] = os.getenv("APP_PASSWORD_HASH")

    # Internal service-to-service key. Cloud Scheduler (refresh-screenshot-urls,
    # check-stale) sends this in the X-Internal-Key header so it can hit
    # @require_admin endpoints without a Supabase session JWT. Leave empty to
    # disable the bypass.
    INTERNAL_API_KEY: Optional[str] = os.getenv("INTERNAL_API_KEY")

    # Cloud Run Worker Job (background pipeline lives here, not in this Service)
    WORKER_JOB_PROJECT: str = os.getenv("WORKER_JOB_PROJECT", "ai-subs-poc")
    WORKER_JOB_REGION: str = os.getenv("WORKER_JOB_REGION", "us-central1")
    WORKER_JOB_NAME: str = os.getenv("WORKER_JOB_NAME", "ai-subs-worker")

    def validate_runtime(self) -> None:
        """Reject ambiguous or incomplete runtime modes before accepting work."""
        if self.LOCAL_MODE and self.ENABLE_GCS_UPLOADS:
            raise RuntimeError("LOCAL_MODE and ENABLE_GCS_UPLOADS cannot both be enabled")
        if self.LOCAL_MODE:
            # LOCAL_MODE routes metadata through services/local_db.py (a SQLite
            # fake of the Supabase client) instead of a real Supabase project —
            # no cloud project is required to run fully offline.
            if not self.LOCAL_STORAGE_ROOT.strip():
                raise RuntimeError("LOCAL_MODE requires LOCAL_STORAGE_ROOT")
            return
        missing_supabase = [
            name
            for name, value in (
                ("SUPABASE_URL", self.SUPABASE_URL),
                ("SUPABASE_SERVICE_KEY", self.SUPABASE_SERVICE_KEY),
            )
            if not value.strip()
        ]
        if missing_supabase:
            raise RuntimeError(
                f"Runtime requires Supabase metadata configuration: {', '.join(missing_supabase)}"
            )
        missing_production = [
            name
            for name, value in (
                ("ENABLE_GCS_UPLOADS", self.ENABLE_GCS_UPLOADS),
                ("GCS_BUCKET_NAME", self.GCS_BUCKET_NAME),
                ("WORKER_JOB_PROJECT", self.WORKER_JOB_PROJECT),
                ("WORKER_JOB_REGION", self.WORKER_JOB_REGION),
                ("WORKER_JOB_NAME", self.WORKER_JOB_NAME),
            )
            if value is False or (isinstance(value, str) and not value.strip())
        ]
        if missing_production:
            raise RuntimeError(
                f"Production runtime configuration is incomplete: {', '.join(missing_production)}"
            )

# Create singleton instance
settings = Settings()
