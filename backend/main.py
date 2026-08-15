"""
FastAPI Application - Video Transcription API
Refactored with organized structure, Pydantic models, and proper documentation
"""
import os
import asyncio
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

from config import settings as app_settings
# Import routers
from routers import video, chat, speaker, transcription, upload, jobs, diagnostics, auth_new, keys, admin, settings, face_tags, chapters, billing

# Import LLM module (optional)
try:
    from llm_providers import llm_manager
    LLM_AVAILABLE = True
except ImportError as e:
    print(f"Warning: LLM features not available: {str(e)}")
    LLM_AVAILABLE = False

# Disable docs in production for security
is_production = os.getenv("ENVIRONMENT", "development") == "production"

# Initialize FastAPI app with proper OpenAPI configuration
app = FastAPI(
    title=app_settings.API_TITLE,
    version=app_settings.API_VERSION,
    description=app_settings.API_DESCRIPTION,
    # Disable automatic trailing slash redirects to prevent HTTP redirect issues
    # (Cloud Run generates http:// redirect URLs instead of https://)
    redirect_slashes=False,
    # Disable Swagger UI and ReDoc in production to prevent unauthorized API access
    docs_url=None if is_production else "/docs",
    redoc_url=None if is_production else "/redoc",
    openapi_url=None if is_production else "/openapi.json",
    openapi_tags=[
        {
            "name": "Transcription",
            "description": "Video transcription with Whisper and speaker diarization"
        },
        {
            "name": "Speaker Recognition",
            "description": "Speaker enrollment and identification using voice biometrics"
        },
        {
            "name": "Chat & RAG",
            "description": "Chat with videos using LLM and RAG (Retrieval-Augmented Generation)"
        },
        {
            "name": "Video & Utilities",
            "description": "Video serving, subtitle generation, and utility functions"
        }
    ]
)


# Startup event
@app.on_event("startup")
async def startup_event():
    """Validate runtime configuration."""
    app_settings.validate_runtime()
    print("Application initialized successfully")

    # Start background model preloading to avoid cold-start 504s.
    # Skipped in LOCAL_MODE: heavy models live in the worker subprocess; keeping
    # them out of the API process saves several GB of RAM. Chat models
    # (MiniLM/CLIP) lazy-load on first use.
    if not app_settings.LOCAL_MODE:
        from model_preloader import start_preloading
        start_preloading()

    if app_settings.LOCAL_MODE:
        from services.job_queue_service import JobQueueService
        from services.media_storage import get_media_storage

        app.state.media_cleanup_task = asyncio.create_task(asyncio.to_thread(
            JobQueueService.drain_media_deletions_best_effort,
            storage=get_media_storage(),
            limit=10,
        ))

    # Clean up old GCS uploads if enabled
    if app_settings.ENABLE_GCS_UPLOADS:
        try:
            from services.gcs_service import gcs_service
            # 720h = 30 days: align the orphan sweep with the 30-day GCS lifecycle so a
            # video stuck in uploads/ (e.g. a failed move_to_processed) is never deleted
            # before the lifecycle window. This sweep runs on every restart, so a shorter
            # TTL here would pre-empt retention during crash-loops.
            deleted = gcs_service.cleanup_old_uploads(max_age_hours=720)
            print(f"- GCS uploads enabled (bucket: {app_settings.GCS_BUCKET_NAME})")
            if deleted > 0:
                print(f"- Cleaned up {deleted} old GCS uploads")
        except Exception as e:
            print(f"- GCS cleanup failed (non-critical): {e}")


# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=app_settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition"],
    max_age=600,
)


# Token refresh middleware - sets refreshed auth cookies on response
# Must be added after CORS middleware so cookies are properly handled
from middleware.token_refresh import TokenRefreshMiddleware
app.add_middleware(TokenRefreshMiddleware)


# Include routers
app.include_router(transcription.router)
app.include_router(speaker.router)
app.include_router(chat.router)
app.include_router(video.router)
app.include_router(upload.router)
app.include_router(jobs.router)
app.include_router(auth_new.router)  # Email/password auth
app.include_router(keys.router)      # API keys management
app.include_router(admin.router)     # Admin panel
app.include_router(settings.router)  # User settings
app.include_router(billing.router)   # Pricing tiers + usage snapshot (Stripe wired in Phase 1.5)
app.include_router(diagnostics.router)
app.include_router(face_tags.router)  # Face tagging for scene search
app.include_router(chapters.router, prefix="/api/chapters", tags=["chapters"])  # Auto chapter markers


# Health check endpoint
@app.get("/", tags=["Health"])
async def root():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "service": app_settings.API_TITLE,
        "version": app_settings.API_VERSION
    }


@app.get("/api/preload-status", tags=["Health"])
async def preload_status():
    """Check model preloading status (diagnostic endpoint)"""
    from model_preloader import get_preload_status
    return get_preload_status()


print("FastAPI application loaded successfully")
print(f"API Title: {app_settings.API_TITLE}")
print(f"API Version: {app_settings.API_VERSION}")
