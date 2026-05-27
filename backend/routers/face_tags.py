"""
Face tagging endpoints for manual face identification in screenshots.
Users tag faces with speaker names; embeddings are used to boost scene search.
"""

import asyncio
import json
from typing import Dict, List, Optional
from concurrent.futures import ThreadPoolExecutor
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from middleware.auth import require_auth
from services.supabase_service import supabase

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


@router.post(
    "/{video_hash}/detect",
    summary="Detect faces in a screenshot",
    description="Runs face detection on a screenshot and returns bounding boxes",
)
@require_auth
async def detect_faces(request: Request, video_hash: str, body: DetectFacesRequest) -> Dict:
    """Detect faces in a screenshot, return bounding boxes with confidence scores"""
    from services.face_service import face_service

    faces = await _run_in_executor(face_service.detect_faces, body.screenshot_url)
    existing_tags = []

    try:
        client = supabase()
        result = client.table("face_tags").select(
            "id,speaker_name,screenshot_url,bbox_x,bbox_y,bbox_w,bbox_h,embedding"
        ).eq("video_hash", video_hash).execute()
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

    # Get face embedding for the specified bbox
    bbox = (body.bbox_x, body.bbox_y, body.bbox_w, body.bbox_h)
    embedding = await _run_in_executor(
        face_service.get_face_embedding, body.screenshot_url, bbox
    )

    if embedding is None:
        raise HTTPException(
            status_code=400,
            detail="Could not extract face embedding for the specified region"
        )

    # Store in Supabase
    client = supabase()
    record = {
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
            on_conflict="video_hash,screenshot_url,bbox_x,bbox_y"
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
    client = supabase()

    try:
        result = client.table("face_tags").select(
            "speaker_name"
        ).eq("video_hash", video_hash).execute()

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
    client = supabase()

    try:
        client.table("face_tags").delete().eq(
            "id", face_tag_id
        ).eq("video_hash", video_hash).execute()

        return {
            "success": True,
            "message": f"Deleted face tag {face_tag_id}",
        }
    except Exception as e:
        print(f"[FaceTags] Error deleting face tag: {e}")
        raise HTTPException(status_code=500, detail=str(e))
