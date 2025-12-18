# Backend Maintenance Scripts

This directory contains utility scripts for maintenance and batch operations.

## Available Scripts

### index_existing_images.py

Batch indexes all existing video screenshots in the database into the ChromaDB vector store using CLIP embeddings for visual search.

**Purpose:**
- Index screenshots from videos that were transcribed before visual search was implemented
- Re-index videos after clearing the ChromaDB database
- Ensure all videos have their screenshots indexed for visual search

**Usage:**
```bash
# From the backend directory
python scripts/index_existing_images.py

# Or make it executable and run directly
./scripts/index_existing_images.py
```

**Features:**
- Automatically retrieves all videos from the database
- Skips videos that are already indexed (checks if collection exists)
- Shows progress for each video being processed
- Handles errors gracefully and continues processing other videos
- Provides detailed summary at the end with statistics

**Output:**
```
================================================================================
Video Screenshot Batch Indexing
================================================================================

Retrieving videos from database...
Found 5 videos in database

[1/5] Processing: example1.mp4
  Video hash: abc123...
  Total segments: 45
  Segments with screenshots: 45
  Successfully indexed 45 images

[2/5] Skipping example2.mp4 - already indexed

...

================================================================================
INDEXING SUMMARY
================================================================================
Total videos in database:  5
Videos processed:          3
Videos skipped:            2
Total images indexed:      135
Errors encountered:        0
================================================================================
```

**Error Handling:**
- Skips videos with corrupt JSON transcription data
- Skips videos with no screenshots
- Reports all errors at the end without stopping the process
- Exits with error code 1 if any errors occurred

**Requirements:**
- All dependencies from requirements.txt must be installed
- ChromaDB directory must be accessible (configured in .env as CHROMA_DB_PATH)
- Screenshot files must exist in the paths specified in the database

## Adding New Scripts

When creating new maintenance scripts:

1. Add a descriptive docstring at the top
2. Include proper error handling
3. Provide progress indicators for long-running operations
4. Print a summary at the end
5. Use proper exit codes (0 for success, non-zero for errors)
6. Document the script in this README
