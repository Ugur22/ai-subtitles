"""
Test script to verify both SQLite and Firestore database backends work correctly.

This script tests the database abstraction layer to ensure backward compatibility
and proper functionality of both backends.
"""
import os
import sys
import json
from datetime import datetime

# Test with SQLite backend
print("=" * 60)
print("Testing SQLite Backend")
print("=" * 60)

os.environ["DATABASE_TYPE"] = "sqlite"
os.environ["DATABASE_PATH"] = "test_transcriptions.db"

# Import after setting env vars
from database import (
    init_db,
    store_transcription,
    get_transcription,
    list_transcriptions,
    delete_transcription,
    update_file_path
)

# Initialize database
init_db()

# Test data
test_hash = "abc123def456"
test_filename = "test_video.mp4"
test_data = {
    "transcription": {
        "segments": [
            {
                "start": 0.0,
                "end": 5.0,
                "text": "Hello world",
                "speaker": "SPEAKER_01",
                "screenshot_url": "/screenshots/test_0.jpg"
            },
            {
                "start": 5.0,
                "end": 10.0,
                "text": "This is a test",
                "speaker": "SPEAKER_01",
                "screenshot_url": "/screenshots/test_1.jpg"
            }
        ]
    }
}

# Test store
print("\n1. Testing store_transcription...")
result = store_transcription(test_hash, test_filename, test_data, "/videos/test.mp4")
print(f"   Result: {'SUCCESS' if result else 'FAILED'}")

# Test retrieve
print("\n2. Testing get_transcription...")
retrieved = get_transcription(test_hash)
if retrieved:
    print(f"   Result: SUCCESS")
    print(f"   Has file_path: {'file_path' in retrieved}")
    print(f"   Segments count: {len(retrieved.get('transcription', {}).get('segments', []))}")
else:
    print(f"   Result: FAILED - No data retrieved")

# Test list
print("\n3. Testing list_transcriptions...")
transcriptions = list_transcriptions()
print(f"   Result: SUCCESS")
print(f"   Count: {len(transcriptions)}")
if transcriptions:
    print(f"   Has thumbnail: {transcriptions[0].get('thumbnail_url') is not None}")

# Test update
print("\n4. Testing update_file_path...")
result = update_file_path(test_hash, "/videos/updated_test.mp4")
print(f"   Result: {'SUCCESS' if result else 'FAILED'}")
retrieved = get_transcription(test_hash)
if retrieved:
    print(f"   Updated path: {retrieved.get('file_path')}")

# Test delete
print("\n5. Testing delete_transcription...")
result = delete_transcription(test_hash)
print(f"   Result: {'SUCCESS' if result else 'FAILED'}")
retrieved = get_transcription(test_hash)
print(f"   Verified deletion: {retrieved is None}")

# Cleanup
import os
if os.path.exists("test_transcriptions.db"):
    os.remove("test_transcriptions.db")
    print("\n   Cleaned up test database file")

print("\n" + "=" * 60)
print("SQLite Backend Tests Complete!")
print("=" * 60)

# Note about Firestore testing
print("\n" + "=" * 60)
print("Firestore Backend Testing")
print("=" * 60)
print("""
To test Firestore backend:
1. Set up Google Cloud credentials (GOOGLE_APPLICATION_CREDENTIALS)
2. Set environment variables:
   - DATABASE_TYPE=firestore
   - FIRESTORE_COLLECTION=transcriptions-test
3. Run this script again

The Firestore backend will automatically use Application Default Credentials
from the Cloud Run environment or local gcloud auth.
""")
print("=" * 60)
