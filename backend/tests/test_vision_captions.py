import asyncio
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from fastapi import HTTPException

from services import image_embedding_service as image_module
from services.background_worker import _compute_dense_timestamps, _extract_dense_segments


class Query:
    def __init__(self, client, name):
        self.client, self.name, self.filters = client, name, {}
        self.operation, self.payload = None, None

    def eq(self, name, value):
        self.filters[name] = value
        return self

    def delete(self):
        self.operation = "delete"
        return self

    def update(self, payload):
        self.operation, self.payload = "update", payload
        return self

    def insert(self, payload):
        self.operation, self.payload = "insert", payload
        return self

    def execute(self):
        self.client.writes.append((self.name, self.operation, dict(self.filters), self.payload))
        if self.operation == "update":
            for row in self.client.rows:
                if all(row.get(key) == value for key, value in self.filters.items()):
                    row.update(self.payload)
        return SimpleNamespace(data=[])


class Client:
    def __init__(self, rows):
        self.rows, self.writes, self.calls = rows, [], []

    def table(self, name):
        return Query(self, name)

    def rpc(self, name, params):
        self.calls.append((name, params))
        if name == "store_image_caption":
            return SimpleNamespace(execute=lambda: SimpleNamespace(data=True))
        rows = [dict(row) for row in self.rows
                if row["user_id"] == params["p_user_id"]
                and row["video_hash"] == params["target_video_hash"]]
        if name == "caption_frames_to_process":
            rows = rows[:params["batch_limit"]]
        return SimpleNamespace(execute=lambda: SimpleNamespace(data=rows))


class Encoder:
    def __init__(self):
        self.inputs = []

    def encode(self, texts, **_kwargs):
        self.inputs.extend(texts)
        return np.array([[1.0, 0.0] for _ in texts])


def image(owner, frame):
    return dict(id=frame, user_id=owner, video_hash="same-hash", segment_id=frame,
                screenshot_url=f"{owner}/{frame}.jpg", caption=None,
                start_time=1.0, end_time=2.0, speaker=None, similarity=0.9)


@pytest.fixture
def caption_setup(monkeypatch, tmp_path):
    rows = [image("alice", "a1"), image("alice", "a2"), image("bob", "b1")]
    client, encoder, generated = Client(rows), Encoder(), []

    class Provider:
        def is_available(self):
            return True

        async def caption_image(self, path):
            generated.append(path)
            return "A person is swimming across the lake."

    def materialize(key, owner, video, _legacy):
        assert key.startswith(f"{owner}/") and video == "same-hash"
        path = tmp_path / Path(key).name
        path.write_bytes(b"image")
        return str(path)

    storage = SimpleNamespace(
        parse_screenshot_key=lambda reference: reference,
        is_owned_screenshot_key=lambda key, owner, _video, **_kwargs: key.startswith(f"{owner}/"),
        materialize_screenshot=materialize,
        generate_download_url=lambda key: f"fresh:{key}",
    )
    monkeypatch.setattr(image_module.settings, "ENABLE_VISION_CAPTIONS", True)
    monkeypatch.setattr(image_module, "supabase", lambda: client)
    monkeypatch.setattr(image_module, "get_media_storage", lambda: storage)
    monkeypatch.setattr(image_module.ImageEmbeddingService, "caption_embedding_model", property(lambda _: encoder))
    import llm_providers
    monkeypatch.setattr(llm_providers, "GrokProvider", Provider)
    return image_module.ImageEmbeddingService(), client, encoder, generated


def test_caption_generation_is_bounded_and_owner_scoped(caption_setup):
    service, client, _, generated = caption_setup
    count = asyncio.run(service.caption_video_images("same-hash", "alice", max_frames=1))

    assert count == 1 and len(generated) == 1
    assert not Path(generated[0]).exists()
    assert client.rows[-1]["caption"] is None
    assert not client.writes
    discovery = next(params for name, params in client.calls if name == "caption_frames_to_process")
    assert discovery["batch_limit"] == 1
    stored = [params for name, params in client.calls if name == "store_image_caption"]
    assert len(stored) == 1
    assert stored[0]["p_user_id"] == "alice" and stored[0]["target_video_hash"] == "same-hash"
    assert stored[0]["target_embedding_model"] == image_module.settings.TEXT_EMBEDDING_MODEL
    assert all(params["p_user_id"] == "alice" for _, params in client.calls)


