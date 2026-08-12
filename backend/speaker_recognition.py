"""
Speaker Recognition Module
Handles voice enrollment and speaker identification using pyannote.audio
"""

import os
import json
import numpy as np
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import torch
from threading import RLock
from pyannote.audio import Inference
from scipy.spatial.distance import cosine

class SpeakerRecognitionSystem:
    """
    Speaker Recognition System for enrolling and identifying speakers
    Uses pyannote.audio's embedding model for voice prints
    """

    def __init__(self, database_path: str = "speaker_database.json"):
        """
        Initialize the speaker recognition system

        Args:
            database_path: Path to store speaker voice prints database
        """
        self.database_path = database_path
        self._database_lock = RLock()
        self.speaker_database = self._load_database()

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

    def _load_database(self) -> Dict:
        """Load speaker database from file"""
        if os.path.exists(self.database_path):
            try:
                with open(self.database_path, 'r') as f:
                    data = json.load(f)
                    # Old flat files are quarantined instead of being exposed
                    # to every authenticated user.
                    if data and all(
                        isinstance(value, dict) and "embedding" in value
                        for value in data.values()
                    ):
                        data = {"__legacy__": data}
                    for speakers in data.values():
                        for speaker in speakers.values():
                            speaker['embedding'] = np.array(speaker['embedding'])
                    return data
            except Exception as e:
                print(f"Error loading database: {e}")
                return {}
        return {}

    def _save_database(self):
        """Save speaker database to file"""
        try:
            # Convert numpy arrays to lists for JSON serialization
            save_data = {}
            for user_id, speakers in self.speaker_database.items():
                save_data[user_id] = {}
                for name, speaker_data in speakers.items():
                    save_data[user_id][name] = {
                        'embedding': speaker_data['embedding'].tolist(),
                        'samples_count': speaker_data['samples_count']
                    }

            with open(self.database_path, 'w') as f:
                json.dump(save_data, f, indent=2)
            print(f"Speaker database saved to {self.database_path}")
        except Exception as e:
            print(f"Error saving database: {e}")

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

            with self._database_lock:
                speakers = self.speaker_database.setdefault(user_id, {})
                if speaker_name in speakers:
                    print(f"Updating existing speaker: {speaker_name}")
                    old_embedding = speakers[speaker_name]['embedding']
                    old_count = speakers[speaker_name]['samples_count']
                    new_embedding = (old_embedding * old_count + embedding) / (old_count + 1)
                    speakers[speaker_name] = {
                        'embedding': new_embedding,
                        'samples_count': old_count + 1
                    }
                else:
                    print(f"Adding new speaker: {speaker_name}")
                    speakers[speaker_name] = {
                        'embedding': embedding,
                        'samples_count': 1
                    }
                self._save_database()
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
            with self._database_lock:
                speakers = {
                    name: {
                        "embedding": data["embedding"].copy(),
                        "samples_count": data["samples_count"],
                    }
                    for name, data in self.speaker_database.get(user_id, {}).items()
                }
            if not speakers:
                print("No speakers enrolled in database")
                return None, 0.0

            # Extract embedding from audio
            embedding = self.extract_embedding(audio_path, start_time, end_time)

            # Compare with all enrolled speakers
            similarities = {}
            for speaker_name, speaker_data in speakers.items():
                stored_embedding = speaker_data['embedding']

                # Calculate cosine similarity (1 = identical, 0 = completely different)
                similarity = 1 - cosine(embedding, stored_embedding)
                similarities[speaker_name] = similarity

            # Find best match
            best_speaker = max(similarities, key=similarities.get)
            best_similarity = similarities[best_speaker]

            print(f"Similarities: {similarities}")
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
        with self._database_lock:
            speakers = self.speaker_database.get(user_id, {})
            if speaker_name in speakers:
                del speakers[speaker_name]
                self._save_database()
                print(f"Removed speaker: {speaker_name}")
                return True
        return False

    def list_speakers(self, user_id: str) -> List[str]:
        """Get list of all enrolled speakers"""
        with self._database_lock:
            return list(self.speaker_database.get(user_id, {}).keys())

    def get_speaker_info(self, user_id: str, speaker_name: str) -> Optional[Dict]:
        """Get information about a speaker"""
        with self._database_lock:
            speakers = self.speaker_database.get(user_id, {})
            if speaker_name in speakers:
                return {
                    'name': speaker_name,
                    'samples_count': speakers[speaker_name]['samples_count'],
                    'embedding_shape': speakers[speaker_name]['embedding'].shape
                }
        return None


# Global instance
_speaker_recognition_system = None

def get_speaker_recognition_system() -> SpeakerRecognitionSystem:
    """Get or create the global speaker recognition system instance"""
    global _speaker_recognition_system
    if _speaker_recognition_system is None:
        _speaker_recognition_system = SpeakerRecognitionSystem()
    return _speaker_recognition_system


# Example usage
