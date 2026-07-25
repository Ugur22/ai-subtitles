"""
LOCAL_MODE: disk-backed drop-in replacement for GCSService.

Keeps the same object-path vocabulary as production ("uploads/...",
"processed/...", "screenshots/{hash}/{ts}.jpg") so every caller — including the
worker pipeline, which runs with ENABLE_GCS_UPLOADS=true — works unchanged.

Physical layout:
  uploads/*      -> {LOCAL_DATA_DIR}/uploads/*      (served at /local-uploads)
  processed/*    -> {VIDEOS_DIR}/*                  (served at /static/videos)
  screenshots/*  -> {SCREENSHOTS_DIR}/*             (served at /static/screenshots)

"Signed" URLs are plain HTTP URLs on the local server (videos, so the browser
and ffmpeg range-read them) or relative /static/ paths (screenshots, which both
the frontend and image_embedding_service already resolve).
"""
import os
import shutil
import tempfile
import uuid
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional, Tuple

from config import settings

_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _abs(path: str) -> str:
    return path if os.path.isabs(path) else os.path.join(_BACKEND_DIR, path)


class LocalStorageService:
    """Local-disk implementation of the GCSService classmethod surface."""

    @classmethod
    def _uploads_dir(cls) -> str:
        return os.path.join(_abs(settings.LOCAL_DATA_DIR), "uploads")

    @classmethod
    def _local_path(cls, gcs_path: str) -> str:
        """Map a GCS-style object path to its local file path."""
        if gcs_path.startswith(settings.GCS_UPLOAD_PREFIX):
            rest = gcs_path[len(settings.GCS_UPLOAD_PREFIX):]
            return os.path.join(cls._uploads_dir(), rest)
        if gcs_path.startswith(settings.GCS_PROCESSED_PREFIX):
            rest = gcs_path[len(settings.GCS_PROCESSED_PREFIX):]
            return os.path.join(_abs(settings.VIDEOS_DIR), rest)
        if gcs_path.startswith(settings.GCS_SCREENSHOTS_PREFIX):
            rest = gcs_path[len(settings.GCS_SCREENSHOTS_PREFIX):]
            return os.path.join(_abs(settings.SCREENSHOTS_DIR), rest)
        return os.path.join(_abs(settings.LOCAL_DATA_DIR), "storage", gcs_path)

    # ── upload URLs ──────────────────────────────────────────────────────
    @classmethod
    def generate_upload_signed_url(
        cls,
        filename: str,
        content_type: str = "video/mp4",
        expiry_seconds: Optional[int] = None,
    ) -> Tuple[str, str]:
        """Return a local PUT endpoint URL instead of a GCS signed URL.

        The random upload id doubles as the capability token (same semantics as
        an unguessable signed URL).
        """
        safe_filename = filename.replace(" ", "_").replace("/", "_")
        upload_id = str(uuid.uuid4())
        gcs_path = f"{settings.GCS_UPLOAD_PREFIX}{upload_id}_{safe_filename}"
        upload_url = f"{settings.LOCAL_BASE_URL}/api/upload/local/{upload_id}/{safe_filename}"
        print(f"[LocalStorage] Generated local upload URL for: {gcs_path}")
        return upload_url, gcs_path

    @classmethod
    def generate_resumable_upload_url(
        cls,
        filename: str,
        content_type: str = "video/mp4",
        expiry_seconds: Optional[int] = None,
    ) -> Tuple[str, str]:
        # No resumable protocol locally — same PUT URL works for any size
        # (no Cloud Run 32MB limit; the upload router forces method=PUT).
        return cls.generate_upload_signed_url(filename, content_type, expiry_seconds)

    # ── object ops ───────────────────────────────────────────────────────
    @classmethod
    def file_exists(cls, gcs_path: str) -> bool:
        return os.path.exists(cls._local_path(gcs_path))

    @classmethod
    def get_file_size(cls, gcs_path: str) -> int:
        try:
            return os.path.getsize(cls._local_path(gcs_path))
        except OSError:
            return 0

    @classmethod
    def download_to_temp(cls, gcs_path: str, suffix: str = "") -> str:
        """Copy (not move) to a temp file — the worker deletes it when done."""
        source = cls._local_path(gcs_path)
        if not suffix and "." in gcs_path:
            suffix = "." + gcs_path.rsplit(".", 1)[-1]
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            temp_path = tmp.name
        shutil.copyfile(source, temp_path)
        print(f"[LocalStorage] Copied {gcs_path} to {temp_path}")
        return temp_path

    @classmethod
    def move_to_processed(cls, gcs_path: str) -> str:
        filename = gcs_path.rsplit("/", 1)[-1]
        new_path = f"{settings.GCS_PROCESSED_PREFIX}{filename}"
        source = cls._local_path(gcs_path)
        dest = cls._local_path(new_path)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        shutil.move(source, dest)
        print(f"[LocalStorage] Moved {gcs_path} -> {new_path}")
        return new_path

    # ── download URLs ────────────────────────────────────────────────────
    @classmethod
    def generate_download_signed_url(
        cls, gcs_path: str, expiry_seconds: Optional[int] = None
    ) -> str:
        if gcs_path.startswith(settings.GCS_SCREENSHOTS_PREFIX):
            # Relative /static path: the frontend prefixes the API base and the
            # indexing pipeline resolves it straight to disk.
            rest = gcs_path[len(settings.GCS_SCREENSHOTS_PREFIX):]
            return f"/static/screenshots/{rest}"
        if gcs_path.startswith((settings.GCS_UPLOAD_PREFIX, settings.GCS_PROCESSED_PREFIX)):
            # Videos go through /api/local-media, which supports HTTP Range —
            # required by ffmpeg screenshot extraction and browser seeking
            # (the StaticFiles mount ignores Range on this Starlette version).
            return f"{settings.LOCAL_BASE_URL}/api/local-media/{gcs_path}"
        raise ValueError(f"Cannot build local URL for path: {gcs_path}")

    @classmethod
    def generate_download_signed_url_resilient(
        cls,
        gcs_path: str,
        expiry_seconds: Optional[int] = None,
        attempts: int = 3,
        per_attempt_timeout: float = 20.0,
    ) -> str:
        return cls.generate_download_signed_url(gcs_path, expiry_seconds)

    # ── screenshots ──────────────────────────────────────────────────────
    @classmethod
    def upload_screenshot(cls, local_path: str, video_hash: str, timestamp: float) -> str:
        filename = f"{timestamp:.2f}.jpg"
        gcs_path = f"{settings.GCS_SCREENSHOTS_PREFIX}{video_hash}/{filename}"
        dest = cls._local_path(gcs_path)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        if os.path.abspath(local_path) != os.path.abspath(dest):
            shutil.copyfile(local_path, dest)
        return cls.generate_download_signed_url(gcs_path)

    @classmethod
    def upload_screenshots_batch(
        cls,
        screenshot_paths: Dict[float, str],
        video_hash: str,
        max_workers: int = 16,
    ) -> Dict[float, Optional[str]]:
        result: Dict[float, Optional[str]] = {}
        for ts, path in screenshot_paths.items():
            try:
                if not path or not os.path.exists(path):
                    result[ts] = None
                    continue
                result[ts] = cls.upload_screenshot(path, video_hash, ts)
            except Exception as e:
                print(f"[LocalStorage] Failed to store screenshot at {ts}s: {e}")
                result[ts] = None
        stored = sum(1 for v in result.values() if v is not None)
        print(f"[LocalStorage] Stored {stored}/{len(screenshot_paths)} screenshots for {video_hash}")
        return result

    @classmethod
    def upload_local_file(cls, local_path: str, gcs_path: str) -> bool:
        try:
            dest = cls._local_path(gcs_path)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            shutil.copyfile(local_path, dest)
            print(f"[LocalStorage] Copied {local_path} -> {gcs_path}")
            return True
        except Exception as e:
            print(f"[LocalStorage] Failed to copy {local_path} to {gcs_path}: {e}")
            return False

    # ── URL utilities ────────────────────────────────────────────────────
    @classmethod
    def extract_gcs_path_from_signed_url(cls, url: str) -> Optional[str]:
        base = url.split("?")[0]
        idx = base.find("/api/local-media/")
        if idx >= 0:
            return base[idx + len("/api/local-media/"):]
        for marker, prefix in (
            ("/static/videos/", settings.GCS_PROCESSED_PREFIX),
            ("/static/screenshots/", settings.GCS_SCREENSHOTS_PREFIX),
        ):
            idx = base.find(marker)
            if idx >= 0:
                return prefix + base[idx + len(marker):]
        return None

    @classmethod
    def refresh_screenshot_urls_in_segments(cls, segments: list) -> list:
        # Local URLs never expire — nothing to refresh.
        return segments

    # ── deletion / cleanup ───────────────────────────────────────────────
    @classmethod
    def delete_file(cls, gcs_path: str) -> bool:
        try:
            os.unlink(cls._local_path(gcs_path))
            print(f"[LocalStorage] Deleted {gcs_path}")
            return True
        except OSError as e:
            print(f"[LocalStorage] Failed to delete {gcs_path}: {e}")
            return False

    @classmethod
    def delete_folder(cls, prefix: str) -> int:
        root = cls._local_path(prefix if prefix.endswith("/") else prefix + "/")
        root = root.rstrip("/")
        if not os.path.isdir(root):
            print(f"[LocalStorage] No files found with prefix '{prefix}'")
            return 0
        count = sum(len(files) for _, _, files in os.walk(root))
        shutil.rmtree(root, ignore_errors=True)
        print(f"[LocalStorage] Deleted folder '{prefix}': {count} files removed")
        return count

    @classmethod
    def cleanup_old_uploads(cls, max_age_hours: int = 24) -> int:
        uploads = cls._uploads_dir()
        if not os.path.isdir(uploads):
            return 0
        cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
        deleted = 0
        for name in os.listdir(uploads):
            path = os.path.join(uploads, name)
            try:
                mtime = datetime.fromtimestamp(os.path.getmtime(path), tz=timezone.utc)
                if os.path.isfile(path) and mtime < cutoff:
                    os.unlink(path)
                    deleted += 1
            except OSError:
                continue
        if deleted:
            print(f"[LocalStorage] Cleanup: deleted {deleted} old uploads")
        return deleted
