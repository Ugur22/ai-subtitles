"""Loads and merges the frames where a person appears."""
from typing import Any, Optional
from services.chat.context import _chat_user_id, _run_in_executor, get_transcription_from_any_source
from services.chat.visual_refs import _cosine_similarity, _load_speaker_reference_embedding, _owner_scoped_screenshot_url, _parse_vector, _timestamp_from_screenshot_url


def _video_duration_seconds(video_hash: str, appearances: list[dict]) -> float:
    transcription = get_transcription_from_any_source(video_hash)
    segments = (transcription or {}).get("transcription", {}).get("segments", [])
    duration = 0.0
    for segment in segments:
        try:
            duration = max(duration, float(segment.get("end") or segment.get("start") or 0))
        except Exception:
            continue
    for appearance in appearances:
        duration = max(duration, float(appearance.get("end_time") or appearance.get("start_time") or 0))
    return max(duration, 1.0)


def _chunks(values: list[Any], size: int) -> list[list[Any]]:
    return [values[i:i + size] for i in range(0, len(values), size)]


async def _load_comparison_presence_rows(
    client,
    user_id: str,
    video_hash: str,
    image_ids: list[str],
) -> tuple[list[dict], list[dict]]:
    """
    Load face/image rows for comparison matches in small batches.
    Keep batches small: each face row carries a large embedding, and Supabase/Cloudflare
    can reject or terminate larger PostgREST responses.
    """
    face_rows: list[dict] = []
    image_rows: list[dict] = []
    for batch in _chunks(image_ids, 8):
        try:
            image_response = await _run_in_executor(
                lambda ids=batch: client.table("image_embeddings")
                .select("id,start_time,end_time,speaker,screenshot_url,embedding")
                .eq("user_id", user_id)
                .eq("video_hash", video_hash)
                .in_("id", ids)
                .execute()
            )
            image_rows.extend(image_response.data or [])
        except Exception as e:
            print(f"[Chat] Face comparison image batch skipped ({len(batch)} ids): {e}")
            continue

        try:
            face_response = await _run_in_executor(
                lambda ids=batch: client.table("image_face_presence")
                .select("image_embedding_id,face_embedding,bbox,start_time,end_time")
                .eq("user_id", user_id)
                .eq("video_hash", video_hash)
                .in_("image_embedding_id", ids)
                .execute()
            )
            face_rows.extend(face_response.data or [])
        except Exception as e:
            print(f"[Chat] Face comparison face batch skipped ({len(batch)} ids): {e}")
    return face_rows, image_rows


async def _load_person_appearances(
    video_hash: str,
    person_name: str,
    *,
    threshold: Optional[float] = None,
) -> list[dict]:
    """Find indexed face appearances for a manually tagged person.

    `threshold` gates which faces qualify (cosine similarity). Defaults to the
    relaxed comparison threshold so faint faces (dim/profile/distant scenes)
    still surface; pass an explicit value to override.
    """
    from config import settings
    from services.supabase_service import supabase as get_supabase

    if threshold is None:
        threshold = settings.FACE_PRESENCE_COMPARISON_THRESHOLD
    user_id = _chat_user_id.get()
    if not user_id:
        return []

    reference_embedding = _load_speaker_reference_embedding(video_hash, person_name)
    if not reference_embedding:
        return []

    client = get_supabase()
    response = await _run_in_executor(
        lambda: client.rpc(
            "match_faces_by_embedding",
            {
                "p_user_id": user_id,
                "target_video_hash": video_hash,
                "query_embedding": reference_embedding,
                "similarity_threshold": threshold,
                "match_limit": 500,
            },
        ).execute()
    )
    matches = response.data or []
    image_ids = list(dict.fromkeys(
        str(row.get("image_embedding_id"))
        for row in matches
        if row.get("image_embedding_id")
    ))
    if not image_ids:
        return []

    try:
        face_rows, image_rows = await _load_comparison_presence_rows(
            client,
            user_id,
            video_hash,
            image_ids,
        )
    except Exception as e:
        print(
            f"[Chat] Face comparison presence row lookup failed for "
            f"'{person_name}' ({len(image_ids)} ids): {e}"
        )
        return []

    match_similarity = {
        str(row.get("image_embedding_id")): float(row.get("similarity") or 0.0)
        for row in matches
    }
    images_by_id = {
        str(row.get("id")): row
        for row in image_rows
        if row.get("id")
    }

    best_faces: dict[str, dict] = {}
    for row in face_rows:
        image_id = str(row.get("image_embedding_id") or "")
        face_embedding = _parse_vector(row.get("face_embedding"))
        if not image_id:
            continue
        similarity = (
            _cosine_similarity(reference_embedding, face_embedding)
            if face_embedding
            else match_similarity.get(image_id, 0.0)
        )
        if similarity < threshold:
            continue
        current = best_faces.get(image_id)
        if current is None or similarity > current["similarity"]:
            best_faces[image_id] = {
                "face_embedding": face_embedding,
                "bbox": row.get("bbox"),
                "similarity": similarity,
                "start_time": float(row.get("start_time") or 0.0),
                "end_time": float(row.get("end_time") or row.get("start_time") or 0.0),
            }

    appearances = []
    for image_id, face in best_faces.items():
        image = images_by_id.get(image_id)
        if not image:
            continue
        scene_embedding = _parse_vector(image.get("embedding"))
        screenshot_url = image.get("screenshot_url")
        if not screenshot_url:
            continue
        owned_url = _owner_scoped_screenshot_url(screenshot_url, video_hash)
        if not owned_url:
            continue
        start = float(image.get("start_time") or face["start_time"])
        end = float(image.get("end_time") or face["end_time"] or start)
        similarity = max(face["similarity"], match_similarity.get(image_id, 0.0))
        appearances.append({
            "image_embedding_id": image_id,
            "start_time": start,
            "end_time": end,
            "speaker": image.get("speaker") or person_name,
            "screenshot_url": owned_url,
            "bbox": face.get("bbox"),
            "face_embedding": face["face_embedding"],
            "scene_embedding": scene_embedding,
            "similarity": similarity,
            # Faint match: surfaced only because of the relaxed comparison
            # threshold. Below the global 0.5 confidence bar -> badge in the UI.
            "low_confidence": similarity < settings.FACE_PRESENCE_SIMILARITY_THRESHOLD,
        })

    appearances.sort(key=lambda row: row.get("similarity", 0.0), reverse=True)

    # Guardrail: keep all confident frames (>= global threshold) plus at most the
    # top N faint frames, so relaxing the gate widens the pool without flooding
    # the timeline strip with low-similarity noise.
    confident = [a for a in appearances if not a.get("low_confidence")]
    faint = [a for a in appearances if a.get("low_confidence")]
    FAINT_FRAME_CAP = 15
    appearances = confident + faint[:FAINT_FRAME_CAP]

    if len(appearances) < 2:
        print(
            f"[Chat] Face comparison presence matches for '{person_name}' yielded "
            f"{len(appearances)} usable appearances; falling back to manual face tags"
        )
        appearances = _merge_comparison_appearances(
            appearances,
            _load_face_tag_appearances(video_hash, person_name, reference_embedding),
        )
    return appearances


