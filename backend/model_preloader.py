"""
Background model preloader for eliminating cold-start 504 timeouts.

Loads heavy ML models in a daemon thread at startup so they're ready
before the first chat request arrives. Models are loaded in priority order:
1. pyannote/embedding (speaker recognition) — the 30-45s bottleneck
2. CLIP clip-ViT-B-32 (image search)
3. InsightFace buffalo_l (face detection)
"""

import threading
import time

_models_ready = threading.Event()
_preload_status = {
    "started": False,
    "speaker_recognition": "pending",
    "clip": "pending",
    "insightface": "pending",
    "start_time": None,
    "ready_time": None,
}


def _preload_models():
    """Load models in priority order. Runs in a daemon thread."""
    _preload_status["start_time"] = time.time()

    # 1. Speaker recognition (pyannote/embedding) — critical bottleneck
    try:
        print("[Preloader] Loading speaker recognition model...")
        from speaker_recognition import get_speaker_recognition_system
        get_speaker_recognition_system()
        _preload_status["speaker_recognition"] = "loaded"
        print("[Preloader] Speaker recognition model ready")
    except Exception as e:
        _preload_status["speaker_recognition"] = f"failed: {e}"
        print(f"[Preloader] Speaker recognition failed: {e}")

    # Signal ready after the critical model loads
    _preload_status["ready_time"] = time.time()
    _models_ready.set()

    # 2. CLIP model (image search)
    try:
        print("[Preloader] Loading CLIP model...")
        from services.image_embedding_service import ImageEmbeddingService
        svc = ImageEmbeddingService()
        _ = svc.clip_model  # trigger lazy load
        _preload_status["clip"] = "loaded"
        print("[Preloader] CLIP model ready")
    except Exception as e:
        _preload_status["clip"] = f"failed: {e}"
        print(f"[Preloader] CLIP failed: {e}")

    # 3. InsightFace (face detection)
    try:
        print("[Preloader] Loading InsightFace model...")
        from services.face_service import face_service
        _ = face_service.model  # trigger lazy load
        _preload_status["insightface"] = "loaded"
        print("[Preloader] InsightFace model ready")
    except Exception as e:
        _preload_status["insightface"] = f"failed: {e}"
        print(f"[Preloader] InsightFace failed: {e}")

    elapsed = time.time() - _preload_status["start_time"]
    print(f"[Preloader] All models loaded in {elapsed:.1f}s")


def start_preloading():
    """Start background model preloading. Call once at startup."""
    if _preload_status["started"]:
        return
    _preload_status["started"] = True
    thread = threading.Thread(target=_preload_models, name="model-preloader", daemon=True)
    thread.start()
    print("[Preloader] Background model preloading started")


def models_ready() -> bool:
    """Check if critical models are loaded."""
    return _models_ready.is_set()


def wait_for_models(timeout: float = 5.0) -> bool:
    """Wait up to timeout seconds for critical models. Returns True if ready."""
    return _models_ready.wait(timeout=timeout)


def get_preload_status() -> dict:
    """Return current preloading status for diagnostics."""
    status = dict(_preload_status)
    if status["start_time"]:
        status["elapsed"] = round(time.time() - status["start_time"], 1)
    status["ready"] = _models_ready.is_set()
    return status
