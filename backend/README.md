# AI Subtitles - Backend API

FastAPI-based backend server for AI-powered video transcription, subtitle generation, speaker diarization, visual search, audio analysis, and RAG-powered chat. Features local AI processing with Faster Whisper, multi-LLM provider support, background job processing, and multi-modal semantic search capabilities.

**Production API**: `https://REDACTED_BACKEND_URL`

## Technology Stack

### Core Framework
- **FastAPI** 0.104.1 - Modern async web framework
- **Uvicorn** 0.24.0 - ASGI server
- **Python** 3.9+
- **Pydantic** 2.5.2 - Data validation

### AI & Machine Learning
- **Faster Whisper** 1.2.1 - Local speech-to-text (OpenAI Whisper optimized)
- **PyTorch** 2.7.0 - Deep learning framework
- **TorchAudio** 2.7.0 - Audio processing
- **Transformers** 4.38.2 - HuggingFace models (MarianMT translation, BART summarization)
- **Pyannote.audio** 3.1.1 - Speaker diarization and identification
- **Sentence Transformers** 3.0.0 - Text embeddings for semantic search
- **CLIP** - Visual embeddings for image search
- **PANNs** - Audio event detection (laughter, applause, music, etc.)

### LLM & RAG
- **ChromaDB** 0.4.22 - Vector database for semantic search
- **Multi-provider LLM support**: Ollama, Groq, OpenAI, Anthropic, Grok (xAI)

### Media Processing
- **MoviePy** 1.0.3 - Video/audio manipulation
- **FFmpeg** - Required system dependency
- **AV** 13.1.0 - Audio/video container format handling

### Infrastructure
- **Google Cloud Storage** - Video file storage (production)
- **Google Cloud Firestore** - Production database
- **Supabase** - Background job queue and real-time updates
- **SQLite3** - Local development database

## Prerequisites

### Required
- **Python** 3.9 or higher
- **FFmpeg** - System installation required
- **HuggingFace Account** - For speaker diarization model access

### Optional (for different LLM providers)
- **Ollama** - For local LLM (recommended for privacy)
- **Groq API Key** - For fast cloud inference
- **OpenAI API Key** - For GPT models
- **Anthropic API Key** - For Claude models
- **xAI API Key** - For Grok models

### For Production Features
- **Google Cloud Project** - For Cloud Run, GCS, Firestore
- **Supabase Account** - For background job processing

## Installation

### 1. Install System Dependencies

#### macOS
```bash
brew install ffmpeg
```

#### Ubuntu/Debian
```bash
sudo apt-get update
sudo apt-get install ffmpeg
```

#### Windows
Download FFmpeg from https://ffmpeg.org/download.html and add to PATH.

### 2. Python Environment Setup

```bash
# Navigate to backend directory
cd backend

# Create virtual environment
python -m venv venv

# Activate virtual environment
# On macOS/Linux:
source venv/bin/activate
# On Windows:
venv\Scripts\activate

# Install Python dependencies
pip install -r requirements.txt
```

### 3. Environment Configuration

```bash
# Copy example environment file
cp .env.example .env

# Edit .env with your configuration
nano .env  # or use your preferred editor
```

### 4. Configure Environment Variables

Edit `backend/.env`:

