"""Unit tests for the LOCAL_MODE SQLite fake supabase client.

Each test exercises a real call shape copied from the backend's supabase-py
usage (job_queue_service, pipeline_cache_service, key_validator, admin, etc.).
Run: python -m pytest tests/test_local_db.py -q  (from backend/)
"""
import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_TMP = tempfile.mkdtemp(prefix="ai_subs_local_test_")
os.environ["LOCAL_MODE"] = "true"
os.environ["LOCAL_DATA_DIR"] = _TMP

from services.local_db import (  # noqa: E402
    LOCAL_USER_ID,
    LocalAPIError,
    LocalSupabaseClient,
)


@pytest.fixture()
def client():
    with tempfile.TemporaryDirectory() as tmp:
        yield LocalSupabaseClient(db_path=os.path.join(tmp, "test.db"))


def _make_job(client, **overrides):
    payload = {
        "filename": "video.mp4",
        "gcs_path": "uploads/abc_video.mp4",
        "file_size_bytes": 1024,
        "video_hash": "hash1",
        "status": "pending",
    }
    payload.update(overrides)
    return client.table("jobs").insert(payload).execute().data[0]


def test_insert_generates_defaults(client):
    job = _make_job(client)
    assert job["id"] and job["access_token"] and job["id"] != job["access_token"]
    assert job["created_at"].endswith("+00:00")
    assert job["status"] == "pending"
    assert job["progress"] == 0


def test_select_eq_and_params_json_roundtrip(client):
    _make_job(client, params={"language": "en", "num_speakers": 2})
    rows = client.table("jobs").select("*").eq("video_hash", "hash1").execute().data
    assert len(rows) == 1
    assert rows[0]["params"] == {"language": "en", "num_speakers": 2}


def test_count_exact_with_in_(client):
    a = _make_job(client)
    b = _make_job(client, video_hash="hash2")
    resp = (
        client.table("jobs")
        .select("id", count="exact")
        .in_("access_token", [a["access_token"], b["access_token"], "nope"])
        .execute()
    )
    assert resp.count == 2
    assert {r["id"] for r in resp.data} == {a["id"], b["id"]}


def test_or_filter_user_or_tokens(client):
    mine = _make_job(client, user_id=LOCAL_USER_ID)
    other = _make_job(client, video_hash="hash2")
    or_filter = f"user_id.eq.{LOCAL_USER_ID},access_token.in.({other['access_token']})"
    resp = client.table("jobs").select("id", count="exact").or_(or_filter).execute()
    assert resp.count == 2
    assert {r["id"] for r in resp.data} == {mine["id"], other["id"]}


def test_not_is_null(client):
    done = _make_job(
        client,
        status="completed",
        started_at="2026-07-24T10:00:00+00:00",
        completed_at="2026-07-24T10:05:00+00:00",
    )
    _make_job(client, video_hash="hash2")
    rows = (
        client.table("jobs")
        .select("*")
        .eq("status", "completed")
        .not_.is_("started_at", "null")
        .not_.is_("completed_at", "null")
        .execute()
        .data
    )
    assert [r["id"] for r in rows] == [done["id"]]


def test_order_desc_and_range_pagination(client):
    ids = []
    for i in range(5):
        ids.append(_make_job(client, filename=f"v{i}.mp4")["id"])
        # distinct created_at not guaranteed; order by insertion via created_at
    rows = (
        client.table("jobs")
        .select("*")
        .order("created_at", desc=True)
        .range(0, 1)
        .execute()
        .data
    )
    assert len(rows) == 2


def test_update_stamps_updated_at_and_returns_rows(client):
    job = _make_job(client)
    rows = (
        client.table("jobs")
        .update({"status": "processing", "progress": 10})
        .eq("id", job["id"])
        .execute()
        .data
    )
    assert rows[0]["status"] == "processing"
    assert rows[0]["updated_at"] >= job["updated_at"]


def test_upsert_pipeline_cache_on_conflict(client):
    for payload in ({"segments": [1, 2]}, {"segments": [1, 2, 3]}):
        client.table("pipeline_cache").upsert(
            {"video_hash": "hash1", "stage": "transcription", "data": payload},
            on_conflict="video_hash,stage",
        ).execute()
    rows = (
        client.table("pipeline_cache")
        .select("data")
        .eq("video_hash", "hash1")
        .eq("stage", "transcription")
        .execute()
        .data
    )
    assert len(rows) == 1
    assert rows[0]["data"] == {"segments": [1, 2, 3]}


def test_delete_with_in_and_lt(client):
    old = _make_job(client, status="completed", created_at="2020-01-01T00:00:00+00:00")
    fresh = _make_job(client, status="completed", video_hash="hash2")
    deleted = (
        client.table("jobs")
        .delete()
        .in_("status", ["completed", "failed", "cancelled"])
        .lt("created_at", "2025-01-01T00:00:00")
        .execute()
        .data
    )
    assert [r["id"] for r in deleted] == [old["id"]]
    remaining = client.table("jobs").select("id").execute().data
    assert [r["id"] for r in remaining] == [fresh["id"]]


