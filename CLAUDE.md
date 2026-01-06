# AI-Subs Project Notes

## Claude Behavior Rules

### CRITICAL: Plan Mode Required
For ANY non-trivial task, Claude MUST:
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
2. Claude enters plan mode (if non-trivial)
3. Claude explores the codebase
4. Claude writes a plan with specific changes
5. Claude asks user: "Ready to implement this plan?"
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