```bash
# ============================================
# CORE SETTINGS
# ============================================
API_TITLE=AI Subtitles API
API_VERSION=1.0.0
CORS_ORIGINS=["http://localhost:5173","https://REDACTED_FRONTEND_URL"]
MAX_UPLOAD_SIZE=10737418240  # 10GB

# ============================================
# DATABASE CONFIGURATION
# ============================================
# Local development: sqlite
# Production: firestore
DATABASE_TYPE=sqlite
DATABASE_PATH=transcriptions.db
FIRESTORE_COLLECTION=transcriptions

# ============================================
# HUGGINGFACE AUTHENTICATION (REQUIRED)
# ============================================
# Get your token from: https://huggingface.co/settings/tokens
# Accept pyannote conditions at: https://huggingface.co/pyannote/speaker-diarization
HUGGINGFACE_TOKEN=your_huggingface_token_here

# ============================================
# WHISPER MODEL CONFIGURATION
# ============================================
# Model size (larger = more accurate but slower)
# Options: tiny, base, small, medium, large, large-v2, large-v3
FASTWHISPER_MODEL=small

# Device for inference
# Options: cpu, cuda (NVIDIA GPU), mps (Apple Silicon)
FASTWHISPER_DEVICE=cpu

# Compute type (affects speed/accuracy tradeoff)
# Options: int8, float16, float32
# int8 recommended for CPU, float16 for GPU
FASTWHISPER_COMPUTE_TYPE=int8

# ============================================
# SPEAKER DIARIZATION SETTINGS
# ============================================
ENABLE_SPEAKER_DIARIZATION=true
MIN_SPEAKERS=1
MAX_SPEAKERS=10

# ============================================
# LLM PROVIDER CONFIGURATION
# ============================================
# Options: local (Ollama), groq, openai, anthropic, grok
DEFAULT_LLM_PROVIDER=local

# Ollama Settings (Local LLM)
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=llama3.2:3b

# Groq Settings (Cloud - Fast)
GROQ_API_KEY=your_groq_api_key
GROQ_MODEL=llama-3.1-70b-versatile

# OpenAI Settings
OPENAI_API_KEY=your_openai_api_key
OPENAI_MODEL=gpt-4

# Anthropic Settings
ANTHROPIC_API_KEY=your_anthropic_api_key
ANTHROPIC_MODEL=claude-3-5-sonnet-20241022

# xAI Grok Settings
XAI_API_KEY=your_xai_api_key
XAI_MODEL=grok-beta

# ============================================
# VISUAL SEARCH (CLIP)
# ============================================
ENABLE_VISUAL_SEARCH=true
CLIP_MODEL=ViT-B/32

# ============================================
# AUDIO ANALYSIS (PANNs)
# ============================================
ENABLE_AUDIO_ANALYSIS=true
PANNS_MODEL=Cnn14_mAP=0.431.pth
AUDIO_EVENT_THRESHOLD=0.3
ENABLE_SPEECH_EMOTION=true

# VAD (Voice Activity Detection)
VAD_ENABLED=true
VAD_THRESHOLD=0.5
VAD_MIN_SILENCE_DURATION_MS=300

# ============================================
# CLOUD STORAGE (GCS)
# ============================================
ENABLE_GCS_UPLOADS=false         # Set true for production
GCS_BUCKET_NAME=your-bucket-name
GCS_VIDEO_PREFIX=videos/
GCS_AUDIO_PREFIX=audio/
GCS_URL_EXPIRY=3600

# ============================================
# SUPABASE (Background Job Queue)
# ============================================
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_KEY=your_service_key

# ============================================
# VECTOR DATABASE
# ============================================
CHROMA_DB_PATH=./chroma_db
```

### 5. Get HuggingFace Token (Required for Speaker Diarization)

1. Create account at https://huggingface.co
2. Go to https://huggingface.co/settings/tokens
3. Create new token with "read" permissions
4. Accept pyannote terms at: https://huggingface.co/pyannote/speaker-diarization-3.1
5. Add token to `.env` file

### 6. Install Ollama (Optional - for Local LLM)

```bash
# Visit https://ollama.ai/ and install for your platform

# After installation, pull a model:
ollama pull llama3.2:3b

# Verify Ollama is running:
curl http://localhost:11434
```

### 7. Run the Server

```bash
# Make sure virtual environment is activated
source venv/bin/activate  # or venv\Scripts\activate on Windows

# Start the server
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

The API will be available at:
- **API**: `http://localhost:8000`
- **API Docs (Swagger)**: `http://localhost:8000/docs`
- **Alternative Docs (ReDoc)**: `http://localhost:8000/redoc`

