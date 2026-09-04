"""
Proves that transcript retrieval-index configurations (chunk_size_2/3/5) are
strictly isolated: a search scoped to one index_config never returns chunks
indexed under another config, even when match_count exceeds a single
config's own row count.

Run: python -m pytest tests/test_retrieval_index_config.py -q  (from backend/)
"""
import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_TMP = tempfile.mkdtemp(prefix="ai_subs_retrieval_index_test_")
os.environ["LOCAL_MODE"] = "true"
os.environ.setdefault("LOCAL_DATA_DIR", _TMP)

from services.local_db import LocalSupabaseClient  # noqa: E402
import services.transcript_embedding_service as embedding_service_module  # noqa: E402
from services.transcript_embedding_service import transcript_embedding_service  # noqa: E402


@pytest.fixture()
def client():
    with tempfile.TemporaryDirectory() as tmp:
        yield LocalSupabaseClient(db_path=os.path.join(tmp, "test.db"))


class _FakeEmbeddingModel:
    """Deterministic stand-in for SentenceTransformer -- no model download."""

    def encode(self, texts, convert_to_numpy=True):
        import numpy as np

        return np.array([[float(i + 1), 0.0, 0.0, 0.0] for i in range(len(texts))])


def _row(index_config, chunk_index, text, vector, user_id="user-1", video_hash="video-1"):
    return {
        "user_id": user_id,
        "video_hash": video_hash,
        "index_config": index_config,
        "chunk_index": chunk_index,
        "start_time": float(chunk_index * 10),
        "end_time": float(chunk_index * 10 + 5),
        "start_timestamp": "00:00:00",
        "end_timestamp": "00:00:05",
        "speaker": "SPEAKER_00",
        "segment_count": 1,
        "chunk_text": text,
        "embedding": vector,
    }


def test_search_only_returns_rows_from_the_requested_index_config(client):
    rows = [
        _row("chunk_size_2", 0, "size2 chunk a", [1.0, 0.0, 0.0, 0.0]),
        _row("chunk_size_2", 1, "size2 chunk b", [1.0, 0.1, 0.0, 0.0]),
        _row("chunk_size_3", 0, "size3 chunk a", [0.0, 1.0, 0.0, 0.0]),
        _row("chunk_size_5", 0, "size5 chunk a", [0.0, 0.0, 1.0, 0.0]),
    ]
    client.table("transcript_embeddings").upsert(
        rows, on_conflict="user_id,video_hash,index_config,chunk_index"
    ).execute()

    result = client.rpc(
        "search_transcript_chunks_by_embedding",
        {
            "p_user_id": "user-1",
            "query_embedding": [1.0, 0.0, 0.0, 0.0],
            "target_video_hash": "video-1",
            # Intentionally higher than any single config's row count, so a
            # leak from another config would show up if filtering were broken.
            "match_count": 10,
            "target_index_config": "chunk_size_2",
        },
    ).execute()

    assert sorted(r["chunk_text"] for r in result.data) == ["size2 chunk a", "size2 chunk b"]


def test_search_defaults_to_baseline_when_index_config_omitted(client):
    rows = [
        _row("chunk_size_3", 0, "baseline chunk", [1.0, 0.0, 0.0, 0.0]),
        _row("chunk_size_5", 0, "experiment chunk", [1.0, 0.0, 0.0, 0.0]),
    ]
    client.table("transcript_embeddings").upsert(
        rows, on_conflict="user_id,video_hash,index_config,chunk_index"
    ).execute()

    result = client.rpc(
        "search_transcript_chunks_by_embedding",
        {
            "p_user_id": "user-1",
            "query_embedding": [1.0, 0.0, 0.0, 0.0],
            "target_video_hash": "video-1",
            "match_count": 10,
            # No target_index_config -- must default to the chunk_size_3 baseline.
        },
    ).execute()

    assert [r["chunk_text"] for r in result.data] == ["baseline chunk"]


def test_index_and_search_respect_index_config_end_to_end(monkeypatch, tmp_path):
    """Exercises the real service functions (not just the raw RPC emulation)."""
    client = LocalSupabaseClient(db_path=str(tmp_path / "e2e.db"))
    monkeypatch.setattr(embedding_service_module, "supabase", lambda: client)
    monkeypatch.setattr(transcript_embedding_service, "_embedding_model", _FakeEmbeddingModel())

    segments = [
        {"start": float(i), "end": float(i + 1), "text": f"segment {i}", "speaker": "SPEAKER_00"}
        for i in range(10)
    ]
    user_id, video_hash = "user-xyz", "video-abc"

    transcript_embedding_service.index_transcript_chunks(
        video_hash=video_hash, segments=segments, user_id=user_id,
        chunk_size=2, index_config="chunk_size_2",
    )
    transcript_embedding_service.index_transcript_chunks(
        video_hash=video_hash, segments=segments, user_id=user_id,
        chunk_size=5, index_config="chunk_size_5",
    )

    results_2 = transcript_embedding_service.search_transcript_chunks(
        video_hash=video_hash, query="segment", user_id=user_id,
        n_results=10, index_config="chunk_size_2",
    )
    results_5 = transcript_embedding_service.search_transcript_chunks(
        video_hash=video_hash, query="segment", user_id=user_id,
        n_results=10, index_config="chunk_size_5",
    )

    # 10 segments / chunk_size 2 = 5 chunks; 10 segments / chunk_size 5 = 2 chunks.
    assert len(results_2) == 5
    assert len(results_5) == 2
    assert all(r["metadata"]["segment_count"] == 2 for r in results_2)
    assert all(r["metadata"]["segment_count"] == 5 for r in results_5)

    # Rebuilding one config must not touch another config's rows for the same video.
    rebuilt = transcript_embedding_service.index_transcript_chunks(
        video_hash=video_hash, segments=segments, user_id=user_id,
        chunk_size=2, index_config="chunk_size_2", force_reindex=True,
    )
    assert rebuilt == 5
    results_5_after = transcript_embedding_service.search_transcript_chunks(
        video_hash=video_hash, query="segment", user_id=user_id,
        n_results=10, index_config="chunk_size_5",
    )
    assert len(results_5_after) == 2
