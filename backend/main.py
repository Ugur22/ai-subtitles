"""
FastAPI Application - Video Transcription API
Refactored with organized structure, Pydantic models, and proper documentation
"""
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from config import settings as app_settings
from routers import video, chat, speaker, transcription, upload, jobs, diagnostics, auth_new, keys, admin, settings, face_tags, chapters, billing, features
from middleware.csrf import CSRFProtectionMiddleware
from middleware.token_refresh import TokenRefreshMiddleware
from utils.structured_log import install_excepthooks, log_exception

# Disable docs in production for security
is_production = app_settings.is_production


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Validate runtime configuration."""
    app_settings.validate_runtime()
    print("Application initialized successfully")

    # Start background model preloading to avoid cold-start 504s
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

    yield


app = FastAPI(
    lifespan=lifespan,
    title=app_settings.API_TITLE,
    version=app_settings.API_VERSION,
    description=app_settings.API_DESCRIPTION,
    # Disable automatic trailing slash redirects to prevent HTTP redirect issues
    # (Cloud Run generates http:// redirect URLs instead of https://)
    redirect_slashes=False,
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


install_excepthooks("api")


# Starlette still re-raises after this, so uvicorn logs it too, but only this
# single-line entry carries the whole trace for Error Reporting. The response
# is Starlette's default 500, unchanged.
@app.exception_handler(Exception)
async def log_unhandled_exception(request: Request, exc: Exception):
    log_exception(exc, f"Unhandled exception on {request.method} {request.url.path}")
    return PlainTextResponse("Internal Server Error", status_code=500)


# CSRF protection. Added before CORS so it sits inside it: CORS answers
# preflight requests first and the rest reach this check.
app.add_middleware(CSRFProtectionMiddleware, allowed_origins=app_settings.CORS_ORIGINS)

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
app.include_router(features.router)  # Feature flags for UI visibility


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
