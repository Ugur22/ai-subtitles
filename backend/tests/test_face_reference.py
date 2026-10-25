"""Unit tests for the outlier-robust face-tag reference embedding."""
import os
import sys
from types import SimpleNamespace

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from routers.chat import _robust_mean_embedding  # noqa: E402


def _near(base, seed, noise=0.05):
    rng = np.random.default_rng(seed)
    return base + rng.normal(0, noise, base.shape)


def _unit_axis(i, dim=32):
    v = np.zeros(dim)
    v[i] = 1.0
    return v


def test_outlier_is_dropped():
    base = _unit_axis(0)
    tags = [_near(base, s) for s in range(5)] + [_unit_axis(7)]
    ref, ignored = _robust_mean_embedding(tags, 0.5)
    assert ignored == 1
    assert float(ref @ base) > 0.99


def test_too_few_tags_keeps_everything():
    tags = [_unit_axis(0), _near(_unit_axis(0), 1), _unit_axis(7)]
    _, ignored = _robust_mean_embedding(tags, 0.5)
    assert ignored == 0


def test_never_drops_more_than_half():
    tags = [_unit_axis(i) for i in range(6)]
    _, ignored = _robust_mean_embedding(tags, 0.99)
    assert ignored == 0


def test_empty_returns_none():
    assert _robust_mean_embedding([], 0.5) == (None, 0)


def test_restricted_scene_search_filters_owner_video_and_frame_ids(monkeypatch):
    from services import image_embedding_service as image_module

    def row(frame_id, embedding, user_id="owner", video_hash="video", screenshot_url=None):
        return {
            "id": frame_id,
            "user_id": user_id,
            "video_hash": video_hash,
            "segment_id": frame_id,
            "start_time": 1.0,
            "end_time": 2.0,
            "speaker": "Person",
            "screenshot_url": screenshot_url or f"owner/{frame_id}.jpg",
            "embedding": embedding,
        }

    rows = [
        row("weaker", [0.8, 0.6]),
        row("best", "[1.0, 0.0]"),
        row("other-owner", [1.0, 0.0], user_id="other"),
        row("other-video", [1.0, 0.0], video_hash="other"),
        row("not-present", [1.0, 0.0]),
        row("bad-url", [1.0, 0.0], screenshot_url="other/private.jpg"),
    ]

    class Client:
        def table(self, name):
            assert name == "image_embeddings"
            self.filters = {}
            self.ids = []
            return self

        def select(self, _columns):
            return self

        def eq(self, name, value):
            self.filters[name] = value
            return self

        def in_(self, name, values):
            assert name == "id"
            self.ids = values
            return self

        def execute(self):
            return SimpleNamespace(data=[
                dict(item) for item in rows
                if item["id"] in self.ids
                and all(item[name] == value for name, value in self.filters.items())
            ])

    class Encoder:
        def encode(self, *_args, **_kwargs):
            return np.array([[1.0, 0.0]])

    storage = SimpleNamespace(
        parse_screenshot_key=lambda url: url,
        is_owned_screenshot_key=lambda key, user_id, _video_hash, **_kwargs: key.startswith(f"{user_id}/"),
        generate_download_url=lambda key: f"fresh:{key}",
    )
    monkeypatch.setattr(image_module, "supabase", lambda: Client())
    monkeypatch.setattr(image_module, "get_media_storage", lambda: storage)
    service = image_module.ImageEmbeddingService()
    service._clip_model = Encoder()

    results = service.search_images_within(
        "video", "person swimming", "owner",
        ["weaker", "best", "other-owner", "other-video", "bad-url"], n_results=10,
    )

    assert [item["metadata"]["image_embedding_id"] for item in results] == ["best", "weaker"]
    assert results[0]["similarity"] > results[1]["similarity"]
    assert all(item["screenshot_url"].startswith("fresh:owner/") for item in results)
