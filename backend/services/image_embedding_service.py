"""
Image Embedding Service using Supabase pgvector
Handles persistent storage of CLIP embeddings for video screenshots
"""

import asyncio
import os
import re
import tempfile
import time
import httpx
import requests
from typing import Callable, List, Dict, Optional
from PIL import Image
from sentence_transformers import SentenceTransformer
from services.supabase_service import supabase
from services.media_storage import get_media_storage
from config import settings

_REFUSAL_PATTERN = re.compile(
    r"(?i)\b(i can'?t|i cannot|i'?m sorry|i am sorry|i won'?t|"
    r"unable to (assist|help|describe|provide)|"
    r"against (my|our|the).{0,20}(policy|guidelines)|"
    r"not able to (help|assist|describe)|as an ai)\b"
)


def _looks_like_refusal(text: Optional[str]) -> bool:
    """Vision-model refusals must be stored as NULL, not indexed as captions."""
    if not text or not text.strip():
        return True
    return bool(_REFUSAL_PATTERN.search(text[:120]))


def _split_caption_sentences(caption: str) -> List[str]:
    """Sentences of a caption, for per-sentence retrieval scoring. Whole-caption
    embeddings dilute the action with scene details, so search scores against
    individual sentences and takes the per-image max."""
    parts = re.split(r'(?<=[.!?])\s+', caption.strip())
    return [p.strip() for p in parts if len(p.strip()) >= 15]


