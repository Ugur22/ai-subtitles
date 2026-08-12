import subprocess
import sys
import os
import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from config import settings
from services.job_dispatcher import (
    CloudRunJobDispatcher,
    LocalDetachedJobDispatcher,
    get_job_dispatcher,
    reset_job_dispatcher_for_tests,
    _schedule_reap,
)
from services.local_storage_service import LocalStorageService
from services.media_storage import (
    GCSMediaStorage,
    get_media_storage,
    reset_media_storage_for_tests,
)


@pytest.fixture(autouse=True)
def reset_runtime_singletons():
    reset_media_storage_for_tests()
    reset_job_dispatcher_for_tests()
    yield
    reset_media_storage_for_tests()
    reset_job_dispatcher_for_tests()


def test_local_storage_is_owner_and_intent_scoped(tmp_path):
    storage = LocalStorageService(str(tmp_path))
    key = storage.upload_path("user-1", "intent-1", "../my video.mp4")

    assert key == "uploads/user-1/intent-1/my_video.mp4"
    assert storage.is_user_upload_path(key, "user-1")
    assert not storage.is_user_upload_path(key, "user-2")

    with storage.atomic_writer(key) as handle:
        handle.write(b"media")

    assert storage.file_exists(key)
    assert storage.get_file_size(key) == 5
    assert storage.generate_download_url(key).endswith(key)
    assert storage.is_owned_media_key(key, "user-1")
    assert not storage.is_owned_media_key(key, "user-2")

    processed = storage.move_to_processed(key)
    assert processed == "processed/user-1/intent-1/my_video.mp4"
    assert storage.file_exists(processed)
    assert not storage.file_exists(key)
    assert storage.is_owned_media_key(processed, "user-1")


def test_local_storage_processed_copy_is_idempotent_and_retains_source(tmp_path):
    storage = LocalStorageService(str(tmp_path / "media"))
    source_key = storage.upload_path("user-a", "intent-a", "video.mp4")
    with storage.atomic_writer(source_key) as handle:
        handle.write(b"video")

    destination = storage.copy_to_processed(source_key)
    assert storage.copy_to_processed(source_key) == destination
    assert storage.file_exists(source_key)
    assert storage.file_exists(destination)
    assert storage.delete_file(source_key) is True
    assert storage.delete_file(source_key) is True
    assert storage.file_exists(destination)


def test_local_screenshot_urls_use_authenticated_object_route(tmp_path):
    storage = LocalStorageService(str(tmp_path))
    source = tmp_path / "frame.jpg"
    source.write_bytes(b"jpeg")

    url = storage.upload_screenshots_batch(
        {1.25: str(source)}, video_hash="video-a", user_id="user-a"
    )[1.25]

    assert url is not None
    assert "/api/upload/object/screenshots/user-a/video-a/1.25.jpg" in url
    key = storage.parse_screenshot_key(url)
    assert key == "screenshots/user-a/video-a/1.25.jpg"
    assert storage.is_owned_screenshot_key(key, "user-a", "video-a")
    assert not storage.is_owned_screenshot_key(key, "user-b", "video-a")


@pytest.mark.parametrize(
    "key",
    ["../secret", "/etc/passwd", "uploads/user/../../secret", "uploads\\user\\file"],
)
def test_local_storage_rejects_path_traversal(tmp_path, key):
    storage = LocalStorageService(str(tmp_path))
    with pytest.raises(ValueError):
        storage.file_exists(key)


def test_local_storage_rejects_symlink_escape(tmp_path):
    storage = LocalStorageService(str(tmp_path / "media"))
    outside = tmp_path / "outside"
    outside.mkdir()
    (storage.root / "uploads").symlink_to(outside, target_is_directory=True)

    with pytest.raises(ValueError):
        storage.file_exists("uploads/user/intent/video.mp4")


def test_local_storage_rejects_same_root_cross_owner_symlink(tmp_path):
    storage = LocalStorageService(str(tmp_path / "media"))
    owner_b = storage.root / "uploads" / "user-b" / "intent"
    owner_b.mkdir(parents=True)
    (owner_b / "video.mp4").write_bytes(b"owner-b")
    (storage.root / "uploads" / "user-a").symlink_to("user-b", target_is_directory=True)

    with pytest.raises(ValueError, match="symlink"):
        storage.get_file_size("uploads/user-a/intent/video.mp4")