## API Endpoints

### Transcription

#### `POST /transcribe_local/`
Upload and transcribe audio/video file using local Faster Whisper model.

**Request:** Multipart form data
- `file`: Audio/video file (MP4, MP3, WAV, WebM, MKV, etc.)
- `language`: Language code (optional, auto-detect if not provided)
- `enable_diarization`: Boolean (default: from env var)

**Response:**
```json
{
  "video_hash": "abc123...",
  "segments": [
    {
      "id": 0,
      "start": 0.0,
      "end": 3.5,
      "text": "Hello, this is a test.",
      "speaker": "SPEAKER_00"
    }
  ],
  "language": "en",
  "file_path": "/path/to/original/file.mp4"
}
```

#### `POST /transcribe_local_stream/`
Streaming transcription with SSE for real-time progress updates.

#### `POST /transcribe_gcs_stream/`
Transcribe directly from GCS signed URL (for Cloud Run deployment).

#### `GET /transcriptions/`
List all saved transcriptions with thumbnails.

#### `GET /transcription/{video_hash}`
Get specific transcription by video hash.

#### `DELETE /transcription/{video_hash}`
Delete transcription and all associated data (files, embeddings).

### Upload & Cloud Storage

#### `POST /api/upload/signed-url`
Get signed URL for direct GCS upload (bypasses 32MB Cloud Run limit).

**Request:**
```json
{
  "filename": "video.mp4",
  "content_type": "video/mp4",
  "file_size": 104857600
}
```

**Response:**
```json
{
  "signed_url": "https://storage.googleapis.com/...",
  "gcs_path": "videos/abc123/video.mp4",
  "expires_at": "2024-01-15T11:30:00Z"
}
```

#### `POST /api/upload/resumable-url`
Get resumable upload URL for large files (>100MB).

#### `GET /api/upload/status/{gcs_path}`
Check upload status.

#### `GET /api/upload/config`
Get upload configuration (max size, allowed types).

### Background Jobs

#### `POST /api/jobs/submit`
Submit video for background transcription processing.

**Request:**
```json
{
  "gcs_path": "videos/abc123/video.mp4",
  "filename": "video.mp4",
  "video_hash": "abc123...",
  "options": {
    "language": "en",
    "enable_diarization": true
  }
}
```

**Response:**
```json
{
  "job_id": "uuid-123...",
  "status": "pending",
  "created_at": "2024-01-15T10:30:00Z"
}
```

#### `GET /api/jobs/{job_id}`
Get job status and results.

**Response:**
```json
{
  "id": "uuid-123...",
  "status": "completed",
  "video_hash": "abc123...",
  "filename": "video.mp4",
  "result_json": { "segments": [...] },
  "created_at": "2024-01-15T10:30:00Z",
  "completed_at": "2024-01-15T10:35:00Z"
}
```

#### `GET /api/jobs`
List all jobs (supports pagination).

#### `DELETE /api/jobs/{job_id}`
Cancel a pending or processing job.

#### `POST /api/jobs/{job_id}/retry`
Retry a failed job.

#### `GET /api/jobs/{job_id}/share`
Generate public share link for job results.

#### `POST /api/jobs/check-stale`
Check for and handle stale/stuck jobs.

#### `GET /api/jobs/{job_id}/download/{format}`
Download job results in JSON, SRT, or CSV format.

#### `GET /api/jobs/{job_id}/video`
Stream video file from job.

### Search & RAG Chat

#### `POST /api/index_video/`
Index video transcription for semantic search.

**Request:**
```json
{
  "video_hash": "abc123..."
}
```

#### `POST /api/index_images/`
Index video screenshots with CLIP embeddings for visual search.

**Request:**
```json
{
  "video_hash": "abc123...",
  "screenshot_urls": ["http://...", "http://..."]
}
```

