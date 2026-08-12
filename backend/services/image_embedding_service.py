"""
Image Embedding Service using Supabase pgvector
Handles persistent storage of CLIP embeddings for video screenshots
"""

import os
import time
import httpx
from typing import List, Dict, Optional
from PIL import Image
from sentence_transformers import SentenceTransformer
from services.supabase_service import supabase
from services.media_storage import get_media_storage
from config import settings


class ImageEmbeddingService:
    """Service for storing and searching image embeddings in Supabase"""

    def __init__(self):
        """Initialize the image embedding service"""
        self._clip_model = None

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
    ) -> int:
        """
        Index video screenshot images into Supabase using CLIP embeddings

        Args:
            video_hash: Unique hash of the video
            segments: List of transcription segments with screenshot_url field
            force_reindex: If True, delete existing embeddings and re-index
            user_id: Owner ID for tenant isolation

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
                force_reindex=force_reindex,
            )
        except Exception as e:
            print(f"[ImageEmbedding] Face presence indexing failed (non-critical): {e}")
        finally:
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
