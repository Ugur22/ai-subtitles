"""Descriptor-safe filesystem media storage for explicit local mode."""

from __future__ import annotations

import errno
import os
import re
import secrets
import shutil
import stat
import tempfile
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from typing import BinaryIO, Dict, Iterator, List, Optional, Tuple
from urllib.parse import quote, unquote, urlparse

from config import settings


class LocalStorageService:
    def __init__(self, root: str) -> None:
        if not root:
            raise ValueError("LOCAL_STORAGE_ROOT is required")
        configured_root = Path(root).expanduser().absolute()
        configured_root.mkdir(parents=True, exist_ok=True)
        if configured_root.is_symlink():
            raise ValueError("LOCAL_STORAGE_ROOT cannot be a symlink")
        self.root = configured_root
        self._directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        self._nofollow = getattr(os, "O_NOFOLLOW", 0)
        if not self._nofollow or os.open not in os.supports_dir_fd:
            raise RuntimeError("Local storage requires descriptor-relative O_NOFOLLOW support")

    @staticmethod
    def _safe_filename(filename: str) -> str:
        safe = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(filename).name).strip("._")
        return safe or "upload.bin"

    @staticmethod
    def _validate_segment(value: str, label: str) -> str:
        if not value or value in {".", ".."} or "/" in value or "\\" in value:
            raise ValueError(f"invalid {label}")
        return value

    def upload_path(self, user_id: str, upload_intent_id: str, filename: str) -> str:
        owner = self._validate_segment(user_id, "user_id")
        intent = self._validate_segment(upload_intent_id, "upload_intent_id")
        return f"uploads/{owner}/{intent}/{self._safe_filename(filename)}"

    def is_user_upload_path(self, object_key: str, user_id: str) -> bool:
        try:
            parts = self._key_parts(object_key)
            return len(parts) >= 4 and parts[0] == "uploads" and parts[1] == user_id
        except ValueError:
            return False

    def is_owned_media_key(self, object_key: str, user_id: str) -> bool:
        try:
            parts = self._key_parts(object_key)
            return (
                len(parts) >= 3
                and parts[0] in {"uploads", "processed", "screenshots"}
                and parts[1] == user_id
            )
        except ValueError:
            return False

    def _key_parts(self, object_key: str) -> Tuple[str, ...]:
        if not object_key or "\x00" in object_key or "\\" in object_key:
            raise ValueError("invalid object key")
        path = PurePosixPath(object_key)
        if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
            raise ValueError("invalid object key")
        return path.parts

    @contextmanager
    def _directory_fd(self, parts: Tuple[str, ...], create: bool = False) -> Iterator[int]:
        current_fd = os.open(self.root, self._directory_flags | self._nofollow)
        try:
            for part in parts:
                try:
                    next_fd = os.open(
                        part,
                        self._directory_flags | self._nofollow,
                        dir_fd=current_fd,
                    )
                except FileNotFoundError:
                    if not create:
                        raise
                    try:
                        os.mkdir(part, mode=0o700, dir_fd=current_fd)
                    except FileExistsError:
                        pass
                    next_fd = os.open(
                        part,
                        self._directory_flags | self._nofollow,
                        dir_fd=current_fd,
                    )
                except OSError as exc:
                    if exc.errno in {errno.ELOOP, errno.ENOTDIR}:
                        raise ValueError("symlink components are forbidden") from exc
                    raise
                os.close(current_fd)
                current_fd = next_fd
            yield current_fd
        finally:
            os.close(current_fd)

    @contextmanager
    def _parent_fd(self, object_key: str, create: bool = False) -> Iterator[Tuple[int, str]]:
        parts = self._key_parts(object_key)
        with self._directory_fd(parts[:-1], create=create) as parent_fd:
            yield parent_fd, parts[-1]

    @staticmethod
    def _reject_symlink(parent_fd: int, name: str) -> None:
        try:
            info = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        except FileNotFoundError:
            return
        if stat.S_ISLNK(info.st_mode):
            raise ValueError("symlink objects are forbidden")

    def create_upload_url(
        self,
        filename: str,
        user_id: str,
        upload_intent_id: str,
        content_type: str,
        resumable: bool = False,
    ) -> Tuple[str, str, str]:
        del content_type, resumable
        object_key = self.upload_path(user_id, upload_intent_id, filename)
        base_url = settings.LOCAL_API_BASE_URL.rstrip("/")
        return f"{base_url}/api/upload/local/{quote(upload_intent_id, safe='')}", object_key, "PUT"

    @contextmanager
    def atomic_writer(self, object_key: str) -> Iterator[BinaryIO]:
        with self._parent_fd(object_key, create=True) as (parent_fd, name):
            temporary_name = f".upload-{secrets.token_hex(16)}"
            fd = os.open(
                temporary_name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | self._nofollow,
                0o600,
                dir_fd=parent_fd,
            )
            published = False
            try:
                with os.fdopen(fd, "wb") as handle:
                    yield handle
                    handle.flush()
                    os.fsync(handle.fileno())
                self._reject_symlink(parent_fd, name)
                os.replace(
                    temporary_name,
                    name,
                    src_dir_fd=parent_fd,
                    dst_dir_fd=parent_fd,
                )
                published = True
            finally:
                if not published:
                    try:
                        os.unlink(temporary_name, dir_fd=parent_fd)
                    except FileNotFoundError:
                        pass

    @contextmanager
    def open_reader(self, object_key: str) -> Iterator[BinaryIO]:
        with self._parent_fd(object_key) as (parent_fd, name):
            try:
                fd = os.open(name, os.O_RDONLY | self._nofollow, dir_fd=parent_fd)
            except OSError as exc:
                if exc.errno == errno.ELOOP:
                    raise ValueError("symlink objects are forbidden") from exc
                raise
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode):
                os.close(fd)
                raise ValueError("object is not a regular file")
            with os.fdopen(fd, "rb") as handle:
                yield handle

    def file_exists(self, object_key: str) -> bool:
        try:
            with self.open_reader(object_key):
                return True
        except FileNotFoundError:
            return False

    def get_file_size(self, object_key: str) -> int:
        with self.open_reader(object_key) as handle:
            return os.fstat(handle.fileno()).st_size

    def download_to_temp(self, object_key: str, suffix: str = "") -> str:
        if not suffix:
            suffix = PurePosixPath(object_key).suffix
        with self.open_reader(object_key) as source:
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as target:
                shutil.copyfileobj(source, target)
                return target.name

    def processed_key(self, object_key: str) -> str:
        parts = self._key_parts(object_key)
        if parts[0] == "processed":
            return object_key
        if len(parts) < 4 or parts[0] != "uploads":
            raise ValueError("only uploaded media can be copied to processed storage")
        return "/".join(("processed", *parts[1:]))

    def copy_to_processed(self, object_key: str) -> str:
        """Atomically copy media while retaining the source for recovery."""
        destination_key = self.processed_key(object_key)
        if destination_key == object_key:
            return destination_key
        try:
            with self.open_reader(object_key) as source:
                with self.atomic_writer(destination_key) as destination:
                    shutil.copyfileobj(source, destination)
        except FileNotFoundError:
            if self.file_exists(destination_key):
                return destination_key
            raise
        return destination_key

    def move_to_processed(self, object_key: str) -> str:
        parts = self._key_parts(object_key)
        if len(parts) < 4 or parts[0] != "uploads":
            raise ValueError("only uploaded media can be moved to processed storage")
        destination_key = "/".join(("processed", *parts[1:]))
        with self._parent_fd(object_key) as (source_fd, source_name):
            opened = os.open(source_name, os.O_RDONLY | self._nofollow, dir_fd=source_fd)
            try:
                if not stat.S_ISREG(os.fstat(opened).st_mode):
                    raise ValueError("source is not a regular file")
            finally:
                os.close(opened)
            with self._parent_fd(destination_key, create=True) as (destination_fd, destination_name):
                self._reject_symlink(destination_fd, destination_name)
                os.replace(
                    source_name,
                    destination_name,
                    src_dir_fd=source_fd,
                    dst_dir_fd=destination_fd,
                )
        return destination_key

    def generate_download_url(
        self, object_key: str, expiry_seconds: Optional[int] = None
    ) -> str:
        del expiry_seconds
        if not self.file_exists(object_key):
            raise FileNotFoundError(object_key)
        base_url = settings.LOCAL_API_BASE_URL.rstrip("/")
        return f"{base_url}/api/upload/object/{quote(object_key, safe='/')}"

    def screenshot_key(self, user_id: str, video_hash: str, timestamp: float) -> str:
        owner = self._validate_segment(user_id, "user_id")
        video = self._validate_segment(video_hash, "video_hash")
        return f"screenshots/{owner}/{video}/{timestamp:.2f}.jpg"

    def parse_screenshot_key(self, reference: str) -> Optional[str]:
        if not reference:
            return None
        parsed = urlparse(reference)
        path = unquote(parsed.path) if parsed.scheme else reference.split("?", 1)[0]
        marker = "/api/upload/object/"
        if path.startswith(marker):
            path = path[len(marker):]
        if not path.startswith("screenshots/"):
            return None
        try:
            self._key_parts(path)
        except ValueError:
            return None
        return path

    def is_owned_screenshot_key(
        self,
        object_key: str,
        user_id: str,
        video_hash: str,
        allow_legacy: bool = False,
    ) -> bool:
        del allow_legacy
        try:
            parts = self._key_parts(object_key)
        except ValueError:
            return False
        return len(parts) == 4 and parts[:3] == ("screenshots", user_id, video_hash)

    def list_screenshot_keys(
        self, user_id: str, video_hash: str, allow_legacy: bool = False
    ) -> List[str]:
        del allow_legacy
        prefix = ("screenshots", user_id, video_hash)
        try:
            with self._directory_fd(prefix) as directory_fd:
                names = os.listdir(directory_fd)
                keys = []
                for name in names:
                    info = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
                    if stat.S_ISREG(info.st_mode):
                        keys.append("/".join((*prefix, name)))
                return keys
        except FileNotFoundError:
            return []

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

    def upload_screenshots_batch(
        self,
        screenshot_paths: Dict[float, str],
        video_hash: str,
        user_id: str,
    ) -> Dict[float, Optional[str]]:
        uploaded: Dict[float, Optional[str]] = {}
        for timestamp, source_name in screenshot_paths.items():
            try:
                object_key = self.screenshot_key(user_id, video_hash, timestamp)
                source_fd = os.open(source_name, os.O_RDONLY | self._nofollow)
                try:
                    if not stat.S_ISREG(os.fstat(source_fd).st_mode):
                        raise ValueError("screenshot source is not a regular file")
                    with os.fdopen(source_fd, "rb") as source, self.atomic_writer(object_key) as target:
                        source_fd = -1
                        shutil.copyfileobj(source, target)
                finally:
                    if source_fd >= 0:
                        os.close(source_fd)
                uploaded[timestamp] = self.generate_download_url(object_key)
            except (OSError, ValueError):
                uploaded[timestamp] = None
        return uploaded

    def delete_file(self, object_key: str) -> bool:
        try:
            with self._parent_fd(object_key) as (parent_fd, name):
                info = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
                if stat.S_ISLNK(info.st_mode):
                    raise ValueError("symlink objects are forbidden")
                if not stat.S_ISREG(info.st_mode):
                    return False
                os.unlink(name, dir_fd=parent_fd)
                return True
        except FileNotFoundError:
            return True
