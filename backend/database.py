"""
Database operations for transcription storage with SQLite and Firestore backends
"""
import sqlite3
import json
from abc import ABC, abstractmethod
from typing import Dict, List, Optional
from contextlib import contextmanager
from datetime import datetime

from config import settings


class DatabaseBackend(ABC):
    """Abstract base class for database backends"""

    @abstractmethod
    def init(self) -> None:
        """Initialize the database backend"""
        pass

    @abstractmethod
    def store_transcription(
        self,
        video_hash: str,
        filename: str,
        transcription_data: Dict,
        file_path: Optional[str] = None
    ) -> bool:
        """Store transcription data in the database"""
        pass

    @abstractmethod
    def get_transcription(self, video_hash: str) -> Optional[Dict]:
        """Retrieve transcription data from the database by hash"""
        pass

    @abstractmethod
    def list_transcriptions(self) -> List[Dict]:
        """List all saved transcriptions with metadata and thumbnails"""
        pass

    @abstractmethod
    def delete_transcription(self, video_hash: str) -> bool:
        """Delete a transcription from the database"""
        pass

    @abstractmethod
    def update_file_path(self, video_hash: str, file_path: str) -> bool:
        """Update the file path for an existing transcription"""
        pass


class SQLiteBackend(DatabaseBackend):
    """SQLite database backend for local development"""

    def __init__(self, database_path: str):
        self.database_path = database_path

    @contextmanager
    def _get_connection(self):
        """Context manager for database connections"""
        conn = sqlite3.connect(self.database_path)
        try:
            yield conn
        finally:
            conn.close()

    def init(self) -> None:
        """Initialize the SQLite database for storing transcriptions"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS transcriptions (
                video_hash TEXT PRIMARY KEY,
                filename TEXT,
                file_path TEXT,
                transcription_data TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            ''')
            conn.commit()
        print("SQLite database initialized successfully")

    def store_transcription(
        self,
        video_hash: str,
        filename: str,
        transcription_data: Dict,
        file_path: Optional[str] = None
    ) -> bool:
        """Store transcription data in SQLite"""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "INSERT OR REPLACE INTO transcriptions (video_hash, filename, file_path, transcription_data) VALUES (?, ?, ?, ?)",
                    (video_hash, filename, file_path, json.dumps(transcription_data))
                )
                conn.commit()
            print(f"Stored transcription for {filename} with hash {video_hash}")
            return True
        except Exception as e:
            print(f"Error storing transcription in SQLite: {str(e)}")
            return False

    def get_transcription(self, video_hash: str) -> Optional[Dict]:
        """Retrieve transcription data from SQLite by hash"""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT transcription_data, file_path FROM transcriptions WHERE video_hash = ?",
                    (video_hash,)
                )
                result = cursor.fetchone()

                if result:
                    transcription_data = json.loads(result[0])
                    file_path = result[1]
                    # Add file_path to the transcription data
                    if file_path:
                        transcription_data['file_path'] = file_path
                    return transcription_data
                return None
        except Exception as e:
            print(f"Error retrieving transcription from SQLite: {str(e)}")
            return None

    def list_transcriptions(self) -> List[Dict]:
        """List all saved transcriptions from SQLite with metadata and thumbnails"""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT video_hash, filename, created_at, file_path, transcription_data "
                    "FROM transcriptions ORDER BY created_at DESC"
                )

                transcriptions = []
                for row in cursor.fetchall():
                    video_hash, filename, created_at, file_path, transcription_data_json = row

                    thumbnail_url = None
                    if transcription_data_json:
                        try:
                            transcription_data = json.loads(transcription_data_json)
                            # Find a segment from the middle with a screenshot URL
                            segments = transcription_data.get("transcription", {}).get("segments", [])
                            segments_with_screenshots = [s for s in segments if s.get("screenshot_url")]

                            if segments_with_screenshots:
                                # Get the middle segment's screenshot
                                middle_index = len(segments_with_screenshots) // 2
                                thumbnail_url = segments_with_screenshots[middle_index].get("screenshot_url")

                        except (json.JSONDecodeError, KeyError):
                            pass  # Ignore if data is not valid JSON or keys are missing

                    transcriptions.append({
                        "video_hash": video_hash,
                        "filename": filename,
                        "created_at": created_at,
                        "file_path": file_path,
                        "thumbnail_url": thumbnail_url
                    })

                return transcriptions
        except Exception as e:
            print(f"Error listing transcriptions from SQLite: {str(e)}")
            raise

    def update_file_path(self, video_hash: str, file_path: str) -> bool:
        """Update the file path for an existing transcription in SQLite"""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "UPDATE transcriptions SET file_path = ? WHERE video_hash = ?",
                    (file_path, video_hash)
                )
                conn.commit()
            return True
        except Exception as e:
            print(f"Error updating file path in SQLite: {str(e)}")
            return False

    def delete_transcription(self, video_hash: str) -> bool:
        """Delete a transcription from SQLite"""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM transcriptions WHERE video_hash = ?", (video_hash,))
                conn.commit()
            return True
        except Exception as e:
            print(f"Error deleting transcription from SQLite: {str(e)}")
            return False


class FirestoreBackend(DatabaseBackend):
    """Firestore database backend for production/Cloud Run"""

    def __init__(self, collection_name: str):
        from google.cloud import firestore
        self.db = firestore.Client()
        self.collection = self.db.collection(collection_name)
        self.firestore = firestore  # Keep reference for SERVER_TIMESTAMP

    def init(self) -> None:
        """Initialize Firestore (no schema setup needed for NoSQL)"""
        print(f"Firestore backend initialized with collection: {self.collection.id}")

    def store_transcription(
        self,
        video_hash: str,
        filename: str,
        transcription_data: Dict,
        file_path: Optional[str] = None
    ) -> bool:
        """Store transcription data in Firestore"""
        try:
            doc_data = {
                "video_hash": video_hash,
                "filename": filename,
                "file_path": file_path,
                "transcription_data": transcription_data,
                "created_at": self.firestore.SERVER_TIMESTAMP
            }

            # Use video_hash as document ID for easy retrieval
            self.collection.document(video_hash).set(doc_data)
            print(f"Stored transcription for {filename} with hash {video_hash} in Firestore")
            return True
        except Exception as e:
            print(f"Error storing transcription in Firestore: {str(e)}")
            return False

    def get_transcription(self, video_hash: str) -> Optional[Dict]:
        """Retrieve transcription data from Firestore by hash"""
        try:
            doc = self.collection.document(video_hash).get()

            if doc.exists:
                data = doc.to_dict()
                transcription_data = data.get("transcription_data", {})
                file_path = data.get("file_path")

                # Add file_path to the transcription data
                if file_path:
                    transcription_data['file_path'] = file_path

                return transcription_data
            return None
        except Exception as e:
            print(f"Error retrieving transcription from Firestore: {str(e)}")
            return None

    def list_transcriptions(self) -> List[Dict]:
        """List all saved transcriptions from Firestore with metadata and thumbnails"""
        try:
            # Query all documents, ordered by created_at descending
            docs = self.collection.order_by(
                "created_at", direction=self.firestore.Query.DESCENDING
            ).stream()

            transcriptions = []
            for doc in docs:
                data = doc.to_dict()
                video_hash = data.get("video_hash")
                filename = data.get("filename")
                file_path = data.get("file_path")
                created_at = data.get("created_at")
                transcription_data = data.get("transcription_data", {})

                # Convert Firestore timestamp to ISO string for consistency
                if created_at:
                    created_at = created_at.isoformat() if hasattr(created_at, 'isoformat') else str(created_at)

                # Extract thumbnail from middle screenshot
                thumbnail_url = None
                if transcription_data:
                    try:
                        # Find a segment from the middle with a screenshot URL
                        segments = transcription_data.get("transcription", {}).get("segments", [])
                        segments_with_screenshots = [s for s in segments if s.get("screenshot_url")]

                        if segments_with_screenshots:
                            # Get the middle segment's screenshot
                            middle_index = len(segments_with_screenshots) // 2
                            thumbnail_url = segments_with_screenshots[middle_index].get("screenshot_url")

                    except (KeyError, TypeError):
                        pass  # Ignore if keys are missing

                transcriptions.append({
                    "video_hash": video_hash,
                    "filename": filename,
                    "created_at": created_at,
                    "file_path": file_path,
                    "thumbnail_url": thumbnail_url
                })

            return transcriptions
        except Exception as e:
            print(f"Error listing transcriptions from Firestore: {str(e)}")
            raise

    def update_file_path(self, video_hash: str, file_path: str) -> bool:
        """Update the file path for an existing transcription in Firestore"""
        try:
            self.collection.document(video_hash).update({
                "file_path": file_path
            })
            return True
        except Exception as e:
            print(f"Error updating file path in Firestore: {str(e)}")
            return False

    def delete_transcription(self, video_hash: str) -> bool:
        """Delete a transcription from Firestore"""
        try:
            self.collection.document(video_hash).delete()
            return True
        except Exception as e:
            print(f"Error deleting transcription from Firestore: {str(e)}")
            return False


# Singleton backend instance
_backend: Optional[DatabaseBackend] = None


def get_database_backend() -> DatabaseBackend:
    """
    Factory function to get the appropriate database backend based on configuration.

    Returns the singleton backend instance, creating it if necessary.
    """
    global _backend

    if _backend is None:
        database_type = settings.DATABASE_TYPE.lower()

        if database_type == "firestore":
            _backend = FirestoreBackend(settings.FIRESTORE_COLLECTION)
        elif database_type == "sqlite":
            _backend = SQLiteBackend(settings.DATABASE_PATH)
        else:
            raise ValueError(f"Unsupported database type: {database_type}. Use 'sqlite' or 'firestore'")

        print(f"Initialized {database_type} database backend")

    return _backend


# Public API functions for backward compatibility
def init_db() -> None:
    """Initialize the database"""
    backend = get_database_backend()
    backend.init()


def store_transcription(
    video_hash: str,
    filename: str,
    transcription_data: Dict,
    file_path: Optional[str] = None
) -> bool:
    """Store transcription data in the database"""
    backend = get_database_backend()
    return backend.store_transcription(video_hash, filename, transcription_data, file_path)


def get_transcription(video_hash: str) -> Optional[Dict]:
    """Retrieve transcription data from the database by hash"""
    backend = get_database_backend()
    return backend.get_transcription(video_hash)


def list_transcriptions() -> List[Dict]:
    """List all saved transcriptions with metadata and thumbnails"""
    backend = get_database_backend()
    return backend.list_transcriptions()


def delete_transcription(video_hash: str) -> bool:
    """Delete a transcription from the database"""
    backend = get_database_backend()
    return backend.delete_transcription(video_hash)


def update_file_path(video_hash: str, file_path: str) -> bool:
    """Update the file path for an existing transcription"""
    backend = get_database_backend()
    return backend.update_file_path(video_hash, file_path)
