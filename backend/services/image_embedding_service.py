"""
Image Embedding Service using Supabase pgvector
Handles persistent storage of CLIP embeddings for video screenshots
"""

import asyncio
import os
import re
import time
import httpx
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
        collect_segments: Optional[List[Dict]] = None,
        face_force: Optional[bool] = None,
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

    def _format_search_results(
        self, items: List[Dict], user_id: str, video_hash: str
    ) -> List[Dict]:
        """Shape raw image_embeddings rows into search results with fresh,
        ownership-checked screenshot URLs."""
        formatted_results = []
        for item in items:
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
        return refreshed_results


    def search_images_within(
        self,
        video_hash: str,
        query: str,
        user_id: str,
        image_embedding_ids: List[str],
        n_results: int = 5,
    ) -> List[Dict]:
        """CLIP text search restricted to the given image_embeddings ids.

        Used to find scene matches among frames where a named person appears;
        a global top-K would be dominated by other people's frames.
        """
        import json
        import numpy as np

        if not image_embedding_ids:
            return []
        client = supabase()
        query_vec = np.asarray(
            self.clip_model.encode([query], convert_to_numpy=True)[0], dtype=np.float32
        )
        query_norm = np.linalg.norm(query_vec)
        if query_norm == 0:
            return []

        scored = []
        ids = list(dict.fromkeys(image_embedding_ids))
        for i in range(0, len(ids), 100):
            rows = client.table('image_embeddings').select(
                'id, video_hash, segment_id, start_time, end_time, speaker, '
                'screenshot_url, embedding'
            ).eq('user_id', user_id).eq('video_hash', video_hash).in_(
                'id', ids[i:i + 100]
            ).execute()
            for row in rows.data or []:
                embedding = row.pop('embedding', None)
                if isinstance(embedding, str):
                    embedding = json.loads(embedding)
                if not embedding:
                    continue
                vec = np.asarray(embedding, dtype=np.float32)
                norm = np.linalg.norm(vec)
                if norm == 0:
                    continue
                row['similarity'] = float(vec @ query_vec / (norm * query_norm))
                scored.append(row)

        scored.sort(key=lambda r: r['similarity'], reverse=True)
        results = self._format_search_results(scored[:n_results], user_id, video_hash)
        print(
            f"[ImageEmbedding] Found {len(results)} results among {len(ids)} "
            f"restricted frames for query: {query}"
        )
        return results


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

            formatted_results = self._format_search_results(
                result.data, user_id, video_hash
            )

            print(f"[ImageEmbedding] Found {len(formatted_results)} results for query: {query}")
            return formatted_results

        except Exception as e:
            raise RuntimeError(f"Image embedding search failed: {e}") from e

    @property
    def caption_embedding_model(self) -> SentenceTransformer:
        from services.transcript_embedding_service import transcript_embedding_service
        return transcript_embedding_service.embedding_model

    async def caption_video_images(
        self,
        video_hash: str,
        user_id: str,
        segments: Optional[List[Dict]] = None,
        api_key: Optional[str] = None,
        force: bool = False,
        progress_cb: Optional[Callable[[int, int], None]] = None,
        max_frames: Optional[int] = None,
        timeout_seconds: Optional[float] = None,
    ) -> int:
        operation = self._caption_video_images(
            video_hash, user_id, segments=segments, api_key=api_key, force=force,
            progress_cb=progress_cb, max_frames=max_frames, timeout_seconds=timeout_seconds,
        )
        if timeout_seconds is None:
            return await operation
        try:
            return await asyncio.wait_for(operation, timeout=max(0.01, timeout_seconds))
        except asyncio.TimeoutError:
            return 0

    async def _caption_video_images(
        self,
        video_hash: str,
        user_id: str,
        segments: Optional[List[Dict]] = None,
        api_key: Optional[str] = None,
        force: bool = False,
        progress_cb: Optional[Callable[[int, int], None]] = None,
        max_frames: Optional[int] = None,
        timeout_seconds: Optional[float] = None,
    ) -> int:
        deadline = time.monotonic() + timeout_seconds if timeout_seconds else None
        if not user_id:
            raise ValueError("user_id is required for caption indexing")
        if not settings.ENABLE_VISION_CAPTIONS:
            return 0
        from llm_providers import GrokProvider

        model_name = settings.TEXT_EMBEDDING_MODEL
        limit = min(max_frames or settings.CAPTION_MAX_FRAMES, settings.CAPTION_MAX_FRAMES, 1000)
        if limit <= 0:
            return 0
        client = supabase()
        try:
            response = await asyncio.to_thread(
                lambda: client.rpc("caption_frames_to_process", {
                    "p_user_id": user_id,
                    "target_video_hash": video_hash,
                    "target_embedding_model": model_name,
                    "batch_limit": limit,
                    "include_existing": force,
                }).execute()
            )
            rows = response.data or []
        except Exception as error:
            print(f"[ImageEmbedding] Caption discovery unavailable: {error}")
            return 0
        if not rows:
            return 0
        provider = GrokProvider()
        if api_key:
            provider.api_key = api_key
        if not provider.is_available():
            return 0

        storage = get_media_storage()
        local_paths = {
            str(segment.get("segment_id")): segment.get("local_path")
            for segment in segments or [] if segment.get("local_path")
        }
        semaphore = asyncio.Semaphore(max(1, min(settings.XAI_CAPTION_CONCURRENCY, 8)))
        done = 0

        async def caption_one(row):
            nonlocal done
            async with semaphore:
                if deadline and time.monotonic() >= deadline:
                    return None
                path = None
                temporary = False
                try:
                    if row.get("caption") and not force:
                        return row, row["caption"]
                    reference = row.get("screenshot_url")
                    object_key = storage.parse_screenshot_key(reference)
                    if not object_key or not storage.is_owned_screenshot_key(
                        object_key, user_id, video_hash, allow_legacy=False
                    ):
                        return None
                    path = local_paths.get(str(row.get("segment_id")))
                    if not path or not os.path.exists(path):
                        path = await asyncio.to_thread(
                            storage.materialize_screenshot, object_key, user_id, video_hash, False
                        )
                        temporary = True
                    remaining = max(0.01, deadline - time.monotonic()) if deadline else 100.0
                    caption = await asyncio.wait_for(provider.caption_image(path), timeout=remaining)
                    if _looks_like_refusal(caption):
                        return None
                    return row, caption
                except (Exception, asyncio.TimeoutError) as error:
                    print(f"[ImageEmbedding] Caption failed for {row.get('id')}: {error}")
                    return None
                finally:
                    if temporary and path:
                        try:
                            os.unlink(path)
                        except OSError:
                            pass
                    done += 1
                    if progress_cb:
                        progress_cb(done, len(rows))

        tasks = [asyncio.create_task(caption_one(row)) for row in rows]
        try:
            results = [result for result in await asyncio.gather(*tasks) if result]
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
        if not results:
            return 0

        stored = 0
        for row, caption in results:
            try:
                sentences = _split_caption_sentences(caption)
                texts = [caption] + sentences
                embeddings = await asyncio.to_thread(
                    lambda: self.caption_embedding_model.encode(texts, convert_to_numpy=True).tolist()
                )
                sentence_rows = [
                    {
                        "user_id": user_id,
                        "video_hash": video_hash,
                        "image_embedding_id": row["id"],
                        "embedding_model": model_name,
                        "sentence": sentence,
                        "embedding": embedding,
                    }
                    for sentence, embedding in zip(sentences, embeddings[1:])
                ]

                response = await asyncio.to_thread(
                    lambda: client.rpc("store_image_caption", {
                        "p_user_id": user_id,
                        "target_video_hash": video_hash,
                        "image_id": row["id"],
                        "caption_text": caption,
                        "caption_vector": embeddings[0],
                        "target_embedding_model": model_name,
                        "sentence_rows": [{"sentence": item["sentence"], "embedding": item["embedding"]}
                                          for item in sentence_rows],
                    }).execute()
                )
                if response.data is not True:
                    continue
                stored += 1
            except Exception as error:
                print(f"[ImageEmbedding] Caption storage failed for {row.get('id')}: {error}")
        return stored

    def search_images_by_caption(
        self, video_hash: str, query: str, user_id: str, n_results: int = 6
    ) -> List[Dict]:
        if not user_id:
            raise ValueError("user_id is required for caption search")
        if not settings.ENABLE_VISION_CAPTIONS:
            return []
        from services.transcript_embedding_service import prepare_embedding_query

        try:
            embedding = self.caption_embedding_model.encode(
                [prepare_embedding_query(query)], convert_to_numpy=True
            ).tolist()[0]
            result = supabase().rpc("search_images_by_caption_sentences", {
                "p_user_id": user_id,
                "query_embedding": embedding,
                "target_video_hash": video_hash,
                "target_embedding_model": settings.TEXT_EMBEDDING_MODEL,
                "match_count": n_results,
            }).execute()
            rows = result.data or []
            formatted = self._format_search_results(rows, user_id, video_hash)
            captions = {row["id"]: row.get("caption") for row in rows}
            for item in formatted:
                item["caption"] = captions.get(item["metadata"]["image_embedding_id"])
                item["source"] = "caption"
            return formatted
        except Exception as error:
            print(f"[ImageEmbedding] Caption search unavailable: {error}")
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
