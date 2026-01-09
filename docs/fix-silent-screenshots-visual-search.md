# Fix: Silent Visual Screenshots and Visual Search

## Summary

Two issues reported:
1. **Silent visual screenshots** not showing in transcript (scenes with no speech)
2. **Visual search with scene** not working

## Root Causes Identified

### Issue 1: Silent Visual Screenshots NOT Working in Production

**Critical Finding:** `create_silent_segments_for_gaps()` is **NOT called in background_worker.py**!

Production uses the job-based system via `background_worker.process_job()` for transcription. This function does NOT call `create_silent_segments_for_gaps()`, which means:
- Silent segments are **never created** when transcribing via job queue
- This only affects production (Cloud Run) - streaming endpoints work locally

**Code Trace:**
1. `routers/jobs.py:262` → calls `background_worker.process_job(job_id)`
2. `services/background_worker.py` → extracts screenshots for speech segments (lines 298-330)
3. BUT **never calls** `create_silent_segments_for_gaps()`!

**Additional Issue:** Even if called, silent screenshots are stored locally but NOT uploaded to GCS:
- `create_silent_segments_for_gaps()` saves to `static/screenshots/` (line 772-780)
- Returns URLs like `/static/screenshots/{filename}`
- On Cloud Run, these local files don't persist

### Issue 2: Visual Search Issues

Potential causes (need to verify):
1. Silent segments aren't created → no silent screenshots to index
2. Image indexing happens BEFORE silent segments exist
3. Supabase RPC `search_images_by_embedding` may need verification

## Files to Modify

### Backend - Critical Changes
1. **`backend/services/background_worker.py`**
   - Add call to `create_silent_segments_for_gaps()` BEFORE GCS screenshot upload
   - Upload silent segment screenshots to GCS

2. **`backend/routers/transcription.py`**
   - Modify `create_silent_segments_for_gaps()` to support GCS upload
   - Return GCS URLs for silent segment screenshots instead of local paths

### Files for Reference
- `backend/routers/transcription.py:710-816` - `create_silent_segments_for_gaps()` function
- `backend/services/gcs_service.py:293-376` - Screenshot upload methods
- `backend/services/background_worker.py:290-370` - Screenshot handling in job processing

## Implementation Plan

### Step 1: Add Silent Segment Detection to Background Worker
Location: `backend/services/background_worker.py` around line 355

```python
# After extracting speech screenshots and before auto-indexing images:

# Detect gaps and create silent segments
from routers.transcription import create_silent_segments_for_gaps
if suffix.lower() in {'.mp4', '.mpeg', '.webm', '.mov', '.mkv'}:
    print(f"[Worker] Detecting timeline gaps and creating silent segments...")
    formatted_segments = create_silent_segments_for_gaps(
        segments=formatted_segments,
        video_path=None,
        video_hash=video_hash,
        min_gap_duration=2.0,
        source_url=read_url  # Use GCS URL for streaming screenshot extraction
    )
```

### Step 2: Upload Silent Segment Screenshots to GCS
Modify `create_silent_segments_for_gaps()` OR add a post-processing step in background_worker:

```python
# Upload silent segment screenshots to GCS
silent_segments = [s for s in formatted_segments if s.get('is_silent')]
for seg in silent_segments:
    screenshot_path = seg.get('screenshot_url', '').replace('/static/screenshots/', 'static/screenshots/')
    if os.path.exists(screenshot_path):
        gcs_url = gcs_service.upload_screenshot(
            screenshot_path,
            video_hash,
            seg['start']  # timestamp
        )
        seg['screenshot_url'] = gcs_url
```

### Step 3: Ensure Image Indexing Includes Silent Segments
Verify that `image_embedding_service.index_video_images()` is called AFTER silent segments are created and their screenshots are uploaded to GCS.

### Step 4: Test Visual Search
After fixing silent segments, visual search should work if images are properly indexed.

## Verification Steps

1. **Deploy to Cloud Run**
2. **Upload a video** with silent gaps (no speech for >2 seconds)
3. **Check transcription result:**
   - Should contain segments with `is_silent: true`
   - `screenshot_url` should be GCS signed URL, not `/static/...`
4. **Enable Visual Moments toggle** in transcript panel
5. **Verify silent segments appear** with "Visual Moment" badge
6. **Test visual search** in chat panel - should find visual moments

## Testing Locally
Can also test by using the streaming endpoint (`/transcribe_local_stream/`) which already calls `create_silent_segments_for_gaps()`, but this won't test the production job-queue path.

## Feature Branch Reference

The `feature/use-local-whisper-version` branch has these features working. Key commits:
- `a5e23a7` - Add silent segment detection with screenshots in transcription process
- `e1b00a6` - Enhance speaker extraction and visual search capabilities

You can compare implementations by running:
```bash
git diff main..feature/use-local-whisper-version -- backend/services/background_worker.py
git diff main..feature/use-local-whisper-version -- backend/routers/transcription.py
```
