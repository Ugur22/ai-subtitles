"""Runtime-selected media storage boundary."""

from __future__ import annotations

from typing import BinaryIO, ContextManager, Dict, List, Optional, Protocol, Tuple

from config import settings


class MediaStorage(Protocol):
    def upload_path(self, user_id: str, upload_intent_id: str, filename: str) -> str: ...

    def is_user_upload_path(self, object_key: str, user_id: str) -> bool: ...

    def is_owned_media_key(self, object_key: str, user_id: str) -> bool: ...

    def create_upload_url(
        self,
        filename: str,
        user_id: str,
        upload_intent_id: str,
        content_type: str,
        resumable: bool = False,
    ) -> Tuple[str, str, str]: ...

    def atomic_writer(self, object_key: str) -> ContextManager[BinaryIO]: ...

    def file_exists(self, object_key: str) -> bool: ...

    def get_file_size(self, object_key: str) -> int: ...

    def download_to_temp(self, object_key: str, suffix: str = "") -> str: ...

    def processed_key(self, object_key: str) -> str: ...

    def copy_to_processed(self, object_key: str) -> str: ...

    def move_to_processed(self, object_key: str) -> str: ...

    def generate_download_url(
        self, object_key: str, expiry_seconds: Optional[int] = None
    ) -> str: ...

    def upload_screenshots_batch(
        self,
        screenshot_paths: Dict[float, str],
        video_hash: str,
        user_id: str,
    ) -> Dict[float, Optional[str]]: ...

    def screenshot_key(self, user_id: str, video_hash: str, timestamp: float) -> str: ...

    def parse_screenshot_key(self, reference: str) -> Optional[str]: ...

    def is_owned_screenshot_key(
        self,
        object_key: str,
        user_id: str,
        video_hash: str,
        allow_legacy: bool = False,
    ) -> bool: ...

    def list_screenshot_keys(
        self, user_id: str, video_hash: str, allow_legacy: bool = False
    ) -> List[str]: ...

    def materialize_screenshot(
        self,
        reference: str,
        user_id: str,
        video_hash: str,
        allow_legacy: bool = False,
    ) -> str: ...

    def delete_file(self, object_key: str) -> bool: ...


