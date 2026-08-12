"""
Face tagging endpoints for manual face identification in screenshots.
Users tag faces with speaker names; embeddings are used to boost scene search.
"""

import asyncio
import json
import os
from urllib.parse import urlparse
from typing import Dict, List, Optional
from concurrent.futures import ThreadPoolExecutor
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from middleware.auth import require_auth
from services.supabase_service import supabase
from services.transcription_access import (
    authenticated_user_id,
)
from services.transcription_repository import transcription_repository
from services.media_storage import get_media_storage
from config import settings

# Executor for CPU/GPU-bound face detection (InsightFace uses ONNX, separate from PyTorch)
_face_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="face_detect")


async def _run_in_executor(func, *args, **kwargs):
    loop = asyncio.get_event_loop()
    if kwargs:
        return await loop.run_in_executor(_face_executor, lambda: func(*args, **kwargs))
    return await loop.run_in_executor(_face_executor, func, *args)


router = APIRouter(prefix="/api/face-tags", tags=["Face Tagging"])


class TagFaceRequest(BaseModel):
    screenshot_url: str
    speaker_name: str
    bbox_x: float
    bbox_y: float
    bbox_w: float
    bbox_h: float


class DetectFacesRequest(BaseModel):
    screenshot_url: str


def _parse_embedding(value) -> Optional[List[float]]:
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else None
        except json.JSONDecodeError:
            return None
    return None


def _bbox_iou(first: Dict, second: Dict) -> float:
    ax1 = float(first.get("x") or 0)
    ay1 = float(first.get("y") or 0)
    ax2 = ax1 + float(first.get("w") or 0)
    ay2 = ay1 + float(first.get("h") or 0)
    bx1 = float(second.get("x") or 0)
    by1 = float(second.get("y") or 0)
    bx2 = bx1 + float(second.get("w") or 0)
    by2 = by1 + float(second.get("h") or 0)

    inter_w = max(0.0, min(ax2, bx2) - max(ax1, bx1))
    inter_h = max(0.0, min(ay2, by2) - max(ay1, by1))
    intersection = inter_w * inter_h
    area_a = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
    area_b = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
    union = area_a + area_b - intersection
    return intersection / union if union > 0 else 0.0


def _owned_screenshot_source(request: Request, video_hash: str, requested: str) -> str:
    """Materialize a screenshot only after owner and transcript validation."""
    user_id = authenticated_user_id(request)
    transcription = transcription_repository.get_transcription(video_hash, user_id)
    if not transcription:
        raise HTTPException(status_code=404, detail="Transcription not found")

    segments = transcription.get("transcription", {}).get("segments", [])
    allowed_urls = {segment.get("screenshot_url") for segment in segments if segment.get("screenshot_url")}
    parsed_requested = urlparse(requested)
    local_host = urlparse(settings.LOCAL_API_BASE_URL).hostname
    if (
        requested not in allowed_urls
        and parsed_requested.scheme
        and parsed_requested.hostname not in {"storage.googleapis.com", local_host}
    ):
        raise HTTPException(status_code=400, detail="Screenshot is not owned by this video")
    storage = get_media_storage()
    requested_key = storage.parse_screenshot_key(requested)
    allowed_keys = {
        key for url in allowed_urls if (key := storage.parse_screenshot_key(url))
    }
    allow_legacy = transcription_repository.hash_resources_are_owner_exclusive(video_hash, user_id)
    if (
        requested_key
        and requested_key in allowed_keys
        and storage.is_owned_screenshot_key(
            requested_key, user_id, video_hash, allow_legacy=allow_legacy
        )
    ):
        try:
            return storage.materialize_screenshot(
                requested_key,
                user_id,
                video_hash,
                allow_legacy=allow_legacy,
            )
        except (OSError, ValueError):
            raise HTTPException(status_code=404, detail="Screenshot media not found")

    raise HTTPException(status_code=400, detail="Screenshot is not owned by this video")