async def _load_person_appearances_with_fallback(video_hash: str, person_name: str) -> list[dict]:
    """Load automatic face-presence appearances, then merge manual tags as a fallback."""
    appearances = await _load_person_appearances(video_hash, person_name)
    reference_embedding = _load_speaker_reference_embedding(video_hash, person_name)
    tagged_appearances = (
        _load_face_tag_appearances(video_hash, person_name, reference_embedding)
        if reference_embedding
        else []
    )
    return _merge_comparison_appearances(appearances, tagged_appearances)


def _comparison_appearance_key(appearance: dict) -> str:
    url = appearance.get("screenshot_url") or ""
    try:
        from services.gcs_service import gcs_service
        return gcs_service.extract_gcs_path_from_signed_url(url) or url.split("?", 1)[0]
    except Exception:
        return url.split("?", 1)[0]


def _merge_comparison_appearances(primary: list[dict], fallback: list[dict]) -> list[dict]:
    merged = []
    seen = set()
    for appearance in [*primary, *fallback]:
        key = _comparison_appearance_key(appearance)
        if not key or key in seen:
            continue
        seen.add(key)
        merged.append(appearance)
    merged.sort(key=lambda row: row.get("similarity", 0.0), reverse=True)
    return merged


def _load_face_tag_appearances(
    video_hash: str,
    person_name: str,
    reference_embedding: Optional[list[float]],
) -> list[dict]:
    """Fallback appearances from manually tagged screenshots."""
    try:
        from services.supabase_service import supabase as get_supabase
        user_id = _chat_user_id.get()
        if not user_id:
            return []

        client = get_supabase()
        result = (
            client.table("face_tags")
            .select("screenshot_url,bbox_x,bbox_y,bbox_w,bbox_h,embedding")
            .eq("user_id", user_id)
            .eq("video_hash", video_hash)
            .eq("speaker_name", person_name)
            .execute()
        )
        appearances = []
        for idx, row in enumerate(result.data or []):
            screenshot_url = row.get("screenshot_url")
            if not screenshot_url:
                continue
            owned_url = _owner_scoped_screenshot_url(screenshot_url, video_hash)
            if not owned_url:
                continue
            face_embedding = _parse_vector(row.get("embedding"))
            start = _timestamp_from_screenshot_url(screenshot_url)
            bbox = None
            if all(row.get(key) is not None for key in ("bbox_x", "bbox_y", "bbox_w", "bbox_h")):
                bbox = {
                    "x": float(row.get("bbox_x")),
                    "y": float(row.get("bbox_y")),
                    "w": float(row.get("bbox_w")),
                    "h": float(row.get("bbox_h")),
                }
            appearances.append({
                "image_embedding_id": f"face_tag_{idx}",
                "start_time": start,
                "end_time": start + 1.0,
                "speaker": person_name,
                "screenshot_url": owned_url,
                "bbox": bbox,
                "face_embedding": face_embedding,
                "scene_embedding": None,
                "similarity": (
                    _cosine_similarity(reference_embedding, face_embedding)
                    if reference_embedding and face_embedding
                    else 1.0
                ),
            })
        appearances.sort(key=lambda row: row.get("similarity", 0.0), reverse=True)
        return appearances
    except Exception as e:
        print(f"[Chat] Face-tag comparison fallback failed: {e}")
        return []
