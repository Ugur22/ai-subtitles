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
            print(f"Using token: {hf_token[:10]}...")

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
                    # Convert lists back to numpy arrays
                    for speaker in data.values():
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
            for name, speaker_data in self.speaker_database.items():
                save_data[name] = {
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

    def enroll_speaker(self, speaker_name: str, audio_path: str,
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

            if speaker_name in self.speaker_database:
                # Update existing speaker - average with existing embedding
                print(f"Updating existing speaker: {speaker_name}")
                old_embedding = self.speaker_database[speaker_name]['embedding']
                old_count = self.speaker_database[speaker_name]['samples_count']

                # Weighted average of embeddings
                new_embedding = (old_embedding * old_count + embedding) / (old_count + 1)

                self.speaker_database[speaker_name] = {
                    'embedding': new_embedding,
                    'samples_count': old_count + 1
                }
            else:
                # New speaker
                print(f"Adding new speaker: {speaker_name}")
                self.speaker_database[speaker_name] = {
                    'embedding': embedding,
                    'samples_count': 1
                }

            # Save to disk
            self._save_database()
            print(f"Successfully enrolled {speaker_name}")
            return True

        except Exception as e:
            print(f"Error enrolling speaker {speaker_name}: {e}")
            return False

    def identify_speaker(self, audio_path: str, start_time: float = None,
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
            if not self.speaker_database:
                print("No speakers enrolled in database")
                return None, 0.0

            # Extract embedding from audio
            embedding = self.extract_embedding(audio_path, start_time, end_time)

            # Compare with all enrolled speakers
            similarities = {}
            for speaker_name, speaker_data in self.speaker_database.items():
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

    def remove_speaker(self, speaker_name: str) -> bool:
        """Remove a speaker from the database"""
        if speaker_name in self.speaker_database:
            del self.speaker_database[speaker_name]
            self._save_database()
            print(f"Removed speaker: {speaker_name}")
            return True
        return False

    def list_speakers(self) -> List[str]:
        """Get list of all enrolled speakers"""
        return list(self.speaker_database.keys())

    def get_speaker_info(self, speaker_name: str) -> Optional[Dict]:
        """Get information about a speaker"""
        if speaker_name in self.speaker_database:
            return {
                'name': speaker_name,
                'samples_count': self.speaker_database[speaker_name]['samples_count'],
                'embedding_shape': self.speaker_database[speaker_name]['embedding'].shape
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
if __name__ == "__main__":
    # Initialize system
    sr_system = SpeakerRecognitionSystem()

    # Example: Enroll a speaker
    # sr_system.enroll_speaker("John", "path/to/john_voice.wav")

    # Example: Identify a speaker
    # speaker, confidence = sr_system.identify_speaker("path/to/unknown_voice.wav")
    # print(f"Identified: {speaker} (confidence: {confidence:.2f})")

    # List enrolled speakers
    print(f"Enrolled speakers: {sr_system.list_speakers()}")