class ImageEmbeddingService:
    """Service for storing and searching image embeddings in Supabase"""

    def __init__(self):
        """Initialize the image embedding service"""
        self._clip_model = None
        self._caption_embedding_model = None

    @property
    def clip_model(self) -> SentenceTransformer:
        """
        Lazy load CLIP model for image embeddings

        Returns:
            CLIP model from sentence-transformers
        """
        if self._clip_model is None:
            print(f"[ImageEmbedding] Loading CLIP model ({settings.CLIP_MODEL})...")
            self._clip_model = SentenceTransformer(settings.CLIP_MODEL)
            print("[ImageEmbedding] CLIP model loaded successfully")
        return self._clip_model

    @property
    def caption_embedding_model(self) -> SentenceTransformer:
        """Lazy load all-MiniLM model for caption text embeddings."""
        if self._caption_embedding_model is None:
            print("[ImageEmbedding] Loading caption embedding model (all-MiniLM-L6-v2)...")
            self._caption_embedding_model = SentenceTransformer('all-MiniLM-L6-v2')
            print("[ImageEmbedding] Caption embedding model loaded successfully")
        return self._caption_embedding_model

    def _download_image_to_temp(self, url: str) -> Optional[str]:
        """
        Download an image from URL to a temporary file

        Args:
            url: URL of the image (can be GCS signed URL or local path)

        Returns:
            Path to temporary file, or None if download failed
        """
        # If it's a local file path, just return it
        if not url.startswith('http://') and not url.startswith('https://'):
            if os.path.exists(url):
                return url
            # Try converting /static/ path to absolute
            if url.startswith('/static/'):
                from pathlib import Path
                backend_dir = Path(__file__).parent.parent.absolute()
                abs_path = str(backend_dir / url.lstrip('/'))
                if os.path.exists(abs_path):
                    return abs_path
                # Fallback: try GCS using predictable path screenshots/{hash}/{ts}.jpg
                if url.startswith('/static/screenshots/'):
                    try:
                        from config import settings as _cfg
                        if _cfg.ENABLE_GCS_UPLOADS and not _cfg.LOCAL_MODE:
                            filename = os.path.basename(url)       # e.g. "abc123_1001.64.jpg"
                            stem = filename.rsplit('.', 1)[0]       # "abc123_1001.64"
                            last_us = stem.rfind('_')
                            if last_us > 0:
                                video_hash = stem[:last_us]
                                ts_str = stem[last_us + 1:]         # "1001.64"
                                gcs_path = f"screenshots/{video_hash}/{ts_str}.jpg"
                                from services.gcs_service import GCSService
                                bucket = GCSService._get_bucket()
                                blob = bucket.blob(gcs_path)
                                if blob.exists():
                                    tmp = tempfile.NamedTemporaryFile(delete=False, suffix='.jpg')
                                    tmp.close()
                                    blob.download_to_filename(tmp.name)
                                    return tmp.name
                    except Exception as gcs_e:
                        print(f"[ImageEmbedding] GCS fallback failed for {url}: {gcs_e}")
            return None

        try:
            # Download from URL
            response = requests.get(url, timeout=30)
            response.raise_for_status()

            # Create temp file with appropriate extension
            suffix = '.jpg'
            if '.png' in url.lower():
                suffix = '.png'
            elif '.webp' in url.lower():
                suffix = '.webp'

            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                tmp.write(response.content)
                return tmp.name

        except Exception as e:
            print(f"[ImageEmbedding] Failed to download image from {url}: {e}")
            return None

    def _download_gcs_path_to_temp(self, gcs_path: str) -> Optional[str]:
        """Download a GCS object directly with service-account credentials."""
        try:
            from config import settings as _cfg
            if _cfg.LOCAL_MODE:
                path = get_media_storage().download_to_temp(gcs_path)
                return path if path and os.path.exists(path) else None

            from services.gcs_service import GCSService

            suffix = os.path.splitext(gcs_path.split("?", 1)[0])[1] or ".jpg"
            bucket = GCSService._get_bucket()
            blob = bucket.blob(gcs_path)
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
            tmp.close()
            blob.download_to_filename(tmp.name)
            return tmp.name
        except Exception as e:
            print(f"[ImageEmbedding] Failed to download GCS object {gcs_path}: {e}")
            return None

    def _materialize_screenshot(
        self,
        reference: str,
        user_id: str,
        video_hash: str,
        allow_legacy: bool,
    ) -> str:
        return get_media_storage().materialize_screenshot(
            reference,
            user_id=user_id,
            video_hash=video_hash,
            allow_legacy=allow_legacy,
        )

    def _generate_embedding(self, image_path: str) -> Optional[List[float]]:
        """
        Generate CLIP embedding for a single image

        Args:
            image_path: Path to image file

        Returns:
            Embedding as list of floats, or None if failed
        """
        try:
            img = Image.open(image_path).convert('RGB')
            embedding = self.clip_model.encode(
                [img],
                convert_to_numpy=True
            ).tolist()[0]
            return embedding
        except Exception as e:
            print(f"[ImageEmbedding] Failed to generate embedding for {image_path}: {e}")
            return None

    def _upsert_with_retry(
        self,
        client,
        records: List[Dict],
        batch_num: int,
        total_batches: int,
        max_retries: int = 3,
    ) -> None:
        # Supabase sits behind Cloudflare which closes idle sockets after ~60s. httpx's
        # pooled connection can be dead by the time we write the next batch. Catch the
        # transport errors, force the pool to rebuild, and retry with backoff.
        last_err: Optional[Exception] = None
        for attempt in range(max_retries):
            try:
                client.table('image_embeddings').upsert(
                    records, on_conflict='user_id,video_hash,segment_id'
                ).execute()
                print(
                    f"[ImageEmbedding] Inserted batch {batch_num}/{total_batches} "
                    f"({len(records)} rows)"
                )
                return
            except (httpx.RemoteProtocolError, httpx.ConnectError, httpx.ReadError) as e:
                last_err = e
                try:
                    session = getattr(client.postgrest, 'session', None)
                    if session is not None:
                        session.close()
                except Exception:
                    pass
                backoff = 0.5 * (2 ** attempt)
                print(
                    f"[ImageEmbedding] Retry {attempt + 1}/{max_retries} for batch "
                    f"{batch_num} after {type(e).__name__}: {e}. Sleeping {backoff}s"
                )
                time.sleep(backoff)
        raise last_err if last_err else RuntimeError("batch upsert failed")

    def _insert_face_presence_with_retry(
        self,
        client,
        records: List[Dict],
        batch_num: int,
        total_batches: int,
        max_retries: int = 3,
    ) -> None:
        last_err: Optional[Exception] = None
        for attempt in range(max_retries):
            try:
                client.table('image_face_presence').insert(records).execute()
                print(
                    f"[ImageEmbedding] Inserted face batch {batch_num}/{total_batches} "
                    f"({len(records)} rows)"
                )
                return
            except (httpx.RemoteProtocolError, httpx.ConnectError, httpx.ReadError) as e:
                last_err = e
                try:
                    session = getattr(client.postgrest, 'session', None)
                    if session is not None:
                        session.close()
                except Exception:
                    pass
                backoff = 0.5 * (2 ** attempt)
                print(
                    f"[ImageEmbedding] Retry {attempt + 1}/{max_retries} for face batch "
                    f"{batch_num} after {type(e).__name__}: {e}. Sleeping {backoff}s"
                )
                time.sleep(backoff)
        raise last_err if last_err else RuntimeError("face batch insert failed")

    def _normalize_embedding(self, embedding: List[float]) -> List[float]:
        import numpy as np

        arr = np.array(embedding, dtype=np.float32)
        norm = np.linalg.norm(arr)
        if norm == 0:
            return arr.tolist()
        return (arr / norm).tolist()

    def _index_face_presence_from_segments(
        self,
        client,
        user_id: str,
        video_hash: str,
        indexed_segments: List[Dict],
        force_reindex: bool = False,
    ) -> int:
        """Detect faces in already-indexed screenshots and persist ArcFace vectors."""
        if not indexed_segments:
            return 0

        try:
            existing = client.table('image_face_presence').select('id').eq(
                'user_id', user_id
            ).eq('video_hash', video_hash).limit(1).execute()
            if existing.data and not force_reindex:
                print(f"[ImageEmbedding] Face presence already indexed for video {video_hash}")
                return 0
        except Exception as e:
            print(f"[ImageEmbedding] Face presence existence check skipped: {e}")

        segment_ids = [str(seg.get('segment_id', '')) for seg in indexed_segments if seg.get('segment_id') is not None]
        id_by_segment: Dict[str, str] = {}
        for i in range(0, len(segment_ids), 100):
            chunk_ids = segment_ids[i:i + 100]
            try:
                rows = client.table('image_embeddings').select(
                    'id, segment_id'
                ).eq('user_id', user_id).eq(
                    'video_hash', video_hash
                ).in_('segment_id', chunk_ids).execute()
                for row in rows.data or []:
                    id_by_segment[str(row.get('segment_id'))] = row.get('id')
            except Exception as e:
                print(f"[ImageEmbedding] Could not load image embedding ids for face indexing: {e}")

        if not id_by_segment:
            print(f"[ImageEmbedding] No image embedding ids found for face indexing ({video_hash})")
            return 0

        if force_reindex:
            try:
                client.table('image_face_presence').delete().eq(
                    'user_id', user_id
                ).eq('video_hash', video_hash).execute()
            except Exception as e:
                print(f"[ImageEmbedding] Could not clear old face presence rows: {e}")

        print(f"[ImageEmbedding] Indexing face presence for video {video_hash}...")
        face_records: List[Dict] = []
        try:
            from services.face_service import face_service
            for seg in indexed_segments:
                image_embedding_id = id_by_segment.get(str(seg.get('segment_id', '')))
                image_path = seg.get('local_path') or seg.get('screenshot_url')
                if not image_embedding_id or not image_path:
                    continue

                try:
                    detections = face_service.detect_faces(image_path)
                except Exception as e:
                    print(f"[ImageEmbedding] Face detection failed for segment {seg.get('segment_id')}: {e}")
                    continue

                for face in detections or []:
                    embedding = face.get('embedding')
                    if not embedding:
                        continue
                    face_records.append({
                        'user_id': user_id,
                        'image_embedding_id': image_embedding_id,
                        'video_hash': video_hash,
                        'start_time': seg.get('start', 0.0),
                        'end_time': seg.get('end', 0.0),
                        'face_embedding': self._normalize_embedding(embedding),
                        'bbox': face.get('bbox'),
                        'det_score': face.get('confidence'),
                    })
        except Exception as e:
            print(f"[ImageEmbedding] Face presence indexing unavailable: {e}")
            return 0

        if not face_records:
            print(f"[ImageEmbedding] No faces detected for video {video_hash}")
            return 0

        insert_batch_size = 50
        total_batches = (len(face_records) + insert_batch_size - 1) // insert_batch_size
        inserted_count = 0
        for i in range(0, len(face_records), insert_batch_size):
            batch = face_records[i:i + insert_batch_size]
            batch_num = i // insert_batch_size + 1
            try:
                self._insert_face_presence_with_retry(client, batch, batch_num, total_batches)
                inserted_count += len(batch)
            except Exception as e:
                print(
                    f"[ImageEmbedding] Face batch {batch_num}/{total_batches} permanently "
                    f"failed after retries: {e}"
                )

        print(
            f"[ImageEmbedding] Successfully indexed {inserted_count}/{len(face_records)} "
            f"face presence rows for video {video_hash}"
        )
        return inserted_count

    def index_face_presence_for_video(
        self,
        video_hash: str,
        user_id: str,
        force_reindex: bool = False,
    ) -> int:
        """Backfill face presence from persisted image_embeddings rows."""
        client = supabase()

        try:
            existing = client.table('image_face_presence').select('id').eq(
                'user_id', user_id
            ).eq('video_hash', video_hash).limit(1).execute()
            if existing.data and not force_reindex:
                return 0
        except Exception as e:
            print(f"[ImageEmbedding] Face presence backfill check failed: {e}")

        rows = client.table('image_embeddings').select(
            'id, user_id, segment_id, start_time, end_time, speaker, screenshot_url'
        ).eq('user_id', user_id).eq('video_hash', video_hash).execute()

        segments = []
        temp_files = []
        for row in rows.data or []:
            screenshot_url = row.get('screenshot_url')
            if not screenshot_url:
                continue
            try:
                local_path = self._materialize_screenshot(
                    screenshot_url, user_id, video_hash, False
                )
            except Exception as e:
                print(f"[ImageEmbedding] Rejected screenshot during face backfill: {e}")
                continue
            temp_files.append(local_path)
            segments.append({
                'local_path': local_path,
                'screenshot_url': screenshot_url,
                'segment_id': row.get('segment_id'),
                'start': row.get('start_time', 0.0),
                'end': row.get('end_time', 0.0),
                'speaker': row.get('speaker', 'SPEAKER_00'),
            })

        try:
            return self._index_face_presence_from_segments(
                client,
                user_id,
                video_hash,
                segments,
                force_reindex=force_reindex,
            )
        finally:
            for temp_path in temp_files:
                try:
                    os.unlink(temp_path)
                except Exception:
                    pass

    def index_video_images(
        self,
        video_hash: str,
        segments: List[Dict],
        user_id: str,
        force_reindex: bool = False,
        collect_segments: Optional[List[Dict]] = None,
        face_force: Optional[bool] = None,
    ) -> int:
        """
        Index video screenshot images into Supabase using CLIP embeddings

        Args:
            video_hash: Unique hash of the video
            segments: List of transcription segments with screenshot_url field
            user_id: Owner ID for tenant isolation
            collect_segments: If provided, receives the indexed segment dicts
                (with local_path temp files) and temp-file cleanup is skipped —
                the caller owns cleanup. Used by the caption pass.
            face_force: Overrides force_reindex for the face-presence phase
                only. The backfill passes False so dense-frame indexing with
                force_reindex=True doesn't wipe existing face rows.

        Returns:
            Number of images indexed
        """
        if not segments:
            print("[ImageEmbedding] No segments to index")
            return 0
        if not user_id:
            raise ValueError("user_id is required for owner-scoped image indexing")

        client = supabase()

        # Check if already indexed (unless force_reindex)
        if not force_reindex:
            existing = client.table('image_embeddings').select('id').eq(
                'user_id', user_id
            ).eq('video_hash', video_hash).limit(1).execute()

            if existing.data:
                count_result = client.table('image_embeddings').select(
                    'id', count='exact'
                ).eq('user_id', user_id).eq('video_hash', video_hash).execute()
                count = count_result.count if count_result.count else len(existing.data)
                print(f"[ImageEmbedding] Video {video_hash} already has {count} indexed images")
                print(
                    "[ImageEmbedding] Face presence catch-up skipped in image indexing path; "
                    "use /api/jobs/backfill-face-presence for background backfill."
                )
                return count

        # Upsert on (video_hash, segment_id) overwrites rows in place, so we intentionally
        # do NOT pre-delete on force_reindex — partial progress is never destroyed if an
        # insert fails partway through. force_reindex now only bypasses the early-return
        # "already indexed" check above.

        # Extract segments with screenshot URLs
        segments_to_index = []
        temp_files = []  # Track temp files for cleanup

        storage = get_media_storage()
        available_keys = storage.list_screenshot_keys(
            user_id, video_hash, allow_legacy=False
        )
        keys_by_timestamp = {
            key.rsplit('/', 1)[-1].rsplit('.', 1)[0]: key
            for key in available_keys
        }

        for seg in segments:
            screenshot_url = seg.get('screenshot_url') or seg.get('screenshot_path')

            object_key = storage.parse_screenshot_key(screenshot_url) if screenshot_url else None
            if not object_key:
                start = seg.get('start', 0)
                ts_str = f"{start:.2f}"
                if ts_str not in keys_by_timestamp:
                    ts_str = f"{seg.get('screenshot_timestamp', start):.2f}"
                object_key = keys_by_timestamp.get(ts_str)
            if not object_key or not storage.is_owned_screenshot_key(
                object_key, user_id, video_hash, False
            ):
                continue

            try:
                local_path = storage.materialize_screenshot(
                    object_key, user_id, video_hash, False
                )
                screenshot_url = storage.generate_download_url(object_key)
            except (OSError, ValueError) as e:
                print(f"[ImageEmbedding] Rejected screenshot {object_key}: {e}")
                continue
            temp_files.append(local_path)

            segments_to_index.append({
                'local_path': local_path,
                'screenshot_url': screenshot_url,
                'segment_id': seg.get('id', ''),
                'start': seg.get('start', 0.0),
                'end': seg.get('end', 0.0),
                'speaker': seg.get('speaker', 'SPEAKER_00')
            })

        if not segments_to_index:
            print("[ImageEmbedding] No valid screenshots found to index")
            return 0

        total = len(segments_to_index)
        # Phase A: encode all images into an in-memory records list (no DB traffic).
        # Doing this up front keeps the Supabase TCP connection idle-free during Phase B,
        # avoiding the Cloudflare edge timeout that was killing the old interleaved loop.
        print(f"[ImageEmbedding] Encoding {total} images with CLIP for video {video_hash}...")
        encode_batch_size = 32
        records: List[Dict] = []

        for start_i in range(0, total, encode_batch_size):
            chunk = segments_to_index[start_i:start_i + encode_batch_size]
            images: List[Image.Image] = []
            kept: List[Dict] = []
            for seg in chunk:
                try:
                    images.append(Image.open(seg['local_path']).convert('RGB'))
                    kept.append(seg)
                except Exception as e:
                    print(f"[ImageEmbedding] Failed to load {seg['local_path']}: {e}")

            if images:
                try:
                    embeddings = self.clip_model.encode(
                        images,
                        convert_to_numpy=True,
                        batch_size=encode_batch_size,
                    ).tolist()
                except Exception as e:
                    print(
                        f"[ImageEmbedding] CLIP encode failed for chunk at offset "
                        f"{start_i}: {e}"
                    )
                    embeddings = []

                for seg, emb in zip(kept, embeddings):
                    record = {
                        'user_id': user_id,
                        'video_hash': video_hash,
                        'segment_id': str(seg['segment_id']),
                        'start_time': seg['start'],
                        'end_time': seg['end'],
                        'speaker': seg['speaker'],
                        'screenshot_url': seg['screenshot_url'],
                        'embedding': emb,
                    }
                    records.append(record)

            # Free PIL handles immediately. Keep temp files until Phase C so
            # face indexing can reuse the same downloaded screenshots.
            for img in images:
                try:
                    img.close()
                except Exception:
                    pass

            done = min(start_i + encode_batch_size, total)
            print(f"[ImageEmbedding] Encoded {done}/{total} images")

        if not records:
            print("[ImageEmbedding] No embeddings generated")
            for temp_path in temp_files:
                try:
                    os.unlink(temp_path)
                except Exception:
                    pass
            return 0

        # Phase B: bulk insert back-to-back. Connection stays warm, and each batch is
        # wrapped in _upsert_with_retry to recover from occasional transport errors.
        insert_batch_size = 50
        total_batches = (len(records) + insert_batch_size - 1) // insert_batch_size
        print(
            f"[ImageEmbedding] Inserting {len(records)} embeddings in {total_batches} "
            f"batches of {insert_batch_size}..."
        )

        indexed_count = 0
        for i in range(0, len(records), insert_batch_size):
            batch = records[i:i + insert_batch_size]
            batch_num = i // insert_batch_size + 1
            try:
                self._upsert_with_retry(client, batch, batch_num, total_batches)
                indexed_count += len(batch)
            except Exception as e:
                # Upsert is idempotent, so a permanently-failed batch doesn't poison later
                # batches — keep going and report what we got.
                print(
                    f"[ImageEmbedding] Batch {batch_num}/{total_batches} permanently "
                    f"failed after retries: {e}"
                )

        print(
            f"[ImageEmbedding] Successfully indexed {indexed_count}/{len(records)} "
            f"images for video {video_hash}"
        )
        try:
            self._index_face_presence_from_segments(
                client,
                user_id,
                video_hash,
                segments_to_index,
                force_reindex=face_force if face_force is not None else force_reindex,
            )
        except Exception as e:
            print(f"[ImageEmbedding] Face presence indexing failed (non-critical): {e}")
        finally:
            if collect_segments is not None:
                collect_segments.extend(segments_to_index)
            else:
                for temp_path in temp_files:
                    try:
                        os.unlink(temp_path)
                    except Exception:
                        pass
        return indexed_count

    def search_images(
        self,
        video_hash: str,
        query: str,
        user_id: str,
        n_results: int = 5,
        speaker_filter: Optional[str] = None
    ) -> List[Dict]:
        """
        Search for relevant images using text query via CLIP embeddings

        Args:
            video_hash: Unique hash of the video
            query: Text search query
            user_id: Owner ID for tenant isolation
            n_results: Number of results to return
            speaker_filter: Optional speaker name/label to filter results by

        Returns:
            List of relevant image segments with metadata and screenshot URLs
        """
        client = supabase()

        # Generate query embedding using CLIP text encoder
        print(f"[ImageEmbedding] Encoding text query with CLIP: {query}")
        query_embedding = self.clip_model.encode(
            [query],
            convert_to_numpy=True
        ).tolist()[0]

        # Use the Supabase RPC function for similarity search
        try:
            result = client.rpc(
                'search_images_by_embedding',
                {
                    'query_embedding': query_embedding,
                    'p_user_id': user_id,
                    'target_video_hash': video_hash,
                    'match_count': n_results,
                    'speaker_filter': speaker_filter
                }
            ).execute()

            if not result.data:
                print(f"[ImageEmbedding] No results found for query: {query}")
                return []

            # Format results
            formatted_results = []
            for item in result.data:
                formatted_results.append({
                    'screenshot_url': item['screenshot_url'],
                    'metadata': {
                        'video_hash': item['video_hash'],
                        'segment_id': item['segment_id'],
                        'image_embedding_id': item.get('id'),
                        'start': item['start_time'],
                        'end': item['end_time'],
                        'speaker': item['speaker']
                    },
                    'similarity': item['similarity']
                })

            storage = get_media_storage()
            refreshed_results = []
            for image_result in formatted_results:
                object_key = storage.parse_screenshot_key(image_result['screenshot_url'])
                if not object_key or not storage.is_owned_screenshot_key(
                    object_key, user_id, video_hash, allow_legacy=False
                ):
                    print("[ImageEmbedding] Ignoring unrecognized screenshot reference")
                    continue
                try:
                    image_result['screenshot_url'] = storage.generate_download_url(object_key)
                except (OSError, ValueError) as refresh_error:
                    print(f"[ImageEmbedding] Screenshot refresh failed closed: {refresh_error}")
                    continue
                refreshed_results.append(image_result)
            formatted_results = refreshed_results

            print(f"[ImageEmbedding] Found {len(formatted_results)} results for query: {query}")
            return formatted_results

        except Exception as e:
            raise RuntimeError(f"Image embedding search failed: {e}") from e

    async def caption_video_images(
        self,
        video_hash: str,
        segments: Optional[List[Dict]] = None,
        api_key: Optional[str] = None,
        force: bool = False,
        progress_cb: Optional[Callable[[int, int], None]] = None,
    ) -> int:
        """
        Generate xAI vision captions for indexed screenshots and store them with
        all-MiniLM embeddings for caption-based semantic search.

        Args:
            segments: Indexed segment dicts carrying local_path (from
                index_video_images collect_segments) to avoid re-downloading.
                When None (backfill), screenshots are downloaded per row.
            api_key: Per-user xAI key override; falls back to env XAI_API_KEY.
            force: Re-caption rows that already have captions.

        Returns:
            Number of captions stored. Never raises.
        """
        from config import settings
        try:
            client = supabase()
            rows = client.table('image_embeddings').select(
                'id, segment_id, screenshot_url, caption'
            ).eq('video_hash', video_hash).execute()
            work = [
                r for r in rows.data or []
                if force or r.get('caption') is None
            ]
            if not work:
                print(f"[ImageEmbedding] No frames need captions for {video_hash}")
                return 0

            local_paths = {}
            if segments:
                local_paths = {
                    str(s.get('segment_id')): s.get('local_path')
                    for s in segments if s.get('local_path')
                }

            from llm_providers import GrokProvider
            provider = GrokProvider()
            if api_key:
                provider.api_key = api_key
            if not provider.api_key or provider.api_key == "your_xai_api_key_here":
                print("[ImageEmbedding] No xAI API key available; skipping captions")
                return 0

            temp_files: List[str] = []
            resolved = []
            for row in work:
                path = local_paths.get(str(row.get('segment_id')))
                if not path or not os.path.exists(path):
                    url = row.get('screenshot_url')
                    if not url:
                        continue
                    path = None
                    try:
                        if settings.ENABLE_GCS_UPLOADS:
                            from services.gcs_service import gcs_service
                            gcs_path = gcs_service.extract_gcs_path_from_signed_url(url)
                            if gcs_path:
                                path = self._download_gcs_path_to_temp(gcs_path)
                    except Exception:
                        pass
                    if not path:
                        path = self._download_image_to_temp(url)
                    if not path:
                        continue
                    if path.startswith(tempfile.gettempdir()):
                        temp_files.append(path)
                resolved.append((row, path))

            if not resolved:
                print(f"[ImageEmbedding] No caption source images available for {video_hash}")
                return 0

            total = len(resolved)
            print(
                f"[ImageEmbedding] Captioning {total} frames for {video_hash} "
                f"with {settings.XAI_CAPTION_MODEL}..."
            )
            sem = asyncio.Semaphore(settings.XAI_CAPTION_CONCURRENCY)
            done_count = {'n': 0}

            async def _caption_one(row, path):
                async with sem:
                    try:
                        caption = await provider.caption_image(path)
                    except Exception:
                        caption = None
                    done_count['n'] += 1
                    if progress_cb and done_count['n'] % 10 == 0:
                        try:
                            progress_cb(done_count['n'], total)
                        except Exception:
                            pass
                    if caption and _looks_like_refusal(caption):
                        return row, None, True
                    return row, caption, False

            try:
                results = await asyncio.gather(
                    *(_caption_one(row, path) for row, path in resolved)
                )
            finally:
                for temp_path in temp_files:
                    try:
                        os.unlink(temp_path)
                    except Exception:
                        pass

            captioned = [(row, cap) for row, cap, refused in results if cap]
            refusals = sum(1 for _, _, refused in results if refused)
            failures = total - len(captioned) - refusals

            if not captioned:
                print(
                    f"[ImageEmbedding] Captioned 0/{total} frames for {video_hash} "
                    f"({refusals} refusals, {failures} failures)"
                )
                return 0

            # Embed all captions in one batch with the shared all-MiniLM model
            loop = asyncio.get_event_loop()
            caption_texts = [cap for _, cap in captioned]
            embeddings = await loop.run_in_executor(
                None,
                lambda: self.caption_embedding_model.encode(
                    caption_texts, convert_to_numpy=True
                ).tolist(),
            )

            # Per-sentence embeddings for retrieval (one batch encode for all)
            sentence_rows: List[Dict] = []
            all_sentences: List[str] = []
            sentence_owners: List[Dict] = []
            for row, cap in captioned:
                for sentence in _split_caption_sentences(cap):
                    all_sentences.append(sentence)
                    sentence_owners.append(row)
            if all_sentences:
                sentence_embs = await loop.run_in_executor(
                    None,
                    lambda: self.caption_embedding_model.encode(
                        all_sentences, convert_to_numpy=True
                    ).tolist(),
                )
                for row, sentence, emb in zip(sentence_owners, all_sentences, sentence_embs):
                    sentence_rows.append({
                        'image_embedding_id': row.get('id'),
                        'video_hash': video_hash,
                        'sentence': sentence,
                        'embedding': emb,
                    })

            stored = 0
            for (row, cap), emb in zip(captioned, embeddings):
                try:
                    await loop.run_in_executor(
                        None,
                        lambda r=row, c=cap, e=emb: self._update_caption_with_retry(
                            client, video_hash, str(r.get('segment_id')), c, e
                        ),
                    )
                    stored += 1
                except Exception as e:
                    print(f"[ImageEmbedding] Caption store failed for {row.get('segment_id')}: {e}")

            if sentence_rows:
                try:
                    captioned_ids = [r.get('id') for r, _ in captioned if r.get('id')]
                    await loop.run_in_executor(
                        None,
                        lambda: self._replace_caption_sentences(client, captioned_ids, sentence_rows),
                    )
                except Exception as e:
                    print(f"[ImageEmbedding] Caption sentence index failed (non-critical): {e}")

            print(
                f"[ImageEmbedding] Captioned {stored}/{total} frames for {video_hash} "
                f"({refusals} refusals, {failures} failures)"
            )
            return stored
        except Exception as e:
            print(f"[ImageEmbedding] Caption pass failed (non-critical): {e}")
            return 0

    def _update_caption_with_retry(
        self,
        client,
        video_hash: str,
        segment_id: str,
        caption: str,
        embedding: List[float],
        max_retries: int = 3,
    ) -> None:
        last_err: Optional[Exception] = None
        for attempt in range(max_retries):
            try:
                client.table('image_embeddings').update({
                    'caption': caption,
                    'caption_embedding': embedding,
                }).eq('video_hash', video_hash).eq('segment_id', segment_id).execute()
                return
            except (httpx.RemoteProtocolError, httpx.ConnectError, httpx.ReadError) as e:
                last_err = e
                try:
                    session = getattr(client.postgrest, 'session', None)
                    if session is not None:
                        session.close()
                except Exception:
                    pass
                time.sleep(0.5 * (2 ** attempt))
        raise last_err if last_err else RuntimeError("caption update failed")

    def _replace_caption_sentences(
        self,
        client,
        image_embedding_ids: List[str],
        sentence_rows: List[Dict],
    ) -> None:
        """Delete-then-insert sentence rows for the given images (idempotent
        re-caption support). Insert in batches of 100."""
        delete_batch = 100
        for i in range(0, len(image_embedding_ids), delete_batch):
            chunk = image_embedding_ids[i:i + delete_batch]
            try:
                client.table('image_caption_sentences').delete().in_(
                    'image_embedding_id', chunk
                ).execute()
            except Exception as e:
                print(f"[ImageEmbedding] Sentence delete failed (continuing): {e}")
        for i in range(0, len(sentence_rows), 100):
            client.table('image_caption_sentences').insert(
                sentence_rows[i:i + 100]
            ).execute()
        print(f"[ImageEmbedding] Indexed {len(sentence_rows)} caption sentences")

    def search_images_by_caption(
        self,
        video_hash: str,
        query: str,
        n_results: int = 6,
    ) -> List[Dict]:
        """
        Search indexed frames by vision-caption similarity (all-MiniLM text
        embeddings, scored per caption sentence). Complements CLIP search for
        action/explicit queries where CLIP's zero-shot signal is too weak.
        """
        try:
            client = supabase()
            query_embedding = self.caption_embedding_model.encode(
                [query], convert_to_numpy=True
            ).tolist()[0]

            try:
                result = client.rpc(
                    'search_images_by_caption_sentences',
                    {
                        'query_embedding': query_embedding,
                        'target_video_hash': video_hash,
                        'match_count': n_results,
                    }
                ).execute()
            except Exception:
                result = None

            # Fallback for DBs without the sentence index yet
            if not result or not result.data:
                result = client.rpc(
                    'search_images_by_caption_embedding',
                    {
                        'query_embedding': query_embedding,
                        'target_video_hash': video_hash,
                        'match_count': n_results,
                    }
                ).execute()

            if not result.data:
                return []

            formatted_results = []
            for item in result.data:
                formatted_results.append({
                    'screenshot_url': item['screenshot_url'],
                    'metadata': {
                        'video_hash': item['video_hash'],
                        'segment_id': item['segment_id'],
                        'image_embedding_id': item.get('id'),
                        'start': item['start_time'],
                        'end': item['end_time'],
                        'speaker': item['speaker']
                    },
                    'similarity': item['similarity'],
                    'caption': item.get('caption'),
                    'source': 'caption',
                })

            try:
                from services.gcs_service import gcs_service
                from config import settings as _settings
                if _settings.ENABLE_GCS_UPLOADS:
                    gcs_service.refresh_screenshot_urls_in_segments(formatted_results)
            except Exception as refresh_err:
                print(f"[ImageEmbedding] URL refresh skipped: {refresh_err}")

            print(f"[ImageEmbedding] Found {len(formatted_results)} caption matches for query: {query}")
            return formatted_results
        except Exception as e:
            print(f"[ImageEmbedding] Caption search error: {e}")
            return []

    def image_collection_exists(self, video_hash: str, user_id: str) -> bool:
        """
        Check if images are indexed for a video

        Args:
            video_hash: Unique hash of the video

        Returns:
            True if images are indexed, False otherwise
        """
        try:
            client = supabase()
            result = client.table('image_embeddings').select(
                'id', count='exact'
            ).eq('user_id', user_id).eq('video_hash', video_hash).limit(1).execute()

            count = result.count if result.count else 0
            return count > 0
        except Exception as e:
            raise RuntimeError(f"Image embedding availability check failed: {e}") from e

    def delete_image_embeddings(self, video_hash: str, user_id: str) -> bool:
        """
        Delete all image embeddings for a video

        Args:
            video_hash: Unique hash of the video

        Returns:
            True if successful, False otherwise
        """
        try:
            client = supabase()
            client.table('image_embeddings').delete().eq(
                'user_id', user_id
            ).eq('video_hash', video_hash).execute()
            print(f"[ImageEmbedding] Deleted embeddings for video {video_hash}")
            return True
        except Exception as e:
            raise RuntimeError(f"Image embedding deletion failed: {e}") from e

    def get_indexed_count(self, video_hash: str, user_id: str) -> int:
        """
        Get the count of indexed images for a video

        Args:
            video_hash: Unique hash of the video

        Returns:
            Number of indexed images
        """
        try:
            client = supabase()
            result = client.table('image_embeddings').select(
                'id', count='exact'
            ).eq('user_id', user_id).eq('video_hash', video_hash).execute()
            return result.count if result.count else 0
        except Exception as e:
            raise RuntimeError(f"Image embedding count failed: {e}") from e


# Global instance
image_embedding_service = ImageEmbeddingService()
