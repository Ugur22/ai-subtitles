"""
Face Detection and Embedding Service using InsightFace (buffalo_l)
Handles face detection (RetinaFace) and embedding (ArcFace, 512-dim)
Uses ONNX Runtime — separate from PyTorch GPU memory
"""

import os
import tempfile
import numpy as np
import requests
from typing import List, Dict, Optional, Tuple
from PIL import Image


class FaceService:
    """Service for face detection and embedding using InsightFace"""

    def __init__(self):
        self._model = None

    @property
    def model(self):
        """Lazy-load InsightFace buffalo_l model"""
        if self._model is None:
            print("[FaceService] Loading InsightFace buffalo_l model...")
            import insightface
            from insightface.app import FaceAnalysis

            self._model = FaceAnalysis(
                name='buffalo_l',
                providers=['CUDAExecutionProvider', 'CPUExecutionProvider']
            )
            # det_size controls detection resolution — 640x640 is default/good balance
            self._model.prepare(ctx_id=0, det_size=(640, 640))
            print("[FaceService] InsightFace model loaded successfully")
        return self._model

    def _download_image_to_temp(self, url: str) -> Optional[str]:
        """Download an image from URL to a temporary file"""
        if not url.startswith('http://') and not url.startswith('https://'):
            if os.path.exists(url):
                return url
            if url.startswith('/static/'):
                from pathlib import Path
                backend_dir = Path(__file__).parent.parent.absolute()
                abs_path = str(backend_dir / url.lstrip('/'))
                if os.path.exists(abs_path):
                    return abs_path
            return None

        try:
            response = requests.get(url, timeout=30)
            response.raise_for_status()

            suffix = '.jpg'
            if '.png' in url.lower():
                suffix = '.png'
            elif '.webp' in url.lower():
                suffix = '.webp'

            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                tmp.write(response.content)
                return tmp.name
        except Exception as e:
            print(f"[FaceService] Failed to download image from {url}: {e}")
            return None

    def detect_faces(self, image_source: str) -> List[Dict]:
        """
        Detect faces in an image.

        Args:
            image_source: URL or local path to image

        Returns:
            List of dicts with keys: bbox (x,y,w,h normalized 0-1),
            embedding (512-dim list), confidence (float)
        """
        temp_path = None
        try:
            # Download if URL
            local_path = self._download_image_to_temp(image_source)
            if not local_path:
                print(f"[FaceService] Could not access image: {image_source}")
                return []

            if local_path != image_source and local_path.startswith(tempfile.gettempdir()):
                temp_path = local_path

            # Load image as numpy array (InsightFace expects BGR)
            import cv2
            img = cv2.imread(local_path)
            if img is None:
                print(f"[FaceService] Failed to read image: {local_path}")
                return []

            h, w = img.shape[:2]

            # Detect faces
            faces = self.model.get(img)

            results = []
            for face in faces:
                bbox = face.bbox  # [x1, y1, x2, y2] in pixels
                embedding = face.embedding  # 512-dim numpy array

                if embedding is None:
                    continue

                # Normalize bbox to 0-1 range
                x1, y1, x2, y2 = bbox
                results.append({
                    'bbox': {
                        'x': float(x1 / w),
                        'y': float(y1 / h),
                        'w': float((x2 - x1) / w),
                        'h': float((y2 - y1) / h),
                    },
                    'embedding': embedding.tolist(),
                    'confidence': float(face.det_score),
                })

            print(f"[FaceService] Detected {len(results)} faces in image")
            return results

        except Exception as e:
            print(f"[FaceService] Face detection error: {e}")
            import traceback
            traceback.print_exc()
            return []
        finally:
            if temp_path:
                try:
                    os.unlink(temp_path)
                except:
                    pass

    def get_face_embedding(self, image_source: str, bbox: Tuple[float, float, float, float]) -> Optional[List[float]]:
        """
        Get face embedding for a specific bounding box region.

        Args:
            image_source: URL or local path to image
            bbox: (x, y, w, h) normalized 0-1

        Returns:
            512-dim embedding as list of floats, or None
        """
        temp_path = None
        try:
            local_path = self._download_image_to_temp(image_source)
            if not local_path:
                return None

            if local_path != image_source and local_path.startswith(tempfile.gettempdir()):
                temp_path = local_path

            import cv2
            img = cv2.imread(local_path)
            if img is None:
                return None

            h_img, w_img = img.shape[:2]

            # Convert normalized bbox to pixel coordinates
            bx, by, bw, bh = bbox
            x1 = int(bx * w_img)
            y1 = int(by * h_img)
            x2 = int((bx + bw) * w_img)
            y2 = int((by + bh) * h_img)

            # Crop face region with some padding
            pad = int(max(bw * w_img, bh * h_img) * 0.1)
            x1 = max(0, x1 - pad)
            y1 = max(0, y1 - pad)
            x2 = min(w_img, x2 + pad)
            y2 = min(h_img, y2 + pad)

            face_crop = img[y1:y2, x1:x2]

            # Run detection on the cropped region
            faces = self.model.get(face_crop)
            if not faces:
                # Fallback: run on full image and find closest face to bbox
                faces = self.model.get(img)
                if not faces:
                    return None

                # Find the face closest to the specified bbox center
                target_cx = (bx + bw / 2) * w_img
                target_cy = (by + bh / 2) * h_img

                best_face = None
                best_dist = float('inf')
                for face in faces:
                    fx1, fy1, fx2, fy2 = face.bbox
                    fcx = (fx1 + fx2) / 2
                    fcy = (fy1 + fy2) / 2
                    dist = ((fcx - target_cx) ** 2 + (fcy - target_cy) ** 2) ** 0.5
                    if dist < best_dist:
                        best_dist = dist
                        best_face = face

                if best_face and best_face.embedding is not None:
                    return best_face.embedding.tolist()
                return None

            # Use the largest/most confident face in the crop
            best = max(faces, key=lambda f: f.det_score)
            if best.embedding is not None:
                return best.embedding.tolist()
            return None

        except Exception as e:
            print(f"[FaceService] get_face_embedding error: {e}")
            return None
        finally:
            if temp_path:
                try:
                    os.unlink(temp_path)
                except:
                    pass

    @staticmethod
    def compute_face_similarity(emb1: List[float], emb2: List[float]) -> float:
        """Compute cosine similarity between two face embeddings"""
        a = np.array(emb1)
        b = np.array(emb2)
        norm_a = np.linalg.norm(a)
        norm_b = np.linalg.norm(b)
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return float(np.dot(a, b) / (norm_a * norm_b))


# Global instance
face_service = FaceService()
