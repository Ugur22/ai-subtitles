"""
Database operations for transcription storage using SQLite
"""
import sqlite3
import json
from typing import Dict, List, Optional
from contextlib import contextmanager

from config import settings


@contextmanager
def get_db_connection():
    """Context manager for database connections"""
    conn = sqlite3.connect(settings.DATABASE_PATH)
    try:
        yield conn
    finally:
        conn.close()


def init_db():
    """Initialize the SQLite database for storing transcriptions"""
    with get_db_connection() as conn:
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
    print("Database initialized successfully")


def store_transcription(video_hash: str, filename: str, transcription_data: Dict, file_path: Optional[str] = None) -> bool:
    """Store transcription data in the database"""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT OR REPLACE INTO transcriptions (video_hash, filename, file_path, transcription_data) VALUES (?, ?, ?, ?)",
                (video_hash, filename, file_path, json.dumps(transcription_data))
            )
            conn.commit()
        print(f"Stored transcription for {filename} with hash {video_hash}")
        return True
    except Exception as e:
        print(f"Error storing transcription: {str(e)}")
        return False


def get_transcription(video_hash: str) -> Optional[Dict]:
    """Retrieve transcription data from the database by hash"""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT transcription_data, file_path FROM transcriptions WHERE video_hash = ?", (video_hash,))
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
        print(f"Error retrieving transcription: {str(e)}")
        return None


def list_transcriptions() -> List[Dict]:
    """List all saved transcriptions with metadata and thumbnails"""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT video_hash, filename, created_at, file_path, transcription_data FROM transcriptions ORDER BY created_at DESC")

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
        print(f"Error listing transcriptions: {str(e)}")
        raise


def update_file_path(video_hash: str, file_path: str) -> bool:
    """Update the file path for an existing transcription"""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE transcriptions SET file_path = ? WHERE video_hash = ?",
                (file_path, video_hash)
            )
            conn.commit()
        return True
    except Exception as e:
        print(f"Error updating file path: {str(e)}")
        return False


def delete_transcription(video_hash: str) -> bool:
    """Delete a transcription from the database"""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM transcriptions WHERE video_hash = ?", (video_hash,))
            conn.commit()
        return True
    except Exception as e:
        print(f"Error deleting transcription: {str(e)}")
        return False
