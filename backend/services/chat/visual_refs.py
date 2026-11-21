"""Owner-scoped screenshot URLs and face/speaker embedding lookups."""
import json
from typing import Any, Optional
from services.chat.context import _chat_user_id


def _timestamp_from_screenshot_url(url: str) -> float:
    """Extract screenshot timestamp from .../<seconds>.jpg URLs."""
    try:
        import os
        path = url.split("?", 1)[0]
        filename = os.path.basename(path)
        stem = filename.rsplit(".", 1)[0]
        return float(stem)
    except Exception:
        return 0.0


def _owner_scoped_screenshot_url(reference: str, video_hash: str) -> Optional[str]:
    """Resolve an owned screenshot through the configured media storage."""
    user_id = _chat_user_id.get()
    if not user_id or not reference:
        return None
    try:
        from services.media_storage import get_media_storage

        storage = get_media_storage()
        object_key = storage.parse_screenshot_key(reference)
        if not object_key or not storage.is_owned_screenshot_key(
            object_key, user_id, video_hash
        ):
            return None
        return storage.generate_download_url(object_key)
    except Exception as e:
        print(f"[Chat] Owner-scoped screenshot resolution failed: {e}")
        return None


def _robust_mean_embedding(embeddings: list, min_sim: float) -> tuple[Any, int]:
    """Normalized mean of tag embeddings, ignoring tags far from the centroid.

    One wrong-person tag skews a plain average enough to make every later face
    match drift, so tags below `min_sim` cosine to the centroid are dropped.
    Needs >=4 tags to judge outliers and never drops more than half of them.
    Returns (mean, ignored_count).
    """
    import numpy as np

    unit = []
    for e in embeddings:
        e = np.asarray(e, dtype=np.float32)
        n = np.linalg.norm(e)
        if n > 0:
            unit.append(e / n)
    if not unit:
        return None, 0

    def _mean(vectors):
        m = np.mean(vectors, axis=0)
        n = np.linalg.norm(m)
        return m / n if n > 0 else m

    centroid = _mean(unit)
    ignored = 0
    if len(unit) >= 4:
        sims = [float(v @ centroid) for v in unit]
        keep = [v for v, s in zip(unit, sims) if s >= min_sim]
        if len(keep) >= len(unit) - len(unit) // 2:
            ignored = len(unit) - len(keep)
            if ignored:
                centroid = _mean(keep)
    return centroid, ignored


def _load_speaker_reference_embedding(video_hash: str, speaker_name: str) -> Optional[list[float]]:
    """Load the normalized average manual face-tag embedding for one person."""
    try:
        import numpy as np
        import json as _json
        from services.supabase_service import supabase as get_supabase
        user_id = _chat_user_id.get()
        if not user_id:
            return None

        face_client = get_supabase()
        face_result = face_client.table("face_tags").select(
            "embedding"
        ).eq("user_id", user_id).eq("video_hash", video_hash).eq(
            "speaker_name", speaker_name
        ).execute()
        if not face_result.data:
            return None

        raw_embeddings = []
        for row in face_result.data:
            emb = row.get("embedding")
            if not emb:
                continue
            if isinstance(emb, str):
                emb = _json.loads(emb)
            raw_embeddings.append(emb)
        if not raw_embeddings:
            return None

        from config import settings
        avg_emb, ignored = _robust_mean_embedding(
            raw_embeddings, settings.FACE_TAG_OUTLIER_MIN_SIMILARITY
        )
        if avg_emb is None:
            return None
        print(
            f"  Face tags for '{speaker_name}': {len(raw_embeddings)} embeddings loaded"
            + (f", ignored {ignored} outliers" if ignored else "")
        )
        return avg_emb.tolist()
    except Exception as e:
        print(f"  Face tags lookup failed (non-critical): {e}")
        return None


def _load_speaker_face_embeddings(video_hash: str, speaker_names: list[str]) -> dict[str, list[float]]:
    """Load averaged manual face-tag embeddings for named speakers."""
    speaker_face_embeddings: dict[str, list[float]] = {}
    if not speaker_names:
        return speaker_face_embeddings

    for name in speaker_names:
        embedding = _load_speaker_reference_embedding(video_hash, name)
        if embedding:
            speaker_face_embeddings[name] = embedding

    return speaker_face_embeddings


def _parse_vector(value: Any) -> Optional[list[float]]:
    """Parse pgvector/list values returned by Supabase into a float list."""
    if value is None:
        return None
    if isinstance(value, list):
        return [float(v) for v in value]
    if isinstance(value, str):
        text = value.strip()
        if text.startswith("[") and text.endswith("]"):
            return [float(v) for v in text.strip("[]").split(",") if v.strip()]
        try:
            parsed = json.loads(text)
            if isinstance(parsed, list):
                return [float(v) for v in parsed]
        except Exception:
            return None
    return None


def _cosine_similarity(a: Any, b: Any) -> float:
    import numpy as np

    va = np.array(a, dtype=np.float32)
    vb = np.array(b, dtype=np.float32)
    denom = float(np.linalg.norm(va) * np.linalg.norm(vb))
    if denom <= 0:
        return 0.0
    return float(np.dot(va, vb) / denom)
