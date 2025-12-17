# AI Subtitles - Backend API

FastAPI-based backend server for AI-powered video transcription, subtitle generation, speaker diarization, and RAG-powered chat. Features local AI processing with Faster Whisper, multi-LLM provider support, and semantic search capabilities.

## Technology Stack

- **FastAPI** 0.104.1 - Modern async web framework
- **Uvicorn** 0.24.0 - ASGI server
- **Python** 3.9+

### AI & Machine Learning

- **Faster Whisper** 1.2.1 - Local speech-to-text (OpenAI Whisper optimized)
- **PyTorch** 2.7.0 - Deep learning framework
- **TorchAudio** 2.7.0 - Audio processing
- **Transformers** 4.38.2 - HuggingFace models (MarianMT translation, BART summarization)
- **Pyannote.audio** 3.1.1 - Speaker diarization and identification
- **Sentence Transformers** 2.2.2 - Text embeddings for semantic search

### LLM & RAG

- **ChromaDB** 0.4.22 - Vector database for semantic search
- **Groq** 0.4.2 - Groq cloud LLM client
- **OpenAI** 1.12.0 - OpenAI/Azure API client
- Multi-provider LLM support (Ollama, Groq, OpenAI, Anthropic)

### Media Processing

- **MoviePy** 1.0.3 - Video/audio manipulation
- **FFmpeg** - Required system dependency
- **AV** 13.1.0 - Audio/video container format handling

### Other

- **SQLite3** - Built-in database for transcription storage
- **python-dotenv** 1.0.0 - Environment configuration
- **NLTK** 3.9.1 - Natural language processing
- **Pydantic** 2.5.2 - Data validation

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
# Choose your LLM provider for chat/summarization
# Options: local (Ollama), groq, openai, anthropic
DEFAULT_LLM_PROVIDER=local

# --------------------------------------------
# Ollama Settings (Local LLM - Recommended)
# --------------------------------------------
# Install Ollama from: https://ollama.ai/
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=llama3.2:3b

# --------------------------------------------
# Groq Settings (Cloud - Fast)
# --------------------------------------------
GROQ_API_KEY=your_groq_api_key_here
GROQ_MODEL=llama-3.1-70b-versatile

# --------------------------------------------
# OpenAI Settings (Cloud)
# --------------------------------------------
OPENAI_API_KEY=your_openai_api_key_here
OPENAI_MODEL=gpt-4

# --------------------------------------------
# Anthropic Settings (Cloud)
# --------------------------------------------
ANTHROPIC_API_KEY=your_anthropic_api_key_here
ANTHROPIC_MODEL=claude-3-5-sonnet-20241022
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

- `file`: Audio/video file (MP4, MP3, WAV, WebM, etc.)
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

Streaming transcription endpoint for real-time updates.

#### `GET /transcriptions/`

List all saved transcriptions.

**Response:**

```json
[
  {
    "video_hash": "abc123...",
    "created_at": "2024-01-15T10:30:00",
    "file_path": "/path/to/video.mp4",
    "segment_count": 150
  }
]
```

#### `GET /transcription/{video_hash}`

Get specific transcription by video hash.

#### `DELETE /transcription/{video_hash}`

Delete transcription and associated data.

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

### Speaker Management

#### `POST /transcription/{video_hash}/speaker`

Update speaker name/label.

**Request:**

```json
{
  "old_speaker": "SPEAKER_00",
  "new_speaker": "John Doe"
}
```

### Search & RAG Chat

#### `POST /api/index_video/`

Index video transcription for semantic search.

**Request:**

```json
{
  "video_hash": "abc123..."
}
```

#### `POST /api/chat/`

Chat with video content using RAG (Retrieval-Augmented Generation).

**Request:**

```json
{
  "video_hash": "abc123...",
  "message": "What did they say about artificial intelligence?",
  "conversation_history": []
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
      "timestamp": "00:05:23"
    }
  ]
}
```

#### `GET /api/llm/providers`

List available LLM providers and their status.

#### `POST /api/llm/test`

Test LLM provider configuration.

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

Stream original video file.

#### `POST /update_file_path/{video_hash}`

Update path to original file if moved.

#### `POST /cleanup_screenshots/`

Clean up temporary screenshot files.

## Database Schema

The backend uses SQLite with the following main tables:

### `transcriptions`

- `video_hash` (TEXT, PRIMARY KEY)
- `created_at` (TIMESTAMP)
- `file_path` (TEXT)
- `language` (TEXT)
- `metadata` (JSON)

### `segments`

- `id` (INTEGER, PRIMARY KEY)
- `video_hash` (TEXT, FOREIGN KEY)
- `segment_index` (INTEGER)
- `start_time` (REAL)
- `end_time` (REAL)
- `text` (TEXT)
- `speaker` (TEXT)

### `translations`

- `video_hash` (TEXT)
- `segment_index` (INTEGER)
- `target_language` (TEXT)
- `translated_text` (TEXT)

## Project Structure

