# AI-Subs Project Notes

## Codex Behavior Rules

### CRITICAL: Plan Mode Required
For ANY non-trivial task, Codex MUST:
1. Enter plan mode FIRST using `EnterPlanMode`
2. Explore and understand the issue
3. Write a detailed plan
4. Get explicit user approval before implementing

**Non-trivial tasks include:**
- Bug fixes
- Code changes
- Feature additions
- Refactoring
- Configuration changes
- ANY deployment

**Only skip plan mode for:**
- Simple questions/explanations
- Reading files for information
- Trivial typo fixes (single character)

### NEVER Do Without Approval
- NEVER make code changes without presenting a plan first
- NEVER deploy to GCloud (`./deploy.sh`, `gcloud run deploy`, `gcloud builds submit`)
- NEVER commit to git without explicit approval
- NEVER assume the user wants changes implemented - always confirm

### Required Workflow
1. User requests something
2. Codex enters plan mode (if non-trivial)
3. Codex explores the codebase
4. Codex writes a plan with specific changes
5. Codex asks user: "Ready to implement this plan?"
6. WAIT for explicit approval
7. Only then implement changes
8. After changes, ask: "Deploy to GCloud?" - WAIT for approval
9. Only deploy after explicit "yes"

---

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

See `.Codex/deployment.md` for full deployment details (secrets, env vars, resources).

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

### Environment Variables (REQUIRED for deployment)
| Variable | Value | Purpose |
|----------|-------|---------|
| `CORS_ORIGINS` | `["https://ai-subs.netlify.app"]` | Frontend URL for CORS |
| `ENABLE_GCS_UPLOADS` | `true` | Enable GCS for persistent storage |
| `GCS_BUCKET_NAME` | `ai-subs-uploads` | GCS bucket name |
| `SUPABASE_URL` | `https://ngfcjdxfhppnzpocgktw.supabase.co` | Supabase instance URL |

### Resource Configuration (Cloud Run with GPU)
| Setting | Value |
|---------|-------|
| Memory | `16Gi` |
| CPU | `4` |
| GPU | `1x nvidia-l4` |
| GPU Zonal Redundancy | `false` (requires less quota) |
| Timeout | `300` seconds |
| Min instances | `0` |
| Max instances | `1` (requires 10 quota units per instance) |
| Port | `8000` |

### GPU Quota
- **Quota Name**: `NvidiaL4GpuAllocNoZonalRedundancyPerProjectRegion`
- **Default**: 3 units (need to request increase)
- **Per Instance**: 10 units
- **Request quota**: https://console.cloud.google.com/iam-admin/quotas?project=ai-subs-poc

### Full Deploy Command Reference
```bash
gcloud run deploy ai-subs-backend \
  --image=us-central1-docker.pkg.dev/ai-subs-poc/ai-subs-repo/ai-subs-backend:latest \
  --platform=managed \
  --region=us-central1 \
  --project=ai-subs-poc \
  --service-account=1052285886390-compute@developer.gserviceaccount.com \
  --memory=16Gi \
  --cpu=4 \
  --gpu=1 \
  --gpu-type=nvidia-l4 \
  --no-gpu-zonal-redundancy \
  --timeout=300 \
  --min-instances=0 \
  --max-instances=1 \
  --port=8000 \
  --allow-unauthenticated \
  --set-env-vars="CORS_ORIGINS=[\"https://ai-subs.netlify.app\"],ENABLE_GCS_UPLOADS=true,GCS_BUCKET_NAME=ai-subs-uploads,SUPABASE_URL=https://ngfcjdxfhppnzpocgktw.supabase.co" \
  --set-secrets="SUPABASE_SERVICE_KEY=supabase-service-key:latest,APP_PASSWORD_HASH=app-password-hash:latest,HUGGINGFACE_TOKEN=huggingface-token:latest,GROQ_API_KEY=groq-api-key:latest,XAI_API_KEY=xai-api-key:latest" \
  --no-cpu-throttling
```

### Scheduled Jobs (Cloud Scheduler)

| Job | Endpoint | Frequency | Purpose |
|-----|----------|-----------|---------|
| `check-stale` | `POST /api/jobs/check-stale` | every 5 min | Recover jobs stuck in `processing` after worker crash |
| `refresh-screenshot-urls` | `POST /api/jobs/refresh-screenshot-urls` | daily at 03:00 UTC | Re-sign GCS screenshot URLs in `jobs.result_json` + `image_embeddings` so V4 URLs (7-day cap) never go stale at rest |

Create the URL refresh job (auth must match `check-stale` — clone whatever mechanism that one uses):

```bash
gcloud scheduler jobs create http refresh-screenshot-urls \
  --project=ai-subs-poc \
  --location=us-central1 \
  --schedule="0 3 * * *" \
  --time-zone="UTC" \
  --uri="https://ai-subs-backend-1052285886390.us-central1.run.app/api/jobs/refresh-screenshot-urls" \
  --http-method=POST \
  --headers="Content-Type=application/json" \
  --message-body='{}' \
  --attempt-deadline=300s
```

Trigger manually:
```bash
gcloud scheduler jobs run refresh-screenshot-urls --location=us-central1 --project=ai-subs-poc
```

Tunables (set via `--update-env-vars`): `URL_REFRESH_CUTOFF_DAYS` (default 30), `URL_REFRESH_BATCH_SIZE` (default 100).

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