#### `POST /api/search_images/`
Search screenshots by text description using CLIP.

**Request:**
```json
{
  "video_hash": "abc123...",
  "query": "person pointing at whiteboard",
  "top_k": 5
}
```

#### `POST /api/chat/`
Multi-modal RAG chat with video content.

**Request:**
```json
{
  "video_hash": "abc123...",
  "message": "What did they say about artificial intelligence?",
  "conversation_history": [],
  "include_images": true,
  "custom_instructions": "Be concise"
}
```

**Response:**
```json
{
  "response": "Based on the transcript, they discussed...",
  "sources": [
    {
      "segment_id": 42,
      "text": "Artificial intelligence is transforming...",
      "timestamp": "00:05:23",
      "speaker": "John"
    }
  ],
  "images": [
    {
      "url": "http://...",
      "timestamp": "00:05:20",
      "relevance_score": 0.85
    }
  ]
}
```

#### `GET /api/llm/providers`
List available LLM providers and their status.

#### `POST /api/llm/test`
Test LLM provider configuration.

### Speaker Recognition

#### `POST /api/speaker/enroll`
Enroll a new speaker with voice sample.

**Request:** Multipart form data
- `audio`: Audio file with speaker's voice
- `speaker_name`: Name to assign to speaker

#### `GET /api/speaker/list`
List all enrolled speakers.

#### `POST /api/speaker/identify`
Identify speaker from audio segment.

#### `DELETE /api/speaker/{speaker_name}`
Remove enrolled speaker.

#### `POST /api/speaker/transcription/{video_hash}/auto_identify_speakers`
Auto-identify speakers in transcription using enrolled voices.

#### `POST /api/speaker/transcription/{video_hash}/speaker`
Update speaker name in transcription (propagates to vector store).

### Translation & Subtitles

#### `POST /translate_local/`
Translate transcript segments using local MarianMT model.

**Request:**
```json
{
  "video_hash": "abc123...",
  "target_language": "es"
}
```

#### `GET /subtitles/{language}`
Generate subtitle file (WebVTT or SRT format).

**Query Parameters:**
- `video_hash`: Video identifier
- `format`: `webvtt` or `srt` (default: webvtt)
- `include_speakers`: Boolean (default: true)

### Summaries

#### `POST /generate_summary/`
Generate AI summary of transcription.

**Request:**
```json
{
  "video_hash": "abc123...",
  "max_length": 200
}
```

### Video & Media

#### `GET /video/{video_hash}`
Stream video file with HTTP range request support (for seeking).

#### `POST /update_file_path/{video_hash}`
Update path to original file if moved.

#### `POST /cleanup_screenshots/`
Clean up temporary screenshot files and orphaned ChromaDB collections.

## Database Architecture

The backend supports multiple database backends with automatic fallback:

### SQLite (Local Development)
- **Path**: `transcriptions.db`
- **Table**: `transcriptions` with columns:
  - `video_hash` (PRIMARY KEY)
  - `filename`
  - `file_path`
  - `transcription_data` (JSON)
  - `created_at`

### Firestore (Production)
- **Configured via**: `DATABASE_TYPE=firestore`
- **Collection**: `transcriptions`
- Same document structure as SQLite

### Supabase (Job Queue)
- **Table**: `jobs` with columns:
  - `id` (UUID, PRIMARY KEY)
  - `status` (pending/processing/completed/failed)
  - `video_hash`
  - `filename`
  - `gcs_path`
  - `result_json` (full transcription)
  - `created_at`, `started_at`, `completed_at`
  - `error_message`, `retry_count`

**Fallback Strategy**: Chat router automatically checks Supabase jobs table if transcription not found in SQLite/Firestore.

## Project Structure