def test_single_returns_dict_or_raises(client):
    job = _make_job(client)
    row = client.table("jobs").select("*").eq("id", job["id"]).single().execute().data
    assert isinstance(row, dict) and row["id"] == job["id"]
    with pytest.raises(LocalAPIError):
        client.table("jobs").select("*").eq("id", "missing").single().execute()


def test_seeded_admin_profile_bools(client):
    profile = (
        client.table("user_profiles").select("*").eq("id", LOCAL_USER_ID).single().execute().data
    )
    assert profile["is_admin"] is True
    assert profile["email_verified"] is True
    assert profile["default_llm_provider"] is None


def test_is_null_on_user_api_keys(client):
    client.table("user_api_keys").insert(
        {
            "user_id": LOCAL_USER_ID,
            "provider": "groq",
            "encrypted_key": "abcd",
            "key_suffix": "1234",
        }
    ).execute()
    rows = (
        client.table("user_api_keys").select("*").is_("is_valid", "null").execute().data
    )
    assert len(rows) == 1 and rows[0]["is_valid"] is None


def test_rpc_search_images_by_embedding(client):
    def emb(x, y):
        return [x, y] + [0.0] * 510

    for i, (segment, speaker, vector) in enumerate(
        [("s1", "SPEAKER_00", emb(1, 0)), ("s2", "SPEAKER_01", emb(0, 1)), ("s3", "SPEAKER_00", emb(0.9, 0.1))]
    ):
        client.table("image_embeddings").insert(
            {
                "video_hash": "hash1",
                "segment_id": segment,
                "start_time": float(i),
                "end_time": float(i + 1),
                "speaker": speaker,
                "screenshot_url": f"/static/screenshots/hash1/{segment}.jpg",
                "embedding": vector,
            }
        ).execute()

    result = client.rpc(
        "search_images_by_embedding",
        {"query_embedding": emb(1, 0), "target_video_hash": "hash1", "match_count": 2},
    ).execute()
    assert [r["segment_id"] for r in result.data] == ["s1", "s3"]
    assert result.data[0]["similarity"] > result.data[1]["similarity"]

    filtered = client.rpc(
        "search_images_by_embedding",
        {
            "query_embedding": emb(1, 0),
            "target_video_hash": "hash1",
            "match_count": 5,
            "speaker_filter": "SPEAKER_01",
        },
    ).execute()
    assert [r["segment_id"] for r in filtered.data] == ["s2"]


def test_rpc_match_faces_and_missing_face_presence(client):
    def emb(x, y):
        return [x, y] + [0.0] * 510

    client.table("image_embeddings").insert(
        {
            "video_hash": "hash1",
            "segment_id": "s1",
            "start_time": 0.0,
            "end_time": 1.0,
            "screenshot_url": "/static/s1.jpg",
            "embedding": emb(1, 0),
        }
    ).execute()
    client.table("image_embeddings").insert(
        {
            "video_hash": "hash2",
            "segment_id": "s1",
            "start_time": 0.0,
            "end_time": 1.0,
            "screenshot_url": "/static/s2.jpg",
            "embedding": emb(1, 0),
        }
    ).execute()

    missing = client.rpc("videos_missing_face_presence", {"batch_limit": 10}).execute()
    assert {r["video_hash"] for r in missing.data} == {"hash1", "hash2"}

    ie = client.table("image_embeddings").select("id").eq("video_hash", "hash1").single().execute()
    client.table("image_face_presence").insert(
        {
            "image_embedding_id": ie.data["id"],
            "video_hash": "hash1",
            "start_time": 0.0,
            "end_time": 1.0,
            "face_embedding": emb(1, 0),
            "det_score": 0.9,
        }
    ).execute()

    missing = client.rpc("videos_missing_face_presence", {"batch_limit": 10}).execute()
    assert {r["video_hash"] for r in missing.data} == {"hash2"}

    matches = client.rpc(
        "match_faces_by_embedding",
        {
            "target_video_hash": "hash1",
            "query_embedding": emb(0.9, 0.1),
            "similarity_threshold": 0.5,
        },
    ).execute()
    assert len(matches.data) == 1
    assert matches.data[0]["image_embedding_id"] == ie.data["id"]

    none = client.rpc(
        "match_faces_by_embedding",
        {
            "target_video_hash": "hash1",
            "query_embedding": emb(0, 1),
            "similarity_threshold": 0.5,
        },
    ).execute()
    assert none.data == []


def test_rpc_get_vault_secret(client):
    resp = client.rpc("get_vault_secret", {"secret_name_input": "api_key_encryption"}).execute()
    key = resp.data[0]["secret"]
    assert len(bytes.fromhex(key)) == 32
    # stable across calls
    assert client.rpc("get_vault_secret", {}).execute().data[0]["secret"] == key


def test_gte_string_date_comparison(client):
    client.table("usage_logs").insert(
        {"user_id": LOCAL_USER_ID, "action": "upload", "metadata": {"file_size": 5}}
    ).execute()
    today = __import__("datetime").datetime.now(
        __import__("datetime").timezone.utc
    ).date().isoformat()
    resp = (
        client.table("usage_logs")
        .select("id", count="exact")
        .eq("action", "upload")
        .gte("created_at", today)
        .execute()
    )
    assert resp.count == 1