def test_caption_search_passes_owner_model_and_returns_fresh_owned_urls(caption_setup):
    service, client, encoder, _ = caption_setup
    results = service.search_images_by_caption("same-hash", "swimming", "alice")

    assert {item["metadata"]["image_embedding_id"] for item in results} == {"a1", "a2"}
    assert all(item["screenshot_url"].startswith("fresh:alice/") for item in results)
    name, params = client.calls[-1]
    assert name == "search_images_by_caption_sentences"
    assert params["p_user_id"] == "alice"
    assert params["target_embedding_model"] == image_module.settings.TEXT_EMBEDDING_MODEL
    assert encoder.inputs[0].endswith("swimming")


def test_caption_failure_keeps_rows_retryable(caption_setup, monkeypatch):
    service, client, _, _ = caption_setup
    import llm_providers

    class Provider:
        def is_available(self):
            return True

        async def caption_image(self, _path):
            raise RuntimeError("provider unavailable")

    monkeypatch.setattr(llm_providers, "GrokProvider", Provider)
    assert asyncio.run(service.caption_video_images("same-hash", "alice")) == 0
    assert not client.writes
    assert not [name for name, _ in client.calls if name == "store_image_caption"]


def test_caption_search_missing_migration_falls_back(caption_setup, monkeypatch):
    service, _, _, _ = caption_setup
    monkeypatch.setattr(image_module, "supabase", lambda: (_ for _ in ()).throw(RuntimeError("missing schema")))
    assert service.search_images_by_caption("same-hash", "swimming", "alice") == []


def test_dense_sampling_is_spread_bounded_and_avoids_existing_frames():
    assert _compute_dense_timestamps(100, [], 0, 2) == []
    frames = _compute_dense_timestamps(100, [5, 35], 10, 2, 3)
    assert len(frames) == 3 and frames[-1] > 50
    assert all(abs(frame - known) > 2 for frame in frames for known in [5, 35])


def test_dense_upload_preserves_owner_and_cleans_failed_frames(monkeypatch, tmp_path):
    from services import background_worker as worker
    extracted = tmp_path / "frame.jpg"
    extracted.write_bytes(b"frame")
    captured = {}

    def upload(**kwargs):
        captured.update(kwargs)
        return {5.0: "owned/frame.jpg"}

    monkeypatch.setattr(worker.VideoService, "extract_screenshots_parallel_from_url", lambda **_kwargs: {5.0: str(extracted), 15.0: None})
    monkeypatch.setattr(worker, "get_media_storage", lambda: SimpleNamespace(upload_screenshots_batch=upload))
    frames = asyncio.run(_extract_dense_segments("video", "alice", "read-url", 20, [], str(tmp_path), 2))

    assert captured["user_id"] == "alice" and captured["video_hash"] == "video"
    assert list(captured["screenshot_paths"]) == [5.0]
    assert not extracted.exists()
    assert len(frames) == 1 and frames[0]["id"].startswith("dense_")


def test_targeted_backfill_requires_owner():
    from routers.jobs import backfill_captions
    with pytest.raises(HTTPException) as error:
        asyncio.run(backfill_captions.__wrapped__(
            SimpleNamespace(), batch_size=3, video_hash="same-hash", user_id=None,
            force=False, dense=False, max_frames=8,
        ))
    assert error.value.status_code == 400


def test_backfill_caps_attempts_to_the_total_request_budget(monkeypatch):
    from routers import jobs
    from routers import chat
    from services import supabase_service, transcription_repository

    captured = []

    async def caption(video, owner, **kwargs):
        captured.append((video, owner, kwargs))
        return 1

    async def key(_owner, _provider):
        return None

    monkeypatch.setattr(jobs.settings, "ENABLE_VISION_CAPTIONS", True)
    monkeypatch.setattr(jobs.settings, "CAPTION_BACKFILL_MAX_FRAMES", 4)
    monkeypatch.setattr(supabase_service, "supabase", lambda: SimpleNamespace())
    monkeypatch.setattr(transcription_repository.transcription_repository, "get_job", lambda _video, _owner: {"id": "owned-job"})
    monkeypatch.setattr(jobs, "get_media_storage", lambda: SimpleNamespace())
    monkeypatch.setattr(chat, "_get_saved_provider_key", key)
    monkeypatch.setattr(image_module.image_embedding_service, "caption_video_images", caption)

    response = asyncio.run(jobs.backfill_captions.__wrapped__(
        SimpleNamespace(), batch_size=3, video_hash="same-hash", user_id="alice",
        force=False, dense=False, max_frames=32,
    ))

    assert response.processed_videos == 1 and response.captioned_images == 1
    assert captured[0][:2] == ("same-hash", "alice")
    assert captured[0][2]["max_frames"] == 4
    assert 0 < captured[0][2]["timeout_seconds"] <= 240
