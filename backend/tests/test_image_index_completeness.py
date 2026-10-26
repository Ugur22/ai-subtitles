from types import SimpleNamespace

import numpy as np
import pytest
from PIL import Image

from services import image_embedding_service as image_module
from services.index_errors import IncompleteIndexError

USER, VIDEO = "user-1", "hash-1"


class _Encoder:
    def encode(self, images, **_kwargs):
        return np.array([[0.1, 0.2] for _ in images])


class _Query:
    def __init__(self, client, name):
        self.client, self.name, self.op = client, name, None

    def select(self, *_args, **_kwargs):
        self.op = "select"
        return self

    def upsert(self, records, **_kwargs):
        self.op, self.records = "upsert", records
        return self

    def eq(self, *_args):
        return self

    def limit(self, *_args):
        return self

    def execute(self):
        if self.op == "select":
            return SimpleNamespace(count=self.client.existing_rows, data=[])
        if self.client.fail_upserts:
            raise RuntimeError("write failed")
        self.client.written.extend(self.records)
        return SimpleNamespace(data=[])


class _Client:
    def __init__(self, existing_rows, fail_upserts=False):
        self.existing_rows, self.fail_upserts, self.written = existing_rows, fail_upserts, []

    def table(self, name):
        return _Query(self, name)


def _setup(monkeypatch, tmp_path, *, segments, screenshots, existing_rows, fail_upserts=False):
    """`segments` segments starting at 1.0s apart; only the first `screenshots` have a GCS object."""
    segment_list = [
        {"id": i, "start": float(i + 1), "end": float(i + 2), "speaker": "SPEAKER_00"}
        for i in range(segments)
    ]
    keys = [f"screenshots/{USER}/{VIDEO}/{seg['start']:.2f}.jpg" for seg in segment_list[:screenshots]]
    materialized = []

    def materialize(key, *_args):
        materialized.append(key)
        path = tmp_path / key.rsplit("/", 1)[-1]
        Image.new("RGB", (4, 4)).save(path, format="JPEG")
        return str(path)

    storage = SimpleNamespace(
        list_screenshot_keys=lambda *_a, **_k: keys,
        parse_screenshot_key=lambda _reference: None,
        is_owned_screenshot_key=lambda *_a, **_k: True,
        materialize_screenshot=materialize,
        generate_download_url=lambda key: f"signed:{key}",
    )
    client = _Client(existing_rows, fail_upserts)
    monkeypatch.setattr(image_module, "supabase", lambda: client)
    monkeypatch.setattr(image_module, "get_media_storage", lambda: storage)
    monkeypatch.setattr(image_module.time, "sleep", lambda _seconds: None)

    service = image_module.ImageEmbeddingService()
    service._clip_model = _Encoder()
    service._index_face_presence_from_segments = lambda *_a, **_k: 0
    return service, segment_list, client, materialized


def test_partial_index_is_completed_instead_of_returning_early(monkeypatch, tmp_path):
    service, segments, client, materialized = _setup(
        monkeypatch, tmp_path, segments=5, screenshots=5, existing_rows=2
    )

    assert service.index_video_images(VIDEO, segments, USER) == 5
    assert len(client.written) == 5
    assert len(materialized) == 5


def test_complete_index_returns_early_without_downloading(monkeypatch, tmp_path):
    service, segments, client, materialized = _setup(
        monkeypatch, tmp_path, segments=5, screenshots=5, existing_rows=5
    )

    assert service.index_video_images(VIDEO, segments, USER) == 5
    assert client.written == [] and materialized == []


def test_segments_without_a_screenshot_do_not_keep_the_index_incomplete(monkeypatch, tmp_path):
    service, segments, client, materialized = _setup(
        monkeypatch, tmp_path, segments=5, screenshots=3, existing_rows=3
    )

    assert service.index_video_images(VIDEO, segments, USER) == 3
    assert client.written == [] and materialized == []


def test_force_reindex_bypasses_the_early_return(monkeypatch, tmp_path):
    service, segments, client, _ = _setup(
        monkeypatch, tmp_path, segments=5, screenshots=5, existing_rows=5
    )

    assert service.index_video_images(VIDEO, segments, USER, force_reindex=True) == 5
    assert len(client.written) == 5


def test_failed_batches_raise_incomplete_index_error(monkeypatch, tmp_path):
    service, segments, _, _ = _setup(
        monkeypatch, tmp_path, segments=5, screenshots=5, existing_rows=0, fail_upserts=True
    )

    with pytest.raises(IncompleteIndexError) as raised:
        service.index_video_images(VIDEO, segments, USER)

    assert (raised.value.indexed, raised.value.expected) == (0, 5)