@router.post(
    "/{video_hash}/detect",
    summary="Detect faces in a screenshot",
    description="Runs face detection on a screenshot and returns bounding boxes",
)
@require_auth
async def detect_faces(request: Request, video_hash: str, body: DetectFacesRequest) -> Dict:
    """Detect faces in a screenshot, return bounding boxes with confidence scores"""
    from services.face_service import face_service
    user_id = authenticated_user_id(request)

    image_source = _owned_screenshot_source(request, video_hash, body.screenshot_url)
    try:
        faces = await _run_in_executor(face_service.detect_faces, image_source)
    finally:
        try:
            os.unlink(image_source)
        except OSError:
            pass
    existing_tags = []

    try:
        client = supabase()
        result = client.table("face_tags").select(
            "id,speaker_name,screenshot_url,bbox_x,bbox_y,bbox_w,bbox_h,embedding"
        ).eq("user_id", user_id).eq("video_hash", video_hash).execute()
        existing_tags = result.data or []
    except Exception as e:
        print(f"[FaceTags] Warning: could not load existing tags for detection labels: {e}")

    annotated_faces = []
    for face in faces:
        face_embedding = face.get("embedding")
        best_exact = None
        best_exact_iou = 0.0
        best_similarity = 0.0
        best_similarity_tag = None

        for tag in existing_tags:
            tag_bbox = {
                "x": tag.get("bbox_x"),
                "y": tag.get("bbox_y"),
                "w": tag.get("bbox_w"),
                "h": tag.get("bbox_h"),
            }

            if tag.get("screenshot_url") == body.screenshot_url:
                overlap = _bbox_iou(face["bbox"], tag_bbox)
                if overlap > best_exact_iou:
                    best_exact_iou = overlap
                    best_exact = tag

            tag_embedding = _parse_embedding(tag.get("embedding"))
            if face_embedding and tag_embedding:
                similarity = face_service.compute_face_similarity(face_embedding, tag_embedding)
                if similarity > best_similarity:
                    best_similarity = similarity
                    best_similarity_tag = tag

        matched_tag = best_exact if best_exact_iou >= 0.6 else None
        already_tagged = matched_tag is not None

        if matched_tag is None and best_similarity_tag is not None and best_similarity >= 0.45:
            matched_tag = best_similarity_tag

        annotated_face = {
            "bbox": face["bbox"],
            "confidence": face["confidence"],
        }
        if matched_tag:
            annotated_face.update({
                "speaker_name": matched_tag.get("speaker_name"),
                "match_confidence": 1.0 if already_tagged else best_similarity,
                "already_tagged": already_tagged,
                "face_tag_id": matched_tag.get("id"),
            })
        annotated_faces.append(annotated_face)

    return {
        "video_hash": video_hash,
        "screenshot_url": body.screenshot_url,
        "faces": annotated_faces,
        "count": len(faces),
    }


@router.post(
    "/{video_hash}/tag",
    summary="Tag a face with a speaker name",
    description="Store a face embedding tagged with a speaker name for scene search boosting",
)
@require_auth
async def tag_face(request: Request, video_hash: str, body: TagFaceRequest) -> Dict:
    """Tag a detected face bbox with a speaker name, storing the face embedding"""
    from services.face_service import face_service
    user_id = authenticated_user_id(request)

    image_source = _owned_screenshot_source(request, video_hash, body.screenshot_url)
    # Get face embedding for the specified bbox
    bbox = (body.bbox_x, body.bbox_y, body.bbox_w, body.bbox_h)
    try:
        embedding = await _run_in_executor(
            face_service.get_face_embedding, image_source, bbox
        )
    finally:
        try:
            os.unlink(image_source)
        except OSError:
            pass

    if embedding is None:
        raise HTTPException(
            status_code=400,
            detail="Could not extract face embedding for the specified region"
        )

    # Store in Supabase
    client = supabase()
    record = {
        "user_id": user_id,
        "video_hash": video_hash,
        "speaker_name": body.speaker_name,
        "screenshot_url": body.screenshot_url,
        "bbox_x": body.bbox_x,
        "bbox_y": body.bbox_y,
        "bbox_w": body.bbox_w,
        "bbox_h": body.bbox_h,
        "embedding": embedding,
    }

    try:
        result = client.table("face_tags").upsert(
            record,
            on_conflict="user_id,video_hash,screenshot_url,bbox_x,bbox_y"
        ).execute()

        tag_id = result.data[0]["id"] if result.data else None

        return {
            "success": True,
            "face_tag_id": tag_id,
            "speaker_name": body.speaker_name,
            "video_hash": video_hash,
        }
    except Exception as e:
        print(f"[FaceTags] Error storing face tag: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to store face tag: {e}")


@router.get(
    "/{video_hash}/speakers",
    summary="Get face tag counts per speaker",
    description="Returns how many face tags exist for each speaker in a video",
)
@require_auth
async def get_speakers(request: Request, video_hash: str) -> Dict:
    """Get face tag counts grouped by speaker name"""
    user_id = authenticated_user_id(request)
    if not transcription_repository.get_transcription(video_hash, user_id):
        raise HTTPException(status_code=404, detail="Transcription not found")
    client = supabase()

    try:
        result = client.table("face_tags").select(
            "speaker_name"
        ).eq("user_id", user_id).eq("video_hash", video_hash).execute()

        # Count per speaker
        counts: Dict[str, int] = {}
        for row in result.data:
            name = row["speaker_name"]
            counts[name] = counts.get(name, 0) + 1

        return {
            "video_hash": video_hash,
            "speakers": [
                {"speaker_name": name, "count": count}
                for name, count in sorted(counts.items())
            ],
            "total": sum(counts.values()),
        }
    except Exception as e:
        print(f"[FaceTags] Error getting speakers: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete(
    "/{video_hash}/{face_tag_id}",
    summary="Delete a face tag",
    description="Remove a specific face tag",
)
@require_auth
async def delete_face_tag(request: Request, video_hash: str, face_tag_id: str) -> Dict:
    """Remove a face tag"""
    user_id = authenticated_user_id(request)
    if not transcription_repository.get_transcription(video_hash, user_id):
        raise HTTPException(status_code=404, detail="Transcription not found")
    client = supabase()

    try:
        client.table("face_tags").delete().eq(
            "id", face_tag_id
        ).eq("user_id", user_id).eq("video_hash", video_hash).execute()

        return {
            "success": True,
            "message": f"Deleted face tag {face_tag_id}",
        }
    except Exception as e:
        print(f"[FaceTags] Error deleting face tag: {e}")
        raise HTTPException(status_code=500, detail=str(e))
