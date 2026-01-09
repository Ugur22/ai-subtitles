# Configuration Guide

Complete reference for all environment variables in AI-Subs.

## Backend Environment Variables

Create `backend/.env` with the following configuration:

### Core Settings

```bash
API_TITLE=AI Subtitles API
API_VERSION=1.0.0
CORS_ORIGINS=["http://localhost:5173","https://your-frontend.netlify.app"]
```

### Database Configuration

```bash
# Local development: sqlite
# Production: firestore
DATABASE_TYPE=sqlite
DATABASE_PATH=transcriptions.db
FIRESTORE_COLLECTION=transcriptions
```

### Whisper Model Settings

```bash
FASTWHISPER_MODEL=small          # Options: tiny, base, small, medium, large
FASTWHISPER_DEVICE=cpu           # Options: cpu, cuda, mps (Apple Silicon)
FASTWHISPER_COMPUTE_TYPE=int8    # Options: int8, float16, float32
```

| Model | Size | Speed | Accuracy |
|-------|------|-------|----------|
| tiny | 75MB | Fastest | Lower |
| base | 142MB | Fast | Good |
| small | 466MB | Medium | Better |
| medium | 1.5GB | Slower | High |
| large | 3GB | Slowest | Best |

### Speaker Diarization

```bash
# Get token: https://huggingface.co/settings/tokens
# Accept terms: https://huggingface.co/pyannote/speaker-diarization
HUGGINGFACE_TOKEN=your_token_here
ENABLE_SPEAKER_DIARIZATION=true
MIN_SPEAKERS=1
MAX_SPEAKERS=10
```

### LLM Providers

```bash
DEFAULT_LLM_PROVIDER=local       # Options: local, groq, openai, anthropic, grok

# Ollama (local, free)
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=llama3.2:3b

# Cloud LLM API Keys (only configure the ones you use)
GROQ_API_KEY=your_groq_api_key
OPENAI_API_KEY=your_openai_api_key
ANTHROPIC_API_KEY=your_anthropic_api_key
XAI_API_KEY=your_xai_api_key
```

### Visual Search (CLIP)

```bash
ENABLE_VISUAL_SEARCH=true
CLIP_MODEL=ViT-B/32
```

### Audio Analysis

```bash
ENABLE_AUDIO_ANALYSIS=true
PANNS_MODEL=Cnn14_mAP=0.431.pth
AUDIO_EVENT_THRESHOLD=0.3
ENABLE_SPEECH_EMOTION=true

# Voice Activity Detection
VAD_ENABLED=true
VAD_THRESHOLD=0.5
VAD_MIN_SILENCE_DURATION_MS=300
```

### Cloud Storage (GCS)

```bash
ENABLE_GCS_UPLOADS=false         # Set true for production
GCS_BUCKET_NAME=your-bucket-name
GCS_VIDEO_PREFIX=videos/
GCS_AUDIO_PREFIX=audio/
GCS_URL_EXPIRY=3600
```

### Supabase (Job Queue)

```bash
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_KEY=your_service_key
```

### Vector Database

```bash
CHROMA_DB_PATH=./chroma_db
```

## Frontend Environment Variables

Create `frontend/.env`:

```bash
VITE_API_URL=http://localhost:8000

# Supabase (for real-time job updates)
VITE_SUPABASE_URL=https://your-project.supabase.co
VITE_SUPABASE_ANON_KEY=your_anon_key
```

## First-Time Setup

### 1. HuggingFace Token (Required for Speaker Diarization)

1. Create account at https://huggingface.co
2. Generate token at https://huggingface.co/settings/tokens
3. Accept pyannote terms at https://huggingface.co/pyannote/speaker-diarization
4. Add token to `HUGGINGFACE_TOKEN` in `.env`

### 2. Ollama (Optional, for Local LLM)

```bash
# Visit https://ollama.ai/ and install for your platform
# Pull a model:
ollama pull llama3.2:3b
```

### 3. First Backend Run

The backend will automatically download required ML models on first run (~500MB-2GB depending on configuration).