def test_atomic_writer_rejects_destination_symlink_created_mid_write(tmp_path):
    storage = LocalStorageService(str(tmp_path / "media"))
    key = storage.upload_path("user", "intent", "video.mp4")
    outside = tmp_path / "outside.mp4"
    outside.write_bytes(b"outside")

    with pytest.raises(ValueError, match="symlink"):
        with storage.atomic_writer(key) as handle:
            handle.write(b"replacement")
            destination = storage.root / key
            destination.symlink_to(outside)

    assert outside.read_bytes() == b"outside"
    assert (storage.root / key).is_symlink()
    assert not list((storage.root / key).parent.glob(".upload-*"))


def test_atomic_writer_does_not_publish_partial_file(tmp_path):
    storage = LocalStorageService(str(tmp_path))
    key = storage.upload_path("user", "intent", "video.mp4")

    with pytest.raises(RuntimeError):
        with storage.atomic_writer(key) as handle:
            handle.write(b"partial")
            raise RuntimeError("interrupted")

    assert not storage.file_exists(key)


def test_storage_selection_is_explicit(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "LOCAL_MODE", True)
    monkeypatch.setattr(settings, "LOCAL_STORAGE_ROOT", str(tmp_path))
    reset_media_storage_for_tests()
    assert isinstance(get_media_storage(), LocalStorageService)

    monkeypatch.setattr(settings, "LOCAL_MODE", False)
    monkeypatch.setattr(settings, "ENABLE_GCS_UPLOADS", True)
    monkeypatch.setattr(settings, "GCS_BUCKET_NAME", "bucket")
    reset_media_storage_for_tests()
    gcs_storage = get_media_storage()
    assert isinstance(gcs_storage, GCSMediaStorage)
    assert gcs_storage.is_owned_media_key("processed/user-a/intent/video.mp4", "user-a")
    assert not gcs_storage.is_owned_media_key("processed/user-b/intent/video.mp4", "user-a")


