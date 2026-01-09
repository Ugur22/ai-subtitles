# API Reference

Complete API documentation for AI-Subs backend.

**Base URL:** `http://localhost:8000` (development) or your Cloud Run URL (production)

## Transcription

### Local Transcription

```
POST /transcribe_local/
```

Upload and transcribe an audio/video file using local Faster Whisper model.

**Request:** `multipart/form-data`
- `file`: Audio/video file (MP4, MP3, WAV, WebM, MKV, etc.)
- `language`: (optional) Language code or "auto"
- `enable_diarization`: (optional) Enable speaker diarization

### Streaming Transcription

```
POST /transcribe_local_stream/
```

Same as above but returns Server-Sent Events (SSE) for real-time progress.

### Transcribe from GCS

```
POST /transcribe_gcs_stream/
```

Transcribe a file already uploaded to Google Cloud Storage.

**Request Body:**
```json
{
  "gcs_uri": "gs://bucket/path/to/file.mp4",
  "language": "auto",
  "enable_diarization": true
}
```

### List Transcriptions

```
GET /transcriptions/
```

Returns all saved transcriptions.

### Get Transcription

```
GET /transcription/{video_hash}
```

Get a specific transcription by video hash.

### Delete Transcription

```
DELETE /transcription/{video_hash}
```

Delete a transcription and associated data.

## Upload & Jobs

### Get Signed Upload URL

```
POST /api/upload/signed-url
```

Get a signed URL for direct upload to GCS (bypasses server file size limits).

**Request Body:**
```json
{
  "filename": "video.mp4",
  "content_type": "video/mp4"
}
```

### Get Resumable Upload URL

```
POST /api/upload/resumable-url
```

Get a resumable upload URL for large files with resume capability.

### Submit Background Job

```
POST /api/jobs/submit
```

Submit a transcription job for background processing.

**Request Body:**
```json
{
  "gcs_uri": "gs://bucket/path/to/file.mp4",
  "language": "auto",
  "enable_diarization": true
}
```

### Get Job Status

```
GET /api/jobs/{job_id}
```

Get job status and results (if completed).

### List Jobs

```
GET /api/jobs
```

List all jobs for the current user.

### Cancel Job

```
DELETE /api/jobs/{job_id}
```

Cancel a pending or running job.

### Generate Share Link

```
GET /api/jobs/{job_id}/share
```

Generate a public share link for completed job results.

## Search & Chat

### Index Video for Search

```
POST /api/index_video/
```

Index a transcription for semantic search.

**Request Body:**
```json
{
  "video_hash": "abc123",
  "segments": [...]
}
```

### Index Screenshots

```
POST /api/index_images/
```

Index video screenshots for visual search using CLIP embeddings.

### Visual Search

```
POST /api/search_images/
```

Search screenshots by text description.

**Request Body:**
```json
{
  "video_hash": "abc123",
  "query": "person pointing at whiteboard",
  "top_k": 5
}
```

### Chat with Video Content

```
POST /api/chat/
```

Multi-modal RAG chat - ask questions about your video content.

**Request Body:**
```json
{
  "video_hash": "abc123",
  "query": "What did the speaker say about the budget?",
  "provider": "grok"
}
```

## Speaker Recognition

### Enroll Speaker

```
POST /api/speaker/enroll
```

Enroll a speaker voice sample for recognition.

**Request:** `multipart/form-data`
- `file`: Audio sample of the speaker
- `name`: Speaker name

### List Speakers

```
GET /api/speaker/list
```

List all enrolled speakers.

### Identify Speaker

```
POST /api/speaker/identify
```

Identify a speaker from an audio sample.

### Auto-Identify in Transcription

```
POST /api/speaker/transcription/{video_hash}/auto_identify_speakers
```

Automatically identify enrolled speakers in a transcription.

## Utilities

### Stream Video

```
GET /video/{video_hash}
```

Stream video file with HTTP range support.

### Generate Subtitles

```
GET /subtitles/{language}
```

Generate SRT subtitle file.

**Query Parameters:**
- `format`: `srt` or `vtt`

### Translate Segments

```
POST /translate_local/
```

Translate transcript segments to another language.

**Request Body:**
```json
{
  "segments": [...],
  "target_language": "es"
}
```

### Generate Summary

```
POST /generate_summary/
```

Generate AI summary of the transcript.

**Request Body:**
```json
{
  "video_hash": "abc123",
  "provider": "local"
}
```

## Interactive Documentation

When running locally, visit:
- **Swagger UI:** http://localhost:8000/docs
- **ReDoc:** http://localhost:8000/redoc