```
backend/
├── main.py                        # FastAPI app entry point
├── config.py                      # Pydantic settings
├── database.py                    # SQLite/Firestore abstraction
├── dependencies.py                # ML model dependency injection
├── requirements.txt               # Python dependencies
├── Dockerfile                     # Cloud Run deployment
├── docker-compose.yml             # Local development
├── .env.example                   # Environment template
│
├── routers/                       # API endpoint organization
│   ├── transcription.py           # Transcription endpoints
│   ├── speaker.py                 # Speaker recognition
│   ├── chat.py                    # LLM/RAG chat + visual search
│   ├── video.py                   # Video serving & utilities
│   ├── upload.py                  # GCS signed URL generation
│   └── jobs.py                    # Background job management
│
├── services/                      # Business logic layer
│   ├── audio_service.py           # Audio extraction & streaming
│   ├── video_service.py           # Video processing & screenshots
│   ├── speaker_service.py         # Speaker diarization
│   ├── translation_service.py     # MarianMT translation
│   ├── subtitle_service.py        # SRT/VTT generation
│   ├── summarization_service.py   # AI summarization
│   ├── audio_analysis_service.py  # PANNs + emotion detection
│   ├── gcs_service.py             # Google Cloud Storage
│   ├── job_queue_service.py       # Supabase job management
│   └── supabase_service.py        # Supabase client
│
├── models/                        # Pydantic schemas
│   ├── transcription.py
│   ├── chat.py
│   ├── speaker.py
│   ├── audio_events.py
│   ├── video.py
│   └── common.py
│
├── utils/                         # Helper utilities
│   ├── file_utils.py              # File hashing
│   └── time_utils.py              # Timestamp formatting
│
├── llm_providers.py               # LLM abstraction (5 providers)
├── vector_store.py                # ChromaDB wrapper for RAG
├── audio_analyzer.py              # PANNs integration
├── speaker_diarization.py         # Pyannote integration
├── speaker_recognition.py         # Voice biometrics
├── download_models.py             # Pre-download models for Docker
│
├── static/                        # Static file storage
│   ├── videos/                    # Uploaded videos
│   ├── screenshots/               # Video screenshots
│   └── subtitles/                 # Generated subtitles
│
├── chroma_db/                     # ChromaDB vector storage
└── transcriptions.db              # SQLite database (local)
```

## Model Information

### Faster Whisper Models

| Model    | Size    | English-only | Multilingual | Relative Speed |
| -------- | ------- | ------------ | ------------ | -------------- |
| tiny     | 39 MB   | Yes          | Yes          | ~32x           |
| base     | 74 MB   | Yes          | Yes          | ~16x           |
| small    | 244 MB  | Yes          | Yes          | ~6x            |
| medium   | 769 MB  | Yes          | Yes          | ~2x            |
| large-v2 | 1550 MB | -            | Yes          | 1x             |
| large-v3 | 1550 MB | -            | Yes          | 1x             |

**Recommendation:**
- **Development/CPU:** `small` (good balance of speed/accuracy)
- **Production/GPU:** `large-v3` (best accuracy)
- **Quick testing:** `tiny` or `base`

### Audio Analysis Models

- **PANNs (Cnn14)**: Detects 527 audio event classes including:
  - Speech, laughter, applause, music
  - Environmental sounds (wind, rain, traffic)
  - Alerts (alarms, sirens)

- **Speech Emotion**: Detects emotional tone:
  - Happy, sad, angry, neutral, fearful, surprised

## Performance Optimization

### CPU Optimization
```bash
FASTWHISPER_COMPUTE_TYPE=int8
FASTWHISPER_MODEL=small
```

### GPU Optimization (NVIDIA)
```bash
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu118

FASTWHISPER_DEVICE=cuda
FASTWHISPER_COMPUTE_TYPE=float16
FASTWHISPER_MODEL=large-v3
```

### Apple Silicon Optimization
```bash
FASTWHISPER_DEVICE=mps
FASTWHISPER_COMPUTE_TYPE=float16
FASTWHISPER_MODEL=medium
```

