#!/usr/bin/env python3
"""
Diagnostic script to check chat images setup and identify issues.

This script checks:
1. Screenshot files in the filesystem
2. Transcriptions in the database
3. ChromaDB collections
4. Consistency between all three

Run this to diagnose "Failed to load image" errors.
"""

import os
import sys
import sqlite3
import json
from pathlib import Path

# Add parent directory to path to import modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from config import settings

try:
    import chromadb
    from chromadb.config import Settings as ChromaSettings
    CHROMADB_AVAILABLE = True
except ImportError:
    CHROMADB_AVAILABLE = False
    print("Warning: ChromaDB not available. Install with: pip install chromadb")


def check_screenshots():
    """Check screenshot files in the filesystem."""
    screenshots_dir = settings.SCREENSHOTS_DIR
    print(f"\n{'='*60}")
    print("1. SCREENSHOT FILES")
    print(f"{'='*60}")
    print(f"Screenshots directory: {screenshots_dir}")

    if not os.path.exists(screenshots_dir):
        print("  Status: Directory does not exist")
        return []

    files = [f for f in os.listdir(screenshots_dir) if f.endswith('.jpg')]
    print(f"  Status: {len(files)} screenshot files found")

    if files:
        # Group by video hash
        hashes = {}
        for f in files:
            # Extract hash from filename (format: hash_123.45.jpg)
            parts = f.split('_')
            if len(parts) >= 2:
                video_hash = parts[0]
                hashes[video_hash] = hashes.get(video_hash, 0) + 1

        print(f"  Video hashes: {len(hashes)}")
        for hash_val, count in sorted(hashes.items()):
            print(f"    - {hash_val}: {count} screenshots")

    return files


def check_database():
    """Check transcriptions in the database."""
    print(f"\n{'='*60}")
    print("2. DATABASE TRANSCRIPTIONS")
    print(f"{'='*60}")
    print(f"Database: {settings.DATABASE_PATH}")

    if not os.path.exists(settings.DATABASE_PATH):
        print("  Status: Database does not exist")
        return []

    conn = sqlite3.connect(settings.DATABASE_PATH)
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM transcriptions")
    count = cursor.fetchone()[0]
    print(f"  Total transcriptions: {count}")

    if count == 0:
        conn.close()
        return []

    cursor.execute("SELECT video_hash, filename, transcription_data FROM transcriptions")
    rows = cursor.fetchall()

    transcription_info = []
    for video_hash, filename, trans_data in rows:
        data = json.loads(trans_data)
        segments = data.get('transcription', {}).get('segments', [])
        screenshots = sum(1 for s in segments if s.get('screenshot_url'))

        print(f"  - {video_hash}: {filename}")
        print(f"      Segments: {len(segments)}, Screenshots: {screenshots}")

        transcription_info.append({
            'hash': video_hash,
            'filename': filename,
            'segments': len(segments),
            'screenshots': screenshots
        })

    conn.close()
    return transcription_info


def check_chromadb():
    """Check ChromaDB collections."""
    print(f"\n{'='*60}")
    print("3. CHROMADB COLLECTIONS")
    print(f"{'='*60}")

    if not CHROMADB_AVAILABLE:
        print("  Status: ChromaDB not available")
        return []

    chroma_path = settings.CHROMA_DB_PATH
    print(f"ChromaDB path: {chroma_path}")

    if not os.path.exists(chroma_path):
        print("  Status: ChromaDB directory does not exist")
        return []

    try:
        client = chromadb.PersistentClient(
            path=chroma_path,
            settings=ChromaSettings(
                anonymized_telemetry=False,
                allow_reset=True
            )
        )

        collections = client.list_collections()
        print(f"  Total collections: {len(collections)}")

        collection_info = []
        for coll in collections:
            print(f"  - {coll.name}: {coll.count()} items")

            # Extract video hash
            import re
            match = re.match(r'video_([a-f0-9]+)(_images)?', coll.name)
            if match:
                video_hash = match.group(1)
                is_images = match.group(2) is not None

                collection_info.append({
                    'name': coll.name,
                    'hash': video_hash,
                    'type': 'images' if is_images else 'text',
                    'count': coll.count()
                })

                # If it's an image collection, show sample path
                if is_images and coll.count() > 0:
                    try:
                        sample = coll.get(limit=1, include=['documents', 'metadatas'])
                        if sample['documents']:
                            print(f"      Sample path: {sample['documents'][0]}")
                    except:
                        pass

        return collection_info
    except Exception as e:
        print(f"  Error accessing ChromaDB: {e}")
        return []


def check_consistency(transcriptions, chromadb_collections):
    """Check consistency between database and ChromaDB."""
    print(f"\n{'='*60}")
    print("4. CONSISTENCY CHECK")
    print(f"{'='*60}")

    # Get hashes from database
    db_hashes = {t['hash'] for t in transcriptions}

    # Get hashes from ChromaDB
    chroma_hashes = {c['hash'] for c in chromadb_collections}

    # Find orphaned collections
    orphaned = chroma_hashes - db_hashes

    if orphaned:
        print(f"  WARNING: {len(orphaned)} orphaned ChromaDB collections found!")
        print("  These collections exist but their transcriptions are deleted:")
        for hash_val in orphaned:
            collections = [c for c in chromadb_collections if c['hash'] == hash_val]
            for c in collections:
                print(f"    - {c['name']} ({c['count']} items)")
        print("\n  Recommendation: Run cleanup endpoint to remove orphaned data:")
        print("    curl -X POST http://localhost:8000/cleanup_screenshots/")
    else:
        print("  OK: No orphaned ChromaDB collections found")

    # Find missing collections
    missing = db_hashes - chroma_hashes
    if missing:
        print(f"\n  Note: {len(missing)} transcriptions not indexed in ChromaDB:")
        for hash_val in missing:
            trans = next(t for t in transcriptions if t['hash'] == hash_val)
            print(f"    - {hash_val}: {trans['filename']}")
        print("\n  Recommendation: Index these videos if you want to use chat feature:")
        print("    POST /api/index_video/?video_hash={hash}")
        print("    POST /api/index_images/?video_hash={hash}")

    return len(orphaned) == 0 and len(missing) == 0


def main():
    """Run all diagnostic checks."""
    print(f"\n{'#'*60}")
    print("# CHAT IMAGES DIAGNOSTIC TOOL")
    print(f"{'#'*60}")
    print(f"Backend directory: {Path(__file__).parent.parent}")

    # Run checks
    screenshot_files = check_screenshots()
    transcriptions = check_database()
    chromadb_collections = check_chromadb()

    # Consistency check
    if transcriptions or chromadb_collections:
        is_consistent = check_consistency(transcriptions, chromadb_collections)
    else:
        is_consistent = True
        print(f"\n{'='*60}")
        print("4. CONSISTENCY CHECK")
        print(f"{'='*60}")
        print("  Status: No data to check")

    # Summary
    print(f"\n{'='*60}")
    print("SUMMARY")
    print(f"{'='*60}")
    print(f"Screenshot files: {len(screenshot_files)}")
    print(f"Database transcriptions: {len(transcriptions)}")
    print(f"ChromaDB collections: {len(chromadb_collections)}")
    print(f"Status: {'✓ Consistent' if is_consistent else '✗ Issues found'}")

    if not is_consistent:
        print("\nPlease review the recommendations above to fix the issues.")
        sys.exit(1)
    else:
        print("\nAll checks passed! System is healthy.")
        sys.exit(0)


if __name__ == '__main__':
    main()