class GCSMediaStorage:
    """Adapter around the existing GCS implementation."""

    def __init__(self) -> None:
        if not settings.ENABLE_GCS_UPLOADS:
            raise RuntimeError("Production media storage requires ENABLE_GCS_UPLOADS=true")
        if not settings.GCS_BUCKET_NAME.strip():
            raise RuntimeError("Production media storage requires GCS_BUCKET_NAME")

    @staticmethod
    def _service():
        from services.gcs_service import gcs_service

        return gcs_service

    def upload_path(self, user_id: str, upload_intent_id: str, filename: str) -> str:
        return self._service()._upload_path(user_id, upload_intent_id, filename)

    def is_user_upload_path(self, object_key: str, user_id: str) -> bool:
        return self._service().is_user_upload_path(object_key, user_id)

    def is_owned_media_key(self, object_key: str, user_id: str) -> bool:
        prefixes = (
            f"{settings.GCS_UPLOAD_PREFIX}{user_id}/",
            f"{settings.GCS_PROCESSED_PREFIX}{user_id}/",
            f"{settings.GCS_SCREENSHOTS_PREFIX}{user_id}/",
        )
        return any(object_key.startswith(prefix) for prefix in prefixes)

    def create_upload_url(
        self,
        filename: str,
        user_id: str,
        upload_intent_id: str,
        content_type: str,
        resumable: bool = False,
    ) -> Tuple[str, str, str]:
        generator = (
            self._service().generate_resumable_upload_url
            if resumable
            else self._service().generate_upload_signed_url
        )
        url, object_key = generator(
            filename=filename,
            user_id=user_id,
            upload_intent_id=upload_intent_id,
            content_type=content_type,
        )
        return url, object_key, "POST" if resumable else "PUT"

    def atomic_writer(self, object_key: str) -> ContextManager[BinaryIO]:
        raise RuntimeError("GCS uploads must use a signed upload URL")

    def file_exists(self, object_key: str) -> bool:
        return self._service().file_exists(object_key)

    def get_file_size(self, object_key: str) -> int:
        return self._service().get_file_size(object_key)

    def download_to_temp(self, object_key: str, suffix: str = "") -> str:
        return self._service().download_to_temp(object_key, suffix)

    def processed_key(self, object_key: str) -> str:
        return self._service().processed_key(object_key)

    def copy_to_processed(self, object_key: str) -> str:
        return self._service().copy_to_processed(object_key)

    def move_to_processed(self, object_key: str) -> str:
        return self._service().move_to_processed(object_key)

    def generate_download_url(
        self, object_key: str, expiry_seconds: Optional[int] = None
    ) -> str:
        return self._service().generate_download_signed_url(object_key, expiry_seconds)

    def upload_screenshots_batch(
        self,
        screenshot_paths: Dict[float, str],
        video_hash: str,
        user_id: str,
    ) -> Dict[float, Optional[str]]:
        return self._service().upload_screenshots_batch(
            screenshot_paths=screenshot_paths,
            video_hash=f"{user_id}/{video_hash}",
        )

    def screenshot_key(self, user_id: str, video_hash: str, timestamp: float) -> str:
        return f"{settings.GCS_SCREENSHOTS_PREFIX}{user_id}/{video_hash}/{timestamp:.2f}.jpg"

    def parse_screenshot_key(self, reference: str) -> Optional[str]:
        if not reference:
            return None
        if reference.startswith(settings.GCS_SCREENSHOTS_PREFIX):
            return reference.split("?", 1)[0]
        return self._service().extract_gcs_path_from_signed_url(reference)

    def is_owned_screenshot_key(
        self,
        object_key: str,
        user_id: str,
        video_hash: str,
        allow_legacy: bool = False,
    ) -> bool:
        owner_prefix = f"{settings.GCS_SCREENSHOTS_PREFIX}{user_id}/{video_hash}/"
        legacy_prefix = f"{settings.GCS_SCREENSHOTS_PREFIX}{video_hash}/"
        return object_key.startswith(owner_prefix) or (
            allow_legacy and object_key.startswith(legacy_prefix)
        )

    def list_screenshot_keys(
        self, user_id: str, video_hash: str, allow_legacy: bool = False
    ) -> List[str]:
        bucket = self._service()._get_bucket()
        prefixes = [f"{settings.GCS_SCREENSHOTS_PREFIX}{user_id}/{video_hash}/"]
        if allow_legacy:
            prefixes.append(f"{settings.GCS_SCREENSHOTS_PREFIX}{video_hash}/")
        return [blob.name for prefix in prefixes for blob in bucket.list_blobs(prefix=prefix)]

    def materialize_screenshot(
        self,
        reference: str,
        user_id: str,
        video_hash: str,
        allow_legacy: bool = False,
    ) -> str:
        object_key = self.parse_screenshot_key(reference)
        if not object_key or not self.is_owned_screenshot_key(
            object_key, user_id, video_hash, allow_legacy
        ):
            raise ValueError("screenshot reference is not owned by this video")
        return self.download_to_temp(object_key, suffix=".jpg")

    def delete_file(self, object_key: str) -> bool:
        return self._service().delete_file(object_key)


_media_storage: Optional[MediaStorage] = None


def get_media_storage() -> MediaStorage:
    """Select exactly one backend from explicit runtime configuration."""
    global _media_storage
    if _media_storage is None:
        if settings.LOCAL_MODE and settings.ENABLE_GCS_UPLOADS:
            raise RuntimeError("LOCAL_MODE and ENABLE_GCS_UPLOADS cannot both be enabled")
        if settings.LOCAL_MODE:
            from services.local_storage_service import LocalStorageService

            _media_storage = LocalStorageService(settings.LOCAL_STORAGE_ROOT)
        else:
            _media_storage = GCSMediaStorage()
    return _media_storage


def reset_media_storage_for_tests() -> None:
    global _media_storage
    _media_storage = None
