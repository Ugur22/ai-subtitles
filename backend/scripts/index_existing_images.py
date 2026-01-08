#!/usr/bin/env python3
"""
Batch indexing script for existing video screenshots.

This script indexes all existing video screenshots in the database into the ChromaDB
vector store using CLIP embeddings for visual search.

Usage:
    python scripts/index_existing_images.py
"""

import os
import sys
import json
from typing import Dict, List

# Add backend directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import get_db_connection
from vector_store import VectorStore
from config import settings


class ImageIndexer:
    """Handles batch indexing of video screenshots"""

    def __init__(self):
        """Initialize the image indexer"""
        self.vector_store = VectorStore(persist_directory=settings.CHROMA_DB_PATH)
        self.stats = {
            'total_videos': 0,
            'videos_processed': 0,
            'videos_skipped': 0,
            'total_images_indexed': 0,
            'errors': []
        }

    def get_all_videos(self) -> List[Dict]:
        """
        Retrieve all videos from the database

        Returns:
            List of video dictionaries with hash, filename, and transcription data
        """
        videos = []
        try:
            with get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT video_hash, filename, transcription_data FROM transcriptions ORDER BY created_at ASC"
                )

                for row in cursor.fetchall():
                    video_hash, filename, transcription_data_json = row
                    try:
                        transcription_data = json.loads(transcription_data_json)
                        videos.append({
                            'video_hash': video_hash,
                            'filename': filename,
                            'transcription_data': transcription_data
                        })
                    except json.JSONDecodeError as e:
                        print(f"Warning: Failed to parse transcription data for {filename}: {e}")
                        self.stats['errors'].append({
                            'video_hash': video_hash,
                            'filename': filename,
                            'error': f'JSON decode error: {str(e)}'
                        })

        except Exception as e:
            print(f"Error retrieving videos from database: {e}")
            raise

        return videos

    def extract_segments(self, transcription_data: Dict) -> List[Dict]:
        """
        Extract segments from transcription data

        Args:
            transcription_data: The full transcription data dictionary

        Returns:
            List of segment dictionaries
        """
        try:
            return transcription_data.get('transcription', {}).get('segments', [])
        except Exception as e:
            print(f"Error extracting segments: {e}")
            return []

    def index_video(self, video_hash: str, filename: str, segments: List[Dict]) -> int:
        """
        Index a single video's screenshots

        Args:
            video_hash: Unique hash of the video
            filename: Name of the video file
            segments: List of transcription segments

        Returns:
            Number of images indexed (0 if skipped or failed)
        """
        # Check if already indexed
        if self.vector_store.image_collection_exists(video_hash):
            print(f"Skipping {filename} - already indexed")
            self.stats['videos_skipped'] += 1
            return 0

        # Filter segments that have screenshots
        segments_with_screenshots = [
            seg for seg in segments
            if seg.get('screenshot_url') or seg.get('screenshot_path')
        ]

        if not segments_with_screenshots:
            print(f"Skipping {filename} - no screenshots found")
            self.stats['videos_skipped'] += 1
            return 0

        print(f"\nProcessing: {filename}")
        print(f"  Video hash: {video_hash}")
        print(f"  Total segments: {len(segments)}")
        print(f"  Segments with screenshots: {len(segments_with_screenshots)}")

        try:
            # Index the images
            num_indexed = self.vector_store.index_video_images(
                video_hash=video_hash,
                segments=segments
            )

            if num_indexed > 0:
                print(f"  Successfully indexed {num_indexed} images")
                self.stats['videos_processed'] += 1
                self.stats['total_images_indexed'] += num_indexed
            else:
                print(f"  No images were indexed")
                self.stats['videos_skipped'] += 1

            return num_indexed

        except Exception as e:
            error_msg = f"Failed to index {filename}: {str(e)}"
            print(f"  ERROR: {error_msg}")
            self.stats['errors'].append({
                'video_hash': video_hash,
                'filename': filename,
                'error': str(e)
            })
            return 0

    def run(self):
        """Execute the batch indexing process"""
        print("=" * 80)
        print("Video Screenshot Batch Indexing")
        print("=" * 80)
        print()

        # Get all videos from database
        print("Retrieving videos from database...")
        videos = self.get_all_videos()
        self.stats['total_videos'] = len(videos)

        if not videos:
            print("No videos found in database.")
            return

        print(f"Found {len(videos)} videos in database")
        print()

        # Process each video
        for i, video in enumerate(videos, 1):
            print(f"\n[{i}/{len(videos)}] ", end="")

            segments = self.extract_segments(video['transcription_data'])
            self.index_video(
                video_hash=video['video_hash'],
                filename=video['filename'],
                segments=segments
            )

        # Print summary
        self.print_summary()

    def print_summary(self):
        """Print a summary of the indexing process"""
        print()
        print("=" * 80)
        print("INDEXING SUMMARY")
        print("=" * 80)
        print(f"Total videos in database:  {self.stats['total_videos']}")
        print(f"Videos processed:          {self.stats['videos_processed']}")
        print(f"Videos skipped:            {self.stats['videos_skipped']}")
        print(f"Total images indexed:      {self.stats['total_images_indexed']}")
        print(f"Errors encountered:        {len(self.stats['errors'])}")

        if self.stats['errors']:
            print()
            print("ERRORS:")
            print("-" * 80)
            for error in self.stats['errors']:
                print(f"  Video: {error['filename']} ({error['video_hash']})")
                print(f"  Error: {error['error']}")
                print()

        print("=" * 80)

        # Exit with error code if there were failures
        if self.stats['errors']:
            sys.exit(1)


def main():
    """Main entry point"""
    try:
        indexer = ImageIndexer()
        indexer.run()
    except KeyboardInterrupt:
        print("\n\nIndexing interrupted by user.")
        sys.exit(130)
    except Exception as e:
        print(f"\n\nFATAL ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
