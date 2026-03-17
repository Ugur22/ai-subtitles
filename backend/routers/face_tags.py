"""
Face tagging endpoints for manual face identification in screenshots.
Users tag faces with speaker names; embeddings are used to boost scene search.
"""

import asyncio
from typing import Dict, List
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

    return {
        "video_hash": video_hash,
        "screenshot_url": body.screenshot_url,
        "faces": [
            {
                "bbox": face["bbox"],
                "confidence": face["confidence"],
            }
            for face in faces
        ],
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
