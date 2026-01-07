"""
Image Embedding Service using Supabase pgvector
Handles persistent storage of CLIP embeddings for video screenshots
"""

import os
import tempfile
import requests
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

    def index_video_images(
        self,
        video_hash: str,
        segments: List[Dict],
        force_reindex: bool = False
    ) -> int:
        """
        Index video screenshot images into Supabase using CLIP embeddings

        Args:
            video_hash: Unique hash of the video
            segments: List of transcription segments with screenshot_url field
            force_reindex: If True, delete existing embeddings and re-index

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

        # Delete existing if force_reindex
        if force_reindex:
            print(f"[ImageEmbedding] Force re-index: deleting existing embeddings for {video_hash}")
            client.table('image_embeddings').delete().eq('video_hash', video_hash).execute()

        # Extract segments with screenshot URLs
        segments_to_index = []
        temp_files = []  # Track temp files for cleanup

        for seg in segments:
            screenshot_url = seg.get('screenshot_url') or seg.get('screenshot_path')
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

        print(f"[ImageEmbedding] Indexing {len(segments_to_index)} images for video {video_hash}...")

        # Generate embeddings and insert into Supabase
        indexed_count = 0
        batch_size = 10  # Process in batches

        try:
            for i in range(0, len(segments_to_index), batch_size):
                batch = segments_to_index[i:i + batch_size]
                records = []

                for seg in batch:
                    embedding = self._generate_embedding(seg['local_path'])
                    if embedding is None:
                        continue

                    records.append({
                        'video_hash': video_hash,
                        'segment_id': str(seg['segment_id']),
                        'start_time': seg['start'],
                        'end_time': seg['end'],
                        'speaker': seg['speaker'],
                        'screenshot_url': seg['screenshot_url'],
                        'embedding': embedding
                    })

                if records:
                    # Upsert to handle duplicates gracefully
                    client.table('image_embeddings').upsert(
                        records,
                        on_conflict='video_hash,segment_id'
                    ).execute()
                    indexed_count += len(records)
                    print(f"[ImageEmbedding] Indexed batch {i // batch_size + 1}: {len(records)} images")

        finally:
            # Cleanup temp files
            for temp_path in temp_files:
                try:
                    os.unlink(temp_path)
                except:
                    pass

        print(f"[ImageEmbedding] Successfully indexed {indexed_count} images for video {video_hash}")
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