```
backend/
├── main.py                        # Main FastAPI application (API endpoints)
├── speaker_diarization.py         # Speaker identification module
├── llm_providers.py               # LLM abstraction layer
├── vector_store.py                # ChromaDB wrapper for RAG
├── requirements.txt               # Python dependencies
├── .env                           # Environment configuration (not in git)
├── .env.example                   # Environment template
├── Dockerfile                     # Docker container definition
├── docker-compose.yml             # Multi-service orchestration
├── REFACTORING_PLAN.md           # Code refactoring notes
├── static/                        # Static file storage
│   ├── screenshots/               # Extracted video screenshots
│   └── processed/                 # Processed audio files
├── transcriptions.db              # SQLite database
└── chroma_db/                     # ChromaDB vector storage
```

## Model Information

### Faster Whisper Models

| Model    | Size    | English-only | Multilingual | Relative Speed |
| -------- | ------- | ------------ | ------------ | -------------- |
| tiny     | 39 MB   | ✓            | ✓            | ~32x           |
| base     | 74 MB   | ✓            | ✓            | ~16x           |
| small    | 244 MB  | ✓            | ✓            | ~6x            |
| medium   | 769 MB  | ✓            | ✓            | ~2x            |
| large-v2 | 1550 MB | -            | ✓            | 1x             |
| large-v3 | 1550 MB | -            | ✓            | 1x             |

**Recommendation:**

- **Development/CPU:** `small` (good balance of speed/accuracy)
- **Production/GPU:** `large-v3` (best accuracy)
- **Quick testing:** `tiny` or `base`

### Speaker Diarization Model

Uses `pyannote/speaker-diarization-3.1` which requires:

- HuggingFace token
- Acceptance of model terms
- ~500MB download on first use

## Performance Optimization

### CPU Optimization

```bash
# Use int8 quantization for faster CPU inference
FASTWHISPER_COMPUTE_TYPE=int8
FASTWHISPER_MODEL=small
```

### GPU Optimization (NVIDIA)

```bash
# Install CUDA-enabled PyTorch first
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu118

# Configure for GPU
FASTWHISPER_DEVICE=cuda
FASTWHISPER_COMPUTE_TYPE=float16
FASTWHISPER_MODEL=large-v3
```

### Apple Silicon Optimization

```bash
# Use Metal Performance Shaders
FASTWHISPER_DEVICE=mps
FASTWHISPER_COMPUTE_TYPE=float16
FASTWHISPER_MODEL=medium
```

## Development

### Running with Auto-reload

```bash
source venv/bin/activate && uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

### Interactive API Documentation

Once running, visit:

- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

### Testing Endpoints

```bash
# Test transcription
curl -X POST "http://localhost:8000/transcribe_local/" \
  -H "Content-Type: multipart/form-data" \
  -F "file=@/path/to/video.mp4" \
  -F "language=en"

# Test LLM providers
curl -X GET "http://localhost:8000/api/llm/providers"

# Test chat
curl -X POST "http://localhost:8000/api/chat/" \
  -H "Content-Type: application/json" \
  -d '{"video_hash": "abc123", "message": "Summarize the main points"}'
```

## Troubleshooting

### Common Issues

**"ModuleNotFoundError: No module named 'torch'"**

```bash
# Ensure virtual environment is activated
source venv/bin/activate
pip install -r requirements.txt
```

**"FFmpeg not found"**

```bash
# macOS
brew install ffmpeg

# Ubuntu/Debian
sudo apt-get install ffmpeg

# Verify installation
ffmpeg -version
```

**"HuggingFace authentication failed"**

```bash
# Verify token is set in .env
cat .env | grep HUGGINGFACE_TOKEN

# Ensure you accepted model terms
# Visit: https://huggingface.co/pyannote/speaker-diarization-3.1
```

**"Ollama connection refused"**

```bash
# Start Ollama service
ollama serve

# Verify it's running
curl http://localhost:11434

# Pull required model
ollama pull llama3.2:3b
```

**"CUDA out of memory"**

```bash
# Reduce model size or use CPU
FASTWHISPER_MODEL=small
FASTWHISPER_DEVICE=cpu
```

**Port 8000 already in use**

```bash
# Find and kill process
lsof -ti:8000 | xargs kill -9

# Or use different port
uvicorn main:app --reload --port 8001
```

## Deployment

For production deployment instructions, see:

- [General Deployment Guide](../docs/DEPLOYMENT.md)
- [AWS Deployment Guide](../docs/AWS_DEPLOYMENT.md)

### Docker Deployment

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

## CORS Configuration

By default, the API allows requests from `http://localhost:5173` (Vite dev server).

To add additional origins, edit `main.py`:

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "https://yourdomain.com"  # Add your production domain
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

## Contributing

When contributing to the backend:

1. Follow PEP 8 style guidelines
2. Add type hints to function signatures
3. Update API documentation if adding endpoints
4. Test endpoints with sample data
5. Update this README if adding features

## Security Notes

- Never commit `.env` file to version control
- Keep API keys secure and rotate regularly
- Use environment variables for all sensitive data
- Consider rate limiting for production deployments
- Validate and sanitize all user inputs
- Use HTTPS in production

## Related Documentation

- **[Main README](../README.md)** - Project overview and quick start
- **[Frontend README](../frontend/README.md)** - Frontend setup and development
- **[Deployment Guide](../docs/DEPLOYMENT.md)** - Production deployment
- **[AWS Deployment](../docs/AWS_DEPLOYMENT.md)** - AWS-specific deployment
- **[Speaker Diarization Setup](../docs/SPEAKER_DIARIZATION_SETUP.md)** - Detailed diarization guide

## License

[Add your license here]
