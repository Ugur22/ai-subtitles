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
from pathlib import Path

# Get the backend directory path for resolving relative paths
BACKEND_DIR = Path(__file__).parent.absolute()


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
        segments: List[Dict],
        force_reindex: bool = False
    ) -> int:
        """
        Index video screenshot images into vector database using CLIP embeddings

        Args:
            video_hash: Unique hash of the video
            segments: List of transcription segments with screenshot_url field
            force_reindex: If True, delete existing collection and re-index

        Returns:
            Number of images indexed
        """
        if not segments:
            print("No segments to index")
            return 0

        # Handle force re-indexing by deleting existing collection
        if force_reindex:
            try:
                collection_name = f"images_{video_hash}"
                self.chroma_client.delete_collection(collection_name)
                print(f"Deleted existing image collection for force re-index: {collection_name}")
            except Exception as e:
                print(f"No existing collection to delete or error: {e}")

        collection = self.get_or_create_image_collection(video_hash)

        # Check if already indexed (skip if force_reindex since we just deleted it)
        if not force_reindex:
            try:
                count = collection.count()
                if count > 0:
                    print(f"Image collection already has {count} items. Skipping indexing.")
                    return count
            except:
                pass

        # Extract image paths from segments
        image_data = []
        segments_with_urls = 0
        missing_files = 0

        for seg in segments:
            screenshot_url = seg.get('screenshot_url') or seg.get('screenshot_path')
            if screenshot_url:
                segments_with_urls += 1
                # Convert URL path to absolute file system path
                # screenshot_url is like "/static/screenshots/hash_123.45.jpg"
                # We need to convert to absolute path based on backend directory
                if screenshot_url.startswith('/static/'):
                    screenshot_path = str(BACKEND_DIR / screenshot_url.lstrip('/'))
                elif screenshot_url.startswith('static/'):
                    screenshot_path = str(BACKEND_DIR / screenshot_url)
                elif screenshot_url.startswith('./'):
                    screenshot_path = str(BACKEND_DIR / screenshot_url.lstrip('./'))
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
                else:
                    missing_files += 1
                    if missing_files <= 3:  # Only log first 3 to avoid spam
                        print(f"Warning: Screenshot file not found: {screenshot_path}")

        print(f"Screenshot analysis: {segments_with_urls} segments have URLs, {len(image_data)} files exist, {missing_files} files missing")

        if not image_data:
            if segments_with_urls == 0:
                print("No screenshots found in segments - segments may not have screenshot_url field")
            else:
                print(f"No valid screenshots found - all {segments_with_urls} screenshot files are missing")
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
                # Convert absolute path back to URL for frontend/LLM use
                abs_path = results['documents'][0][i]
                if 'static/screenshots/' in abs_path:
                    # Extract filename from absolute path
                    filename = abs_path.split('static/screenshots/')[-1]
                    screenshot_url = f"/static/screenshots/{filename}"
                else:
                    # Fallback: use as-is
                    screenshot_url = abs_path

                formatted_results.append({
                    "screenshot_path": screenshot_url,  # Return URL, not absolute path
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

    def get_or_create_audio_collection(self, video_hash: str) -> chromadb.Collection:
        """
        Get or create an audio event collection for a specific video

        Args:
            video_hash: Unique hash of the video

        Returns:
            ChromaDB collection for audio events
        """
        collection_name = f"video_{video_hash}_audio"
        try:
            collection = self.client.get_collection(name=collection_name)
            print(f"Retrieved existing audio collection: {collection_name}")
        except:
            collection = self.client.create_collection(
                name=collection_name,
                metadata={"video_hash": video_hash, "type": "audio_events"}
            )
            print(f"Created new audio collection: {collection_name}")

        return collection

    def index_audio_events(
        self,
        video_hash: str,
        segments: List[Dict],
        force_reindex: bool = False
    ) -> int:
        """
        Index audio events from transcription segments into vector database

        Args:
            video_hash: Unique hash of the video
            segments: List of transcription segments with audio_events or audio_analysis
            force_reindex: If True, delete existing collection and re-index

        Returns:
            Number of audio events indexed
        """
        if not segments:
            print("No segments to index")
            return 0

        # Handle force re-indexing by deleting existing collection
        if force_reindex:
            try:
                collection_name = f"video_{video_hash}_audio"
                self.client.delete_collection(collection_name)
                print(f"Deleted existing audio collection for force re-index: {collection_name}")
            except Exception as e:
                print(f"No existing collection to delete or error: {e}")

        collection = self.get_or_create_audio_collection(video_hash)

        # Check if already indexed (skip if force_reindex since we just deleted it)
        if not force_reindex:
            try:
                count = collection.count()
                if count > 0:
                    print(f"Audio collection already has {count} items. Skipping indexing.")
                    return count
            except:
                pass

        # Extract audio events from segments
        audio_data = []
        segments_with_audio = 0

        for seg in segments:
            audio_events = seg.get('audio_events')
            audio_analysis = seg.get('audio_analysis')

            if audio_events or audio_analysis:
                segments_with_audio += 1

                # Build text description from audio events
                event_descriptions = []
                primary_event = None
                speech_emotion = None
                has_speech = False

                if audio_events:
                    # audio_events is a list of dicts: [{"event_type": str, "confidence": float}, ...]
                    # Sort events by confidence (descending)
                    sorted_events = sorted(
                        audio_events,
                        key=lambda x: x.get('confidence', 0),
                        reverse=True
                    )

                    # Create description from top events
                    for event in sorted_events:
                        event_type = event.get('event_type', 'unknown')
                        confidence = event.get('confidence', 0)
                        if confidence > 0.1:  # Only include events with >10% confidence
                            event_descriptions.append(
                                f"{event_type} ({confidence*100:.0f}%)"
                            )

                    # Get primary event (highest confidence)
                    if sorted_events:
                        primary_event = sorted_events[0].get('event_type', 'unknown')

                if audio_analysis:
                    has_speech = audio_analysis.get('has_speech', False)
                    speech_emotion_data = audio_analysis.get('speech_emotion')

                    # Add speech emotion to description if available
                    # speech_emotion is a dict like {"emotion": "happy", "confidence": 0.85}
                    if speech_emotion_data and isinstance(speech_emotion_data, dict):
                        speech_emotion = speech_emotion_data.get('emotion', 'unknown')
                        emotion_confidence = speech_emotion_data.get('confidence', 0)
                        event_descriptions.append(f"emotion: {speech_emotion} ({emotion_confidence*100:.0f}%)")
                    else:
                        speech_emotion = None

                # Skip if no meaningful events
                if not event_descriptions:
                    continue

                # Combine into searchable text
                description_text = ", ".join(event_descriptions)

                audio_data.append({
                    'text': description_text,
                    'segment_id': seg.get('id', ''),
                    'start': seg.get('start', 0.0),
                    'end': seg.get('end', 0.0),
                    'speaker': seg.get('speaker', 'SPEAKER_00'),
                    'has_speech': has_speech,
                    'primary_event': primary_event or 'unknown',
                    'speech_emotion': speech_emotion or 'unknown'
                })

        print(f"Audio analysis: {segments_with_audio} segments have audio events, {len(audio_data)} valid events to index")

        if not audio_data:
            print("No valid audio events found in segments")
            return 0

        # Generate embeddings for audio event descriptions
        texts = [item['text'] for item in audio_data]
        print(f"Generating embeddings for {len(texts)} audio event descriptions...")
        embeddings = self.embedding_model.encode(
            texts,
            show_progress_bar=True,
            convert_to_numpy=True
        ).tolist()

        # Prepare data for ChromaDB
        ids = []
        metadatas = []
        documents = []

        for item, embedding in zip(audio_data, embeddings):
            # Generate unique ID for this audio event
            audio_id = hashlib.md5(
                f"{video_hash}_{item['segment_id']}_{item['start']}".encode()
            ).hexdigest()

            metadata = {
                "video_hash": video_hash,
                "segment_id": str(item['segment_id']),
                "start": item['start'],
                "end": item['end'],
                "speaker": item['speaker'],
                "has_speech": str(item['has_speech']),
                "primary_event": item['primary_event'],
                "speech_emotion": item['speech_emotion']
            }

            ids.append(audio_id)
            metadatas.append(metadata)
            documents.append(item['text'])

        # Add to ChromaDB
        collection.add(
            embeddings=embeddings,
            documents=documents,
            metadatas=metadatas,
            ids=ids
        )

        print(f"Successfully indexed {len(embeddings)} audio events for video {video_hash}")
        return len(embeddings)

    def search_audio_events(
        self,
        video_hash: str,
        query: str,
        n_results: int = 5
    ) -> List[Dict]:
        """
        Search for relevant audio events using semantic similarity

        Args:
            video_hash: Unique hash of the video
            query: Search query (e.g., "laughter", "applause", "sad emotion")
            n_results: Number of results to return

        Returns:
            List of relevant audio event segments with metadata
        """
        collection = self.get_or_create_audio_collection(video_hash)

        # Check if collection has data
        count = collection.count()
        if count == 0:
            print(f"Audio collection for video {video_hash} is empty")
            return []

        # Generate query embedding
        print(f"Searching audio events for: {query}")
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
                    "description": results['documents'][0][i],
                    "metadata": results['metadatas'][0][i],
                    "distance": results['distances'][0][i] if 'distances' in results else None
                })

        return formatted_results

    def audio_collection_exists(self, video_hash: str) -> bool:
        """Check if an audio collection exists for a video AND has data"""
        try:
            collection_name = f"video_{video_hash}_audio"
            collection = self.client.get_collection(name=collection_name)
            # Return True only if collection has items
            return collection.count() > 0
        except:
            return False

    def delete_audio_collection(self, video_hash: str) -> bool:
        """
        Delete an audio collection for a specific video

        Args:
            video_hash: Unique hash of the video

        Returns:
            True if successful, False otherwise
        """
        try:
            collection_name = f"video_{video_hash}_audio"
            self.client.delete_collection(name=collection_name)
            print(f"Deleted audio collection: {collection_name}")
            return True
        except Exception as e:
            print(f"Error deleting audio collection: {str(e)}")
            return False

    def update_speaker_name(
        self,
        video_hash: str,
        old_speaker: str,
        new_speaker: str
    ) -> Dict[str, int]:
        """
        Update speaker name in vector store metadata for both text and image collections

        Args:
            video_hash: Unique hash of the video
            old_speaker: Original speaker name/label to replace
            new_speaker: New speaker name

        Returns:
            Dict with counts of updated items in text and image collections
        """
        results = {
            "text_updated": 0,
            "images_updated": 0
        }

        # Update text collection (video_{hash})
        try:
            collection_name = f"video_{video_hash}"
            collection = self.client.get_collection(name=collection_name)

            # Get all items in the collection
            all_items = collection.get(
                include=["metadatas"]
            )

            if all_items and all_items['ids']:
                # Find items with the old speaker name
                ids_to_update = []
                updated_metadatas = []

                for i, metadata in enumerate(all_items['metadatas']):
                    if metadata.get('speaker') == old_speaker:
                        ids_to_update.append(all_items['ids'][i])
                        # Create updated metadata
                        new_metadata = metadata.copy()
                        new_metadata['speaker'] = new_speaker
                        updated_metadatas.append(new_metadata)

                # Update the items with new metadata
                if ids_to_update:
                    collection.update(
                        ids=ids_to_update,
                        metadatas=updated_metadatas
                    )
                    results['text_updated'] = len(ids_to_update)
                    print(f"Updated {len(ids_to_update)} text chunks from '{old_speaker}' to '{new_speaker}'")

        except Exception as e:
            print(f"Error updating text collection: {str(e)}")

        # Update image collection (video_{hash}_images)
        try:
            collection_name = f"video_{video_hash}_images"
            collection = self.client.get_collection(name=collection_name)

            # Get all items in the collection
            all_items = collection.get(
                include=["metadatas"]
            )

            if all_items and all_items['ids']:
                # Find items with the old speaker name
                ids_to_update = []
                updated_metadatas = []

                for i, metadata in enumerate(all_items['metadatas']):
                    if metadata.get('speaker') == old_speaker:
                        ids_to_update.append(all_items['ids'][i])
                        # Create updated metadata
                        new_metadata = metadata.copy()
                        new_metadata['speaker'] = new_speaker
                        updated_metadatas.append(new_metadata)

                # Update the items with new metadata
                if ids_to_update:
                    collection.update(
                        ids=ids_to_update,
                        metadatas=updated_metadatas
                    )
                    results['images_updated'] = len(ids_to_update)
                    print(f"Updated {len(ids_to_update)} images from '{old_speaker}' to '{new_speaker}'")

        except Exception as e:
            print(f"Error updating image collection: {str(e)}")

        return results


# Global vector store instance
vector_store = VectorStore()
