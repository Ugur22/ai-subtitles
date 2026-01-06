# AI-Subs Project Notes

## Google Cloud Deployment

### Project Details
- **GCP Project ID**: `ai-subs-poc`
- **Region**: `us-central1`
- **Cloud Run Service**: `ai-subs-backend`

### Artifact Registry
- **Repository Name**: `ai-subs-repo` (NOT `ai-subs`)
- **Full Image Path**: `us-central1-docker.pkg.dev/ai-subs-poc/ai-subs-repo/ai-subs-backend:latest`

### Deploy Backend

```bash
cd backend && ./deploy.sh
```

See `.claude/deployment.md` for full deployment details (secrets, env vars, resources).

### GCS Storage
- **Bucket**: `ai-subs-uploads`
- **Screenshots Path**: `screenshots/{video_hash}/{timestamp}.jpg`
- **Videos Path**: `uploads/{uuid}_{filename}`

### Service Account
- `1052285886390-compute@developer.gserviceaccount.com` (default compute service account)

### Secrets in Secret Manager
| Secret Name | Environment Variable | Purpose |
|-------------|---------------------|---------|
| `huggingface-token` | `HUGGINGFACE_TOKEN` | Speaker diarization models |
| `supabase-service-key` | `SUPABASE_SERVICE_KEY` | Database operations |
| `app-password-hash` | `APP_PASSWORD_HASH` | App authentication |
| `groq-api-key` | `GROQ_API_KEY` | Groq LLM chat |
| `xai-api-key` | `XAI_API_KEY` | Grok LLM chat |

### LLM Chat Configuration
- **Default Provider**: `grok`
- **Groq Model**: `llama-3.3-70b-versatile`
- **Grok Model**: `grok-4-1-fast-reasoning` (set via `XAI_MODEL` env var)

To update secrets:
```bash
echo -n "NEW_VALUE" | gcloud secrets versions add SECRET_NAME --data-file=- --project=ai-subs-poc
```

To update env vars (no rebuild needed):
```bash
gcloud run services update ai-subs-backend --platform=managed --region=us-central1 --project=ai-subs-poc --update-env-vars="VAR=value"
```

## Models Pre-downloaded in Docker

The following models are downloaded during Docker build to avoid runtime rate limiting:
- Whisper (faster-whisper-small)
- Sentence Transformers (all-MiniLM-L6-v2)
- BART Summarization (facebook/bart-large-cnn)
- PANNs audio tagging
- Emotion recognition (wav2vec2)
- Translation models (MarianMT)
