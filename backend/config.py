"""
Configuration management using Pydantic Settings
"""
import os
import json
from pathlib import Path
from typing import Optional, List
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/.env, resolved from this file rather than the working directory so the
# API and the worker read the same file wherever they are started from.
ENV_FILE = Path(__file__).resolve().parent / ".env"


class Settings(BaseSettings):
    """Application settings: process environment first, then backend/.env, then the defaults below."""

    model_config = SettingsConfigDict(
        case_sensitive=True,
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # API Configuration
    API_TITLE: str = "Video Transcription API"
    API_VERSION: str = "1.0.0"
    API_DESCRIPTION: str = "API for video transcription with Whisper, speaker diarization, and LLM features"

    # CORS Configuration. Raw JSON from the CORS_ORIGINS variable; the property
    # below parses it and falls back to localhost when it is missing or invalid.
    cors_origins_json: Optional[str] = Field(default=None, validation_alias="CORS_ORIGINS")

    @property
    def CORS_ORIGINS(self) -> List[str]:
        """
        Load CORS origins from environment variable.
        Expects a JSON array string, e.g., CORS_ORIGINS='["https://myapp.vercel.app","https://app.example.com"]'
        Defaults to localhost for development if not set.
        """
        cors_env = self.cors_origins_json
        if cors_env:
            try:
                origins = json.loads(cors_env)
                if isinstance(origins, list):
                    return origins
                else:
                    print("Warning: CORS_ORIGINS is not a list, using default")
                    return ["http://localhost:5173"]
            except json.JSONDecodeError as e:
                print(f"Warning: Failed to parse CORS_ORIGINS as JSON: {e}, using default")
                return ["http://localhost:5173"]
        return ["http://localhost:5173"]

    # File Upload Configuration
    MAX_UPLOAD_SIZE: int = 10 * 1024 * 1024 * 1024  # 10GB

    # Runtime mode is explicit: production uses GCS + Cloud Run Jobs, while
    # local development uses filesystem media + detached worker processes.
    LOCAL_MODE: bool = False
    LOCAL_STORAGE_ROOT: str = os.path.join(os.path.dirname(__file__), "local_data", "media")
    LOCAL_API_BASE_URL: str = "http://localhost:8000"

    # "production" disables the interactive API docs (see main.py).
    ENVIRONMENT: str = "development"

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT == "production"

    # Directory Configuration - Support Railway persistent volumes via env vars
    # Railway mounts volumes to /data, local dev uses relative paths
    VIDEOS_DIR: str = os.path.join("static", "videos")
    SCREENSHOTS_DIR: str = os.path.join("static", "screenshots")
    STATIC_DIR: str = "static"

    # Whisper Model Configuration
    FASTWHISPER_MODEL: str = "small"
    FASTWHISPER_DEVICE: str = "cpu"
    FASTWHISPER_COMPUTE_TYPE: str = "int8"

    # Speaker Diarization Configuration
    ENABLE_SPEAKER_DIARIZATION: bool = True
    HUGGINGFACE_TOKEN: Optional[str] = None
    MIN_SPEAKERS: int = 1
    MAX_SPEAKERS: int = 0  # 0 = unlimited/auto-detect

    # Chunked Diarization Configuration
    # For long videos, process diarization in chunks to reduce memory usage
    DIARIZATION_CHUNK_DURATION: int = 900
    DIARIZATION_BATCH_SIZE: int = 32
    DIARIZATION_LINK_MODEL: str = "pyannote/wespeaker-voxceleb-resnet34-LM"
    DIARIZATION_SIMILARITY_THRESHOLD: float = 0.5
    USE_CHUNKED_DIARIZATION_ABOVE: int = 1800  # 30 minutes - use chunked processing for videos longer than this

    # Memory Management Configuration
    EMBEDDING_SEGMENTS_PER_SPEAKER: int = 5
    ENABLE_MEMORY_LOGGING: bool = True

    # LLM Configuration
    DEFAULT_LLM_PROVIDER: str = "grok"
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    OLLAMA_MODEL: str = "llama3.2:3b"
    GROQ_API_KEY: Optional[str] = None
    GROQ_MODEL: str = "llama-3.1-70b-versatile"
    OPENAI_API_KEY: Optional[str] = None
    OPENAI_MODEL: str = "gpt-5.6-terra"
    ANTHROPIC_API_KEY: Optional[str] = None
    ANTHROPIC_MODEL: str = "claude-sonnet-5-5"
    XAI_API_KEY: Optional[str] = None
    XAI_MODEL: str = "grok-beta"
    DEEPSEEK_API_KEY: Optional[str] = None
    DEEPSEEK_MODEL: str = "deepseek-v4-pro"
    DEEPSEEK_BASE_URL: str = "https://api.deepseek.com"

    # CLIP Visual Search Configuration
    ENABLE_VISUAL_SEARCH: bool = True
    CLIP_MODEL: str = "clip-ViT-B-32"

    TEXT_EMBEDDING_MODEL: str = "BAAI/bge-small-en-v1.5"
    ENABLE_VISION_CAPTIONS: bool = True
    XAI_CAPTION_MODEL: str = "grok-4.3"
    XAI_CAPTION_CONCURRENCY: int = 4
    CAPTION_MAX_FRAMES: int = 300
    CAPTION_BACKFILL_MAX_FRAMES: int = 8
    CAPTION_BACKFILL_TIMEOUT_SECONDS: float = 180
    CAPTION_MIN_SIMILARITY: float = 0.30
    DENSE_FRAME_INTERVAL_SECONDS: float = 10
    DENSE_FRAME_MIN_GAP_SECONDS: float = 2
    DENSE_FRAME_MAX_COUNT: int = 360

    # Face Presence Index Configuration
    # Cosine similarity threshold for matching a detected face against a
    # speaker's reference embedding. 0.5 is a reasonable default for ArcFace.
    FACE_PRESENCE_SIMILARITY_THRESHOLD: float = 0.5

    # A mis-tag can skew the person reference enough to make later matches drift.
    FACE_TAG_OUTLIER_MIN_SIMILARITY: float = 0.5

    # Relaxed cosine threshold used ONLY for the A/B person-comparison candidate
    # pool, so faint faces (low light, profile, distance - e.g. dim/intimate
    # scenes) still surface as selectable "other moments". Lower than the global
    # 0.5 on purpose; auto-pick still favors confident frames via avg_identity.
    FACE_PRESENCE_COMPARISON_THRESHOLD: float = 0.38

    # Verbose per-query debug logging from the chat retrieval pipeline
    # (overlap_score=0 diagnostics, per-result hybrid score dumps). Off in prod.
    CHAT_DEBUG_LOGS: bool = False

    # Audio Analysis Configuration
    ENABLE_AUDIO_ANALYSIS: bool = True
    PANNS_MODEL: str = "Cnn14_mAP=0.431"
    AUDIO_EVENT_THRESHOLD: float = 0.3

    # VAD (Voice Activity Detection) Configuration
    VAD_ENABLED: bool = True
    VAD_THRESHOLD: float = 0.2  # Lower = more permissive (default was 0.5, too aggressive)
    VAD_MIN_SILENCE_DURATION_MS: int = 500

    # GCS Upload Configuration
    ENABLE_GCS_UPLOADS: bool = False
    GCS_BUCKET_NAME: str = "ai-subs-uploads"
    GCS_UPLOAD_PREFIX: str = "uploads/"
    GCS_PROCESSED_PREFIX: str = "processed/"
    GCS_SCREENSHOTS_PREFIX: str = "screenshots/"
    GCS_SIGNED_URL_EXPIRY: int = 3600  # 1 hour for uploads
    GCS_DOWNLOAD_URL_EXPIRY: int = 604800  # 7 days for playback
    # 30-day target retention is achieved via daily refresh-screenshot-urls cron;
    # the underlying V4 sign call clamps to 7 days per GCS limit.
    GCS_SCREENSHOT_URL_EXPIRY: int = 2592000
    # Background URL refresh job: V4 signed URLs cap at 7 days, so a daily
    # scheduler call re-signs URLs in jobs.result_json and image_embeddings
    # so anything completed within the cutoff window never goes stale at rest.
    URL_REFRESH_CUTOFF_DAYS: int = 30
    URL_REFRESH_BATCH_SIZE: int = 100

    # Supabase Configuration
    SUPABASE_URL: str = ""
    SUPABASE_SERVICE_KEY: str = ""

    # App Password Protection
    # Generate hash with: python -c "import hashlib; print(hashlib.sha256('your_password'.encode()).hexdigest())"
    # Leave empty to disable password protection
    APP_PASSWORD_HASH: Optional[str] = None

    # Internal service-to-service key. Cloud Scheduler (refresh-screenshot-urls,
    # check-stale) sends this in the X-Internal-Key header so it can hit
    # @require_admin endpoints without a Supabase session JWT. Leave empty to
    # disable the bypass.
    INTERNAL_API_KEY: Optional[str] = None

    # Flagsmith server-side environment key ("ser.…"). Unset = every flag off.
    FLAGSMITH_SERVER_KEY: Optional[str] = None

    # Cloud Run Worker Job (background pipeline lives here, not in this Service)
    WORKER_JOB_PROJECT: str = "ai-subs-poc"
    WORKER_JOB_REGION: str = "us-central1"
    WORKER_JOB_NAME: str = "ai-subs-worker"

    # Long-job continuations. One worker execution works until its time budget is
    # used, checkpoints, and hands the job to a fresh execution.
    # 0 = derive from CLOUD_RUN_TASK_TIMEOUT minus a safety margin (about 50 min).
    WORKER_TIME_BUDGET_SECONDS: int = 0
    CLOUD_RUN_TASK_TIMEOUT: int = 0
    MAX_JOB_CONTINUATIONS: int = 12
    # Rough whole-pipeline processing seconds per second of media on the L4
    # worker. Only used to warn about files that look too long to finish.
    PROCESSING_REALTIME_FACTOR: float = 0.35

    def validate_runtime(self) -> None:
        """Reject ambiguous or incomplete runtime modes before accepting work."""
        if self.LOCAL_MODE and self.ENABLE_GCS_UPLOADS:
            raise RuntimeError("LOCAL_MODE and ENABLE_GCS_UPLOADS cannot both be enabled")
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
        if self.LOCAL_MODE:
            if not self.LOCAL_STORAGE_ROOT.strip():
                raise RuntimeError("LOCAL_MODE requires LOCAL_STORAGE_ROOT")
            return
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
