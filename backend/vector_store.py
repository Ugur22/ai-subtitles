"""
Vector Store for RAG (Retrieval-Augmented Generation)
Uses ChromaDB for storing and retrieving transcript embeddings
Supports both text embeddings (for transcripts) and image embeddings (using CLIP)
"""

import os
import chromadb
from chromadb.config import Settings
from sentence_transformers import SentenceTransformer
from typing import List, Dict, Optional
from PIL import Image
import hashlib


class VectorStore:
    """Manages vector embeddings for transcription segments and images"""

    def __init__(self, persist_directory: str = "./chroma_db"):
        """
        Initialize the vector store

        Args:
            persist_directory: Directory to persist ChromaDB data
        """
        self.persist_directory = persist_directory
        os.makedirs(persist_directory, exist_ok=True)

        # Initialize ChromaDB client
        self.client = chromadb.PersistentClient(
            path=persist_directory,
            settings=Settings(
                anonymized_telemetry=False,
                allow_reset=True
            )
        )

        # Initialize text embedding model (lazy loading)
        print("Loading text embedding model (sentence-transformers)...")
        self.embedding_model = SentenceTransformer('all-MiniLM-L6-v2')
        print("Text embedding model loaded successfully")

        # CLIP model for image embeddings (lazy loading)
        self._clip_model = None

        # Default collection name
        self.collection_name = "transcriptions"

    @property
    def clip_model(self) -> SentenceTransformer:
        """
        Lazy load CLIP model for image embeddings

        Returns:
            CLIP model from sentence-transformers
        """
        if self._clip_model is None:
            print("Loading CLIP model (clip-ViT-B-32)...")
            self._clip_model = SentenceTransformer('clip-ViT-B-32')
            print("CLIP model loaded successfully")
        return self._clip_model

    def get_or_create_collection(self, video_hash: str) -> chromadb.Collection:
        """
        Get or create a collection for a specific video

        Args:
            video_hash: Unique hash of the video

        Returns:
            ChromaDB collection
        """
        collection_name = f"video_{video_hash}"
        try:
            collection = self.client.get_collection(name=collection_name)
            print(f"Retrieved existing collection: {collection_name}")
        except:
            collection = self.client.create_collection(
                name=collection_name,
                metadata={"video_hash": video_hash}
            )
            print(f"Created new collection: {collection_name}")

        return collection

    def index_transcription(
        self,
        video_hash: str,
        segments: List[Dict],
        chunk_size: int = 3
    ) -> int:
        """
        Index transcription segments into vector database

        Args:
            video_hash: Unique hash of the video
            segments: List of transcription segments
            chunk_size: Number of segments to combine into one chunk (default: 3)

        Returns:
            Number of chunks indexed
        """
        if not segments:
            print("No segments to index")
            return 0

        collection = self.get_or_create_collection(video_hash)

        # Check if already indexed
        try:
            count = collection.count()
            if count > 0:
                print(f"Collection already has {count} chunks. Skipping indexing.")
                return count
        except:
            pass

        # Combine segments into chunks for better context
        chunks = []
        chunk_metadata = []
        chunk_ids = []

        for i in range(0, len(segments), chunk_size):
            chunk_segments = segments[i:i + chunk_size]

            # Combine text from multiple segments
            texts = []
            for seg in chunk_segments:
                # Use translation if available and not empty, otherwise use original text
                text = seg.get('translation') or seg.get('text', '')
                if text and text.strip():
                    texts.append(text.strip())

            if not texts:
                continue

            combined_text = " ".join(texts)

            # Create metadata
            first_segment = chunk_segments[0]
            last_segment = chunk_segments[-1]

            # Get segment IDs and convert to JSON string (ChromaDB doesn't accept lists)
            segment_ids = [seg.get('id', str(i)) for seg in chunk_segments]

            metadata = {
                "video_hash": video_hash,
                "start": first_segment.get('start', 0.0),
                "end": last_segment.get('end', 0.0),
                "start_time": first_segment.get('start_time', '00:00:00'),
                "end_time": last_segment.get('end_time', '00:00:00'),
                "speaker": first_segment.get('speaker', 'SPEAKER_00'),
                "segment_ids": str(len(segment_ids))  # Store count instead of list
            }

            # Generate unique ID for this chunk
            chunk_id = hashlib.md5(
                f"{video_hash}_{metadata['start']}_{metadata['end']}".encode()
            ).hexdigest()

            chunks.append(combined_text)
            chunk_metadata.append(metadata)
            chunk_ids.append(chunk_id)

        if not chunks:
            print("No valid chunks to index")
            return 0

        # Generate embeddings
        print(f"Generating embeddings for {len(chunks)} chunks...")
        embeddings = self.embedding_model.encode(
            chunks,
            show_progress_bar=True,
            convert_to_numpy=True
        ).tolist()

        # Add to ChromaDB
        collection.add(
            embeddings=embeddings,
            documents=chunks,
            metadatas=chunk_metadata,
            ids=chunk_ids
        )

        print(f"Successfully indexed {len(chunks)} chunks for video {video_hash}")
        return len(chunks)

    def search(
        self,
        video_hash: str,
        query: str,
        n_results: int = 5
    ) -> List[Dict]:
        """
        Search for relevant chunks using semantic similarity

        Args:
            video_hash: Unique hash of the video
            query: Search query
            n_results: Number of results to return

        Returns:
            List of relevant chunks with metadata and timestamps
        """
        collection = self.get_or_create_collection(video_hash)

        # Check if collection has data
        count = collection.count()
        if count == 0:
            print(f"Collection for video {video_hash} is empty")
            return []

        # Generate query embedding
        query_embedding = self.embedding_model.encode(
            [query],
            convert_to_numpy=True
        ).tolist()[0]

        # Search in ChromaDB
        results = collection.query(
            query_embeddings=[query_embedding],
            n_results=min(n_results, count)
        )

        # Format results
        formatted_results = []
        if results['documents'] and len(results['documents']) > 0:
            for i in range(len(results['documents'][0])):
                formatted_results.append({
                    "text": results['documents'][0][i],
                    "metadata": results['metadatas'][0][i],
                    "distance": results['distances'][0][i] if 'distances' in results else None
                })

        return formatted_results

    def delete_collection(self, video_hash: str) -> bool:
        """
        Delete a collection for a specific video

        Args:
            video_hash: Unique hash of the video

        Returns:
            True if successful, False otherwise
        """
        try:
            collection_name = f"video_{video_hash}"
            self.client.delete_collection(name=collection_name)
            print(f"Deleted collection: {collection_name}")
            return True
        except Exception as e:
            print(f"Error deleting collection: {str(e)}")
            return False

    def collection_exists(self, video_hash: str) -> bool:
        """Check if a collection exists for a video"""
        try:
            collection_name = f"video_{video_hash}"
            self.client.get_collection(name=collection_name)
            return True
        except:
            return False

    def get_or_create_image_collection(self, video_hash: str) -> chromadb.Collection:
        """
        Get or create an image collection for a specific video

        Args:
            video_hash: Unique hash of the video

        Returns:
            ChromaDB collection for images
        """
        collection_name = f"video_{video_hash}_images"
        try:
            collection = self.client.get_collection(name=collection_name)
            print(f"Retrieved existing image collection: {collection_name}")
        except:
            collection = self.client.create_collection(
                name=collection_name,
                metadata={"video_hash": video_hash, "type": "images"}
            )
            print(f"Created new image collection: {collection_name}")

        return collection

    def embed_images(self, image_paths: List[str]) -> List[List[float]]:
        """
        Generate CLIP embeddings for a list of images

        Args:
            image_paths: List of paths to image files

        Returns:
            List of embeddings (each embedding is a list of floats)

        Raises:
            FileNotFoundError: If an image file doesn't exist
            Exception: If image loading or encoding fails
        """
        if not image_paths:
            return []

        # Load images
        images = []
        valid_paths = []

        for path in image_paths:
            try:
                if os.path.exists(path):
                    img = Image.open(path).convert('RGB')
                    images.append(img)
                    valid_paths.append(path)
                else:
                    print(f"Warning: Image not found: {path}")
            except Exception as e:
                print(f"Warning: Failed to load image {path}: {str(e)}")

        if not images:
            print("No valid images to embed")
            return []

        # Generate embeddings using CLIP
        print(f"Generating CLIP embeddings for {len(images)} images...")
        embeddings = self.clip_model.encode(
            images,
            show_progress_bar=True,
            convert_to_numpy=True
        ).tolist()

        print(f"Successfully generated {len(embeddings)} image embeddings")
        return embeddings

    def index_video_images(
        self,
        video_hash: str,
        segments: List[Dict]
    ) -> int:
        """
        Index video screenshot images into vector database using CLIP embeddings

        Args:
            video_hash: Unique hash of the video
            segments: List of transcription segments with screenshot_url field

        Returns:
            Number of images indexed
        """
        if not segments:
            print("No segments to index")
            return 0

        collection = self.get_or_create_image_collection(video_hash)

        # Check if already indexed
        try:
            count = collection.count()
            if count > 0:
                print(f"Image collection already has {count} items. Skipping indexing.")
                return count
        except:
            pass

        # Extract image paths from segments
        image_data = []
        for seg in segments:
            screenshot_url = seg.get('screenshot_url') or seg.get('screenshot_path')
            if screenshot_url:
                # Convert URL path to file system path
                # screenshot_url is like "/static/screenshots/hash_123.45.jpg"
                # We need to convert to "./static/screenshots/hash_123.45.jpg"
                if screenshot_url.startswith('/static/'):
                    screenshot_path = '.' + screenshot_url
                elif screenshot_url.startswith('static/'):
                    screenshot_path = './' + screenshot_url
                else:
                    screenshot_path = screenshot_url

                if os.path.exists(screenshot_path):
                    image_data.append({
                        'path': screenshot_path,
                        'segment_id': seg.get('id', ''),
                        'start': seg.get('start', 0.0),
                        'end': seg.get('end', 0.0),
                        'speaker': seg.get('speaker', 'SPEAKER_00')
                    })

        if not image_data:
            print("No valid screenshots found in segments")
            return 0

        # Generate embeddings for all images
        image_paths = [item['path'] for item in image_data]
        embeddings = self.embed_images(image_paths)

        if not embeddings:
            print("Failed to generate embeddings")
            return 0

        # Prepare data for ChromaDB
        ids = []
        metadatas = []
        documents = []  # Store screenshot paths as documents for reference

        for i, (item, embedding) in enumerate(zip(image_data, embeddings)):
            # Generate unique ID for this image
            image_id = hashlib.md5(
                f"{video_hash}_{item['segment_id']}_{item['start']}".encode()
            ).hexdigest()

            metadata = {
                "video_hash": video_hash,
                "segment_id": str(item['segment_id']),
                "start": item['start'],
                "end": item['end'],
                "speaker": item['speaker'],
                "screenshot_path": item['path']
            }

            ids.append(image_id)
            metadatas.append(metadata)
            documents.append(item['path'])  # Store path as document

        # Add to ChromaDB
        collection.add(
            embeddings=embeddings,
            documents=documents,
            metadatas=metadatas,
            ids=ids
        )

        print(f"Successfully indexed {len(embeddings)} images for video {video_hash}")
        return len(embeddings)

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
            List of relevant image segments with metadata and screenshot paths
        """
        collection = self.get_or_create_image_collection(video_hash)

        # Check if collection has data
        count = collection.count()
        if count == 0:
            print(f"Image collection for video {video_hash} is empty")
            return []

        # Generate query embedding using CLIP (text encoder)
        print(f"Encoding text query with CLIP: {query}")
        query_embedding = self.clip_model.encode(
            [query],
            convert_to_numpy=True
        ).tolist()[0]

        # Build where clause for speaker filtering
        where_clause = None
        if speaker_filter:
            where_clause = {"speaker": speaker_filter}
            print(f"Filtering images by speaker: {speaker_filter}")

        # Search in ChromaDB
        results = collection.query(
            query_embeddings=[query_embedding],
            n_results=min(n_results, count),
            where=where_clause
        )

        # Format results
        formatted_results = []
        if results['documents'] and len(results['documents']) > 0:
            for i in range(len(results['documents'][0])):
                formatted_results.append({
                    "screenshot_path": results['documents'][0][i],
                    "metadata": results['metadatas'][0][i],
                    "distance": results['distances'][0][i] if 'distances' in results else None
                })

        return formatted_results

    def delete_image_collection(self, video_hash: str) -> bool:
        """
        Delete an image collection for a specific video

        Args:
            video_hash: Unique hash of the video

        Returns:
            True if successful, False otherwise
        """
        try:
            collection_name = f"video_{video_hash}_images"
            self.client.delete_collection(name=collection_name)
            print(f"Deleted image collection: {collection_name}")
            return True
        except Exception as e:
            print(f"Error deleting image collection: {str(e)}")
            return False

    def image_collection_exists(self, video_hash: str) -> bool:
        """Check if an image collection exists for a video AND has data"""
        try:
            collection_name = f"video_{video_hash}_images"
            collection = self.client.get_collection(name=collection_name)
            # Return True only if collection has items
            return collection.count() > 0
        except:
            return False


# Global vector store instance
vector_store = VectorStore()
