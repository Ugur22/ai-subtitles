"""
Image Embedding Service using Supabase pgvector
Handles persistent storage of CLIP embeddings for video screenshots
"""

import os
import tempfile
import time
import requests
import httpx
from typing import List, Dict, Optional
from PIL import Image
from sentence_transformers import SentenceTransformer
from services.supabase_service import supabase


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
            print("[ImageEmbedding] Loading CLIP model (clip-ViT-B-32)...")
            self._clip_model = SentenceTransformer('clip-ViT-B-32')
            print("[ImageEmbedding] CLIP model loaded successfully")
        return self._clip_model

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
                        if _cfg.ENABLE_GCS_UPLOADS:
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
                    records, on_conflict='video_hash,segment_id'
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

    def index_video_images(
        self,
        video_hash: str,
        segments: List[Dict],
        force_reindex: bool = False,
        user_id: Optional[str] = None
    ) -> int:
        """
        Index video screenshot images into Supabase using CLIP embeddings

        Args:
            video_hash: Unique hash of the video
            segments: List of transcription segments with screenshot_url field
            force_reindex: If True, delete existing embeddings and re-index
            user_id: Optional user ID for RLS policy compliance

        Returns:
            Number of images indexed
        """
        if not segments:
            print("[ImageEmbedding] No segments to index")
            return 0

        client = supabase()

        # Check if already indexed (unless force_reindex)
        if not force_reindex:
            existing = client.table('image_embeddings').select('id').eq(
                'video_hash', video_hash
            ).limit(1).execute()

            if existing.data:
                count_result = client.table('image_embeddings').select(
                    'id', count='exact'
                ).eq('video_hash', video_hash).execute()
                count = count_result.count if count_result.count else len(existing.data)
                print(f"[ImageEmbedding] Video {video_hash} already has {count} indexed images")
                return count

        # Upsert on (video_hash, segment_id) overwrites rows in place, so we intentionally
        # do NOT pre-delete on force_reindex — partial progress is never destroyed if an
        # insert fails partway through. force_reindex now only bypasses the early-return
        # "already indexed" check above.

        # Extract segments with screenshot URLs
        segments_to_index = []
        temp_files = []  # Track temp files for cleanup

        # Pre-load available GCS screenshots in one list API call so we can
        # recover when screenshot_url is null (common for older jobs).
        _gcs_bucket = None
        _gcs_ts_set: set = set()
        _gcs_cfg = None
        _GCSService = None
        try:
            from config import settings as _gcs_cfg
            if _gcs_cfg.ENABLE_GCS_UPLOADS:
                from services.gcs_service import GCSService as _GCSService
                _gcs_bucket = _GCSService._get_bucket()
                prefix = f"screenshots/{video_hash}/"
                for b in _gcs_bucket.list_blobs(prefix=prefix):
                    fname = b.name.rsplit('/', 1)[-1]
                    if fname.endswith('.jpg'):
                        _gcs_ts_set.add(fname[:-4])  # "1001.64"
                if _gcs_ts_set:
                    print(f"[ImageEmbedding] GCS fallback: {len(_gcs_ts_set)} screenshots found for {video_hash}")
        except Exception as e:
            print(f"[ImageEmbedding] Could not list GCS screenshots: {e}")

        for seg in segments:
            screenshot_url = seg.get('screenshot_url') or seg.get('screenshot_path')

            # GCS fallback: screenshot_url is null but file exists in GCS
            if not screenshot_url and _gcs_bucket and _gcs_ts_set:
                start = seg.get('start', 0)
                ts_str = f"{start:.2f}"
                # Silent segments store screenshot at midpoint (screenshot_timestamp), not start
                if ts_str not in _gcs_ts_set:
                    ts_str = f"{seg.get('screenshot_timestamp', start):.2f}"
                if ts_str in _gcs_ts_set:
                    gcs_path = f"screenshots/{video_hash}/{ts_str}.jpg"
                    try:
                        img_data = _gcs_bucket.blob(gcs_path).download_as_bytes()
                        with tempfile.NamedTemporaryFile(delete=False, suffix='.jpg') as tmp:
                            tmp.write(img_data)
                            tmp_path = tmp.name
                        temp_files.append(tmp_path)
                        signed_url = _GCSService.generate_download_signed_url(
                            gcs_path,
                            expiry_seconds=_gcs_cfg.GCS_SCREENSHOT_URL_EXPIRY
                        )
                        segments_to_index.append({
                            'local_path': tmp_path,
                            'screenshot_url': signed_url,
                            'segment_id': seg.get('id', ''),
                            'start': seg.get('start', 0.0),
                            'end': seg.get('end', 0.0),
                            'speaker': seg.get('speaker', 'SPEAKER_00')
                        })
                    except Exception as e:
                        print(f"[ImageEmbedding] GCS download failed for {gcs_path}: {e}")
                continue  # null-url segments handled above; skip normal path

            if not screenshot_url:
                continue

            # Download image to temp file if it's a URL
            local_path = self._download_image_to_temp(screenshot_url)
            if not local_path:
                continue

            # Track temp files for cleanup
            if local_path.startswith(tempfile.gettempdir()):
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
        tmp_dir = tempfile.gettempdir()

        # Phase A: encode all images into an in-memory records list (no DB traffic).
        # Doing this up front keeps the Supabase TCP connection idle-free during Phase B,
        # avoiding the Cloudflare edge timeout that was killing the old interleaved loop.
        print(f"[ImageEmbedding] Encoding {total} images with CLIP for video {video_hash}...")
        encode_batch_size = 32
        records: List[Dict] = []

        try:
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
                            'video_hash': video_hash,
                            'segment_id': str(seg['segment_id']),
                            'start_time': seg['start'],
                            'end_time': seg['end'],
                            'speaker': seg['speaker'],
                            'screenshot_url': seg['screenshot_url'],
                            'embedding': emb,
                        }
                        if user_id:
                            record['user_id'] = user_id
                        records.append(record)

                # Free PIL handles and per-chunk temp files immediately.
                for img in images:
                    try:
                        img.close()
                    except Exception:
                        pass
                for seg in chunk:
                    path = seg.get('local_path', '')
                    if path.startswith(tmp_dir):
                        try:
                            os.unlink(path)
                        except Exception:
                            pass

                done = min(start_i + encode_batch_size, total)
                print(f"[ImageEmbedding] Encoded {done}/{total} images")
        finally:
            # Safety net in case a code path skipped chunk-local cleanup above.
            for temp_path in temp_files:
                try:
                    os.unlink(temp_path)
                except Exception:
                    pass

        if not records:
            print("[ImageEmbedding] No embeddings generated")
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
        return indexed_count

    def search_images(
        self,
        video_hash: str,
        query: str,
        n_results: int = 5,
        speaker_filter: Optional[str] = None
    ) -> List[Dict]:
        """
        Search for relevant images using text query via CLIP embeddings

        Args:
            video_hash: Unique hash of the video
            query: Text search query
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
                        'start': item['start_time'],
                        'end': item['end_time'],
                        'speaker': item['speaker']
                    },
                    'similarity': item['similarity']
                })

            print(f"[ImageEmbedding] Found {len(formatted_results)} results for query: {query}")
            return formatted_results

        except Exception as e:
            print(f"[ImageEmbedding] Search error: {e}")
            return []

    def image_collection_exists(self, video_hash: str) -> bool:
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
            ).eq('video_hash', video_hash).limit(1).execute()

            count = result.count if result.count else 0
            return count > 0
        except Exception as e:
            print(f"[ImageEmbedding] Error checking collection: {e}")
            return False

    def delete_image_embeddings(self, video_hash: str) -> bool:
        """
        Delete all image embeddings for a video

        Args:
            video_hash: Unique hash of the video

        Returns:
            True if successful, False otherwise
        """
        try:
            client = supabase()
            client.table('image_embeddings').delete().eq('video_hash', video_hash).execute()
            print(f"[ImageEmbedding] Deleted embeddings for video {video_hash}")
            return True
        except Exception as e:
            print(f"[ImageEmbedding] Error deleting embeddings: {e}")
            return False

    def get_indexed_count(self, video_hash: str) -> int:
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
            ).eq('video_hash', video_hash).execute()
            return result.count if result.count else 0
        except Exception as e:
            print(f"[ImageEmbedding] Error getting count: {e}")
            return 0


# Global instance
image_embedding_service = ImageEmbeddingService()
