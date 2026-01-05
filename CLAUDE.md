# AI-Subs Project Notes

## Google Cloud Deployment

### Project Details
- **GCP Project ID**: `ai-subs-poc`
- **Region**: `us-central1`
- **Cloud Run Service**: `ai-subs-backend`

### Artifact Registry
- **Repository Name**: `ai-subs-repo` (NOT `ai-subs`)
- **Full Image Path**: `us-central1-docker.pkg.dev/ai-subs-poc/ai-subs-repo/ai-subs-backend:latest`

### Build & Deploy Commands

```bash
# Build and push Docker image
cd backend
gcloud builds submit --tag us-central1-docker.pkg.dev/ai-subs-poc/ai-subs-repo/ai-subs-backend:latest --project=ai-subs-poc

# Deploy to Cloud Run
gcloud run deploy ai-subs-backend \
  --image=us-central1-docker.pkg.dev/ai-subs-poc/ai-subs-repo/ai-subs-backend:latest \
  --region=us-central1 \
  --project=ai-subs-poc
```

### Secrets Configuration
- `huggingface-token` - HuggingFace API token (linked to Cloud Run as `HUGGINGFACE_TOKEN`)

### Required Environment Variables
- `ENABLE_GCS_UPLOADS=true` - Required for screenshots to persist (Cloud Run storage is ephemeral)
- `GCS_BUCKET_NAME=ai-subs-uploads` - GCS bucket for video uploads and screenshots

### GCS Storage
- **Bucket**: `ai-subs-uploads`
- **Screenshots Path**: `screenshots/{video_hash}/{timestamp}.jpg`
- **Videos Path**: `uploads/{uuid}_{filename}`

### Service Account
- `1052285886390-compute@developer.gserviceaccount.com` (default compute service account)

## Models Pre-downloaded in Docker

The following models are downloaded during Docker build to avoid runtime rate limiting:
- Whisper (faster-whisper-small)
- Sentence Transformers (all-MiniLM-L6-v2)
- BART Summarization (facebook/bart-large-cnn)
- PANNs audio tagging
- Emotion recognition (wav2vec2)
- Translation models (MarianMT)
