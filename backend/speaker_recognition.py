"""
Speaker Recognition Module
Handles voice enrollment and speaker identification using pyannote.audio

Voiceprints are persisted in Supabase (speaker_voiceprints table) rather than
local disk - the backend runs on Cloud Run with min-instances=0, so anything
written to local disk is destroyed every time the container scales to zero.
"""

import os
import threading
import numpy as np
from typing import Dict, List, Optional, Tuple
import torch
from pyannote.audio import Inference

from services.supabase_service import SupabaseService

EMBEDDING_DIM = 512  # pyannote/embedding output size


class SpeakerRecognitionSystem:
    """
    Speaker Recognition System for enrolling and identifying speakers
    Uses pyannote.audio's embedding model for voice prints
    """

    def __init__(self):
        """Initialize the speaker recognition system"""
        # Initialize pyannote embedding model
        # This extracts voice embeddings (voice prints)
        try:
            # Load environment variables
            from dotenv import load_dotenv
            load_dotenv()

            hf_token = os.getenv("HUGGINGFACE_TOKEN")
            if not hf_token:
                raise ValueError("HUGGINGFACE_TOKEN not found in environment variables")

            print("Loading speaker embedding model...")

            self.embedding_model = Inference(
                "pyannote/embedding",
                use_auth_token=hf_token
            )
            print("Speaker embedding model loaded successfully")
        except Exception as e:
            print(f"Error loading embedding model: {e}")
            print("You may need to accept pyannote.audio model conditions at:")
            print("https://huggingface.co/pyannote/embedding")
            raise

    def extract_embedding(self, audio_path: str, start_time: float = None,
                         end_time: float = None) -> np.ndarray:
        """
        Extract voice embedding (voice print) from audio

        Args:
            audio_path: Path to audio file
            start_time: Start time in seconds (optional)
            end_time: End time in seconds (optional)

        Returns:
            numpy array representing the voice embedding
        """
        try:
            if start_time is not None and end_time is not None:
                # Extract embedding from specific segment
                from pyannote.core import Segment
                segment = Segment(start_time, end_time)
                embedding = self.embedding_model({
                    'uri': audio_path,
                    'audio': audio_path
                }, segment)
            else:
                # Extract embedding from entire file
                embedding = self.embedding_model(audio_path)

            return embedding
        except Exception as e:
            print(f"Error extracting embedding: {e}")
            raise

    def enroll_speaker(self, user_id: str, speaker_name: str, audio_path: str,
                      start_time: float = None, end_time: float = None) -> bool:
        """
        Enroll a new speaker or add a sample to existing speaker

        Args:
            speaker_name: Name of the speaker (e.g., "John", "Anna")
            audio_path: Path to audio file with this speaker's voice
            start_time: Start time in seconds (if using segment)
            end_time: End time in seconds (if using segment)

        Returns:
            True if enrollment successful
        """
        try:
            print(f"Enrolling speaker: {speaker_name}")

            # Extract embedding
            embedding = self.extract_embedding(audio_path, start_time, end_time)

            client = SupabaseService.get_client()
            existing = (
                client.table("speaker_voiceprints")
                .select("embedding, samples_count")
                .eq("user_id", user_id)
                .eq("speaker_name", speaker_name)
                .execute()
            )

            if existing.data:
                print(f"Updating existing speaker: {speaker_name}")
                row = existing.data[0]
                old_embedding = _parse_embedding(row["embedding"])
                old_count = row["samples_count"]
                new_embedding = (old_embedding * old_count + embedding) / (old_count + 1)
                client.table("speaker_voiceprints").update({
                    "embedding": new_embedding.tolist(),
                    "samples_count": old_count + 1,
                }).eq("user_id", user_id).eq("speaker_name", speaker_name).execute()
            else:
                print(f"Adding new speaker: {speaker_name}")
                client.table("speaker_voiceprints").insert({
                    "user_id": user_id,
                    "speaker_name": speaker_name,
                    "embedding": embedding.tolist(),
                    "samples_count": 1,
                }).execute()

            print(f"Successfully enrolled {speaker_name}")
            return True

        except Exception as e:
            print(f"Error enrolling speaker {speaker_name}: {e}")
            return False

    def identify_speaker(self, user_id: str, audio_path: str, start_time: float = None,
                        end_time: float = None, threshold: float = 0.7) -> Tuple[Optional[str], float]:
        """
        Identify speaker from audio segment

        Args:
            audio_path: Path to audio file
            start_time: Start time in seconds (if using segment)
            end_time: End time in seconds (if using segment)
            threshold: Similarity threshold (0.0 to 1.0). Higher = more strict

        Returns:
            Tuple of (speaker_name, confidence) or (None, 0.0) if no match
        """
        try:
            client = SupabaseService.get_client()
            has_speakers = (
                client.table("speaker_voiceprints")
                .select("id")
                .eq("user_id", user_id)
                .limit(1)
                .execute()
            )
            if not has_speakers.data:
                print("No speakers enrolled in database")
                return None, 0.0

            # Extract embedding from audio
            embedding = self.extract_embedding(audio_path, start_time, end_time)

            result = client.rpc("search_speaker_voiceprints_by_embedding", {
                "p_user_id": user_id,
                "query_embedding": embedding.tolist(),
                "match_count": 1,
            }).execute()

            if not result.data:
                print("No speakers enrolled in database")
                return None, 0.0

            best = result.data[0]
            best_speaker = best["speaker_name"]
            best_similarity = best["similarity"]

            print(f"Best match: {best_speaker} ({best_similarity:.3f})")

            # Check if similarity meets threshold
            if best_similarity >= threshold:
                return best_speaker, best_similarity
            else:
                print(f"No confident match (best similarity: {best_similarity:.3f} < threshold: {threshold})")
                return None, best_similarity

        except Exception as e:
            print(f"Error identifying speaker: {e}")
            return None, 0.0

    def remove_speaker(self, user_id: str, speaker_name: str) -> bool:
        """Remove a speaker from the database"""
        client = SupabaseService.get_client()
        result = (
            client.table("speaker_voiceprints")
            .delete()
            .eq("user_id", user_id)
            .eq("speaker_name", speaker_name)
            .execute()
        )
        removed = bool(result.data)
        if removed:
            print(f"Removed speaker: {speaker_name}")
        return removed

    def list_speakers(self, user_id: str) -> List[str]:
        """Get list of all enrolled speakers"""
        client = SupabaseService.get_client()
        result = (
            client.table("speaker_voiceprints")
            .select("speaker_name")
            .eq("user_id", user_id)
            .execute()
        )
        return [row["speaker_name"] for row in result.data]

    def get_speaker_info(self, user_id: str, speaker_name: str) -> Optional[Dict]:
        """Get information about a speaker"""
        client = SupabaseService.get_client()
        result = (
            client.table("speaker_voiceprints")
            .select("samples_count")
            .eq("user_id", user_id)
            .eq("speaker_name", speaker_name)
            .execute()
        )
        if result.data:
            return {
                'name': speaker_name,
                'samples_count': result.data[0]['samples_count'],
                'embedding_shape': (EMBEDDING_DIM,)
            }
        return None


def _parse_embedding(value) -> np.ndarray:
    """Parse a pgvector column value (list or Postgres text form) into an ndarray."""
    if isinstance(value, str):
        value = [float(x) for x in value.strip("[]").split(",")]
    return np.array(value, dtype=np.float64)


# Global instance
_speaker_recognition_system = None
_speaker_recognition_system_lock = threading.Lock()

def get_speaker_recognition_system() -> SpeakerRecognitionSystem:
    """Get or create the global speaker recognition system instance"""
    global _speaker_recognition_system
    if _speaker_recognition_system is None:
        with _speaker_recognition_system_lock:
            if _speaker_recognition_system is None:
                _speaker_recognition_system = SpeakerRecognitionSystem()
    return _speaker_recognition_system


# Example usage
