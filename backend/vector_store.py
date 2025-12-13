"""
Vector Store for RAG (Retrieval-Augmented Generation)
Uses ChromaDB for storing and retrieving transcript embeddings
"""

import os
import chromadb
from chromadb.config import Settings
from sentence_transformers import SentenceTransformer
from typing import List, Dict, Optional
import hashlib


class VectorStore:
    """Manages vector embeddings for transcription segments"""

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

        # Initialize embedding model
        print("Loading embedding model (sentence-transformers)...")
        self.embedding_model = SentenceTransformer('all-MiniLM-L6-v2')
        print("Embedding model loaded successfully")

        # Default collection name
        self.collection_name = "transcriptions"

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


# Global vector store instance
vector_store = VectorStore()