## Deployment

### Production (Google Cloud Run)

The backend is deployed to Cloud Run with:
- Pre-downloaded translation models
- Persistent volumes for data
- Firestore for database
- GCS for file storage
- Supabase for job queue

```bash
# Build and deploy
docker build -t gcr.io/PROJECT_ID/ai-subs-backend .
docker push gcr.io/PROJECT_ID/ai-subs-backend
gcloud run deploy ai-subs-backend \
  --image gcr.io/PROJECT_ID/ai-subs-backend \
  --platform managed \
  --region us-central1 \
  --allow-unauthenticated
```

See [Production Deployment Guide](../docs/PRODUCTION_DEPLOYMENT_FIXES.md) for complete instructions.

### Docker (Local)
```bash
# Build image
docker build -t ai-subs-backend .

# Run container
docker run -p 8000:8000 \
  -v $(pwd)/transcriptions.db:/app/transcriptions.db \
  -e HUGGINGFACE_TOKEN=your_token \
  ai-subs-backend

# Or use docker-compose
docker-compose up -d
```

## Development

### Running with Auto-reload
```bash
source venv/bin/activate && uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

### Interactive API Documentation
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

### Testing Endpoints
```bash
# Test transcription
curl -X POST "http://localhost:8000/transcribe_local/" \
  -H "Content-Type: multipart/form-data" \
  -F "file=@/path/to/video.mp4"

# Test LLM providers
curl -X GET "http://localhost:8000/api/llm/providers"

# Test chat
curl -X POST "http://localhost:8000/api/chat/" \
  -H "Content-Type: application/json" \
  -d '{"video_hash": "abc123", "message": "Summarize the main points"}'

# Submit background job
curl -X POST "http://localhost:8000/api/jobs/submit" \
  -H "Content-Type: application/json" \
  -d '{"gcs_path": "videos/test.mp4", "filename": "test.mp4", "video_hash": "abc123"}'
```

## Troubleshooting

### Common Issues

**"ModuleNotFoundError: No module named 'torch'"**
```bash
source venv/bin/activate
pip install -r requirements.txt
```

**"FFmpeg not found"**
```bash
# macOS
brew install ffmpeg

# Ubuntu/Debian
sudo apt-get install ffmpeg
```

**"HuggingFace authentication failed"**
```bash
# Verify token is set
cat .env | grep HUGGINGFACE_TOKEN

# Accept model terms at:
# https://huggingface.co/pyannote/speaker-diarization-3.1
```

**"Ollama connection refused"**
```bash
ollama serve
curl http://localhost:11434
ollama pull llama3.2:3b
```

**"CUDA out of memory"**
```bash
FASTWHISPER_MODEL=small
FASTWHISPER_DEVICE=cpu
```

**"Large file upload fails"**
- Enable GCS uploads: `ENABLE_GCS_UPLOADS=true`
- Configure GCS bucket and credentials
- Use resumable upload for files >100MB

**"Background jobs stuck in processing"**
- Check Supabase credentials
- Call `/api/jobs/check-stale` to reset stuck jobs
- Verify Cloud Run has sufficient memory

## Security Notes

- Never commit `.env` file to version control
- Keep API keys secure and rotate regularly
- Use environment variables for all sensitive data
- CORS is configured for specific origins in production
- Use HTTPS in production (Cloud Run provides this)
- Validate and sanitize all user inputs

## Related Documentation

- **[Main README](../README.md)** - Project overview and quick start
- **[Frontend README](../frontend/README.md)** - Frontend setup
- **[Production Deployment](../docs/PRODUCTION_DEPLOYMENT_FIXES.md)** - Cloud Run + Netlify
- **[Speaker Diarization Setup](../docs/SPEAKER_DIARIZATION_SETUP.md)** - Detailed diarization guide

## License

[Add your license here]