def test_runtime_validation_rejects_ambiguous_mode(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "LOCAL_MODE", True)
    monkeypatch.setattr(settings, "ENABLE_GCS_UPLOADS", True)
    monkeypatch.setattr(settings, "LOCAL_STORAGE_ROOT", str(tmp_path))
    monkeypatch.setattr(settings, "SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setattr(settings, "SUPABASE_SERVICE_KEY", "service-key")
    with pytest.raises(RuntimeError, match="cannot both"):
        settings.validate_runtime()


def test_runtime_validation_requires_production_prerequisites(monkeypatch):
    monkeypatch.setattr(settings, "LOCAL_MODE", False)
    monkeypatch.setattr(settings, "ENABLE_GCS_UPLOADS", False)
    monkeypatch.setattr(settings, "SUPABASE_URL", "")
    monkeypatch.setattr(settings, "SUPABASE_SERVICE_KEY", "")
    with pytest.raises(RuntimeError, match="Supabase"):
        settings.validate_runtime()


def test_production_storage_fails_when_gcs_is_disabled(monkeypatch):
    monkeypatch.setattr(settings, "LOCAL_MODE", False)
    monkeypatch.setattr(settings, "ENABLE_GCS_UPLOADS", False)
    reset_media_storage_for_tests()
    with pytest.raises(RuntimeError, match="ENABLE_GCS_UPLOADS"):
        get_media_storage()


def test_dispatcher_selection_is_explicit(monkeypatch):
    monkeypatch.setattr(settings, "LOCAL_MODE", True)
    reset_job_dispatcher_for_tests()
    assert isinstance(get_job_dispatcher(), LocalDetachedJobDispatcher)

    monkeypatch.setattr(settings, "LOCAL_MODE", False)
    reset_job_dispatcher_for_tests()
    assert isinstance(get_job_dispatcher(), CloudRunJobDispatcher)


def test_local_dispatch_is_detached_and_does_not_use_shell(monkeypatch, tmp_path):
    popen = Mock()
    monkeypatch.setattr(subprocess, "Popen", popen)
    dispatcher = LocalDetachedJobDispatcher(tmp_path)

    dispatcher.dispatch("job-123")

    args, kwargs = popen.call_args
    assert args[0] == [sys.executable, "-m", "worker_main", "job-123"]
    assert kwargs["cwd"] == str(tmp_path)
    assert kwargs["env"]["LOCAL_MODE"] == "true"
    assert kwargs["stdin"] is subprocess.DEVNULL
    assert kwargs["stdout"] is subprocess.DEVNULL
    assert kwargs["stderr"] is subprocess.DEVNULL
    assert kwargs["start_new_session"] is True
    assert "shell" not in kwargs


def test_detached_worker_reaper_schedules_wait(monkeypatch):
    process = Mock(pid=42)
    thread = Mock()
    thread_factory = Mock(return_value=thread)
    monkeypatch.setattr("services.job_dispatcher.threading.Thread", thread_factory)

    _schedule_reap(process)

    assert thread_factory.call_args.kwargs == {
        "target": process.wait,
        "name": "local-worker-reaper-42",
        "daemon": True,
    }
    thread.start.assert_called_once_with()


def test_screenshot_key_upload_listing_and_face_materialization_are_consistent(
    monkeypatch, tmp_path
):
    module_path = Path(__file__).parents[1] / "routers" / "face_tags.py"
    spec = importlib.util.spec_from_file_location("storage_face_tags_module", module_path)
    face_tags = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(face_tags)

    storage = LocalStorageService(str(tmp_path / "media"))
    source = tmp_path / "frame.jpg"
    source.write_bytes(b"jpeg")
    urls = storage.upload_screenshots_batch(
        {1.25: str(source)}, video_hash="video-a", user_id="user-a"
    )
    key = storage.screenshot_key("user-a", "video-a", 1.25)
    url = urls[1.25]

    assert url is not None
    assert storage.parse_screenshot_key(url) == key
    assert storage.list_screenshot_keys("user-a", "video-a") == [key]

    monkeypatch.setattr(settings, "LOCAL_MODE", True)
    monkeypatch.setattr(settings, "ENABLE_GCS_UPLOADS", False)
    monkeypatch.setattr(settings, "LOCAL_STORAGE_ROOT", str(storage.root))
    reset_media_storage_for_tests()
    monkeypatch.setattr(
        face_tags.transcription_repository,
        "get_transcription",
        lambda *_args: {"transcription": {"segments": [{"screenshot_url": url}]}},
    )
    monkeypatch.setattr(
        face_tags.transcription_repository,
        "hash_resources_are_owner_exclusive",
        lambda *_args: False,
    )
    request = SimpleNamespace(state=SimpleNamespace(profile={"id": "user-a"}))
    materialized = face_tags._owned_screenshot_source(request, "video-a", url)
    try:
        with open(materialized, "rb") as handle:
            assert handle.read() == b"jpeg"
    finally:
        os.unlink(materialized)


def test_frontend_upload_credentials_are_limited_to_local_api_endpoint():
    source = (
        Path(__file__).parents[2]
        / "frontend"
        / "src"
        / "services"
        / "gcsUpload.ts"
    ).read_text()

    assert "shouldSendUploadCredentials(uploadUrl)" in source
    assert "upload.pathname.startsWith('/api/upload/local/')" in source
    assert "uploadUrl.startsWith(API_BASE_URL)" not in source


def test_frontend_uses_only_durable_job_submission():
    frontend = Path(__file__).parents[2] / "frontend" / "src"
    api_source = (frontend / "services" / "api.ts").read_text()
    upload_source = (
        frontend
        / "components"
        / "features"
        / "transcription"
        / "TranscriptionUpload.tsx"
    ).read_text()

    upload_zone_source = (
        frontend
        / "components"
        / "features"
        / "transcription"
        / "UploadZone.tsx"
    ).read_text()

    for route in (
        "/transcribe/",
        "/transcribe_local/",
        "/transcribe_local_stream/",
        "/transcribe_gcs_stream/",
    ):
        assert route not in api_source
    assert "submitBackgroundJob" in api_source
    assert "uploadMedia(file" in api_source
    assert "backgroundJobSubmit.submit(file" in upload_source
    assert "transcriptionMethod" not in upload_source
    assert "Stay here" not in upload_zone_source
