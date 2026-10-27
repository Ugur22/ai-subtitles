# Backend Deployment Instructions

## Quick Deploy

```bash
cd backend
./deploy.sh
```

This single command handles everything: build, push, and deploy with all environment variables.

## GCP Configuration

| Setting | Value |
|---------|-------|
| Project ID | `ai-subs-poc` |
| Region | `us-central1` |
| Service | `ai-subs-backend` |
| Image | `us-central1-docker.pkg.dev/ai-subs-poc/ai-subs-repo/ai-subs-backend:latest` |
| Service Account | `1052285886390-compute@developer.gserviceaccount.com` |

## Secrets (in Secret Manager)

All sensitive values are stored in Google Secret Manager - NOT as plain environment variables:

| Secret Name | Environment Variable | Purpose |
|-------------|---------------------|---------|
| `huggingface-token` | `HUGGINGFACE_TOKEN` | HuggingFace API access |
| `supabase-service-key` | `SUPABASE_SERVICE_KEY` | Supabase database access |
| `app-password-hash` | `APP_PASSWORD_HASH` | Password protection |
| `groq-api-key` | `GROQ_API_KEY` | Groq LLM chat |
| `xai-api-key` | `XAI_API_KEY` | Grok/xAI LLM chat |

## Environment Variables (Non-sensitive)

These are set directly in `deploy.sh`:

| Variable | Value |
|----------|-------|
| `CORS_ORIGINS` | `["https://ai-subs.netlify.app"]` |
| `ENABLE_GCS_UPLOADS` | `true` |
| `GCS_BUCKET_NAME` | `ai-subs-uploads` |
| `SUPABASE_URL` | `https://ngfcjdxfhppnzpocgktw.supabase.co` |
| `XAI_MODEL` | `grok-4-1-fast-reasoning` |

## LLM Chat Configuration

| Provider | Model | Secret |
|----------|-------|--------|
| Groq | `llama-3.3-70b-versatile` | `groq-api-key` |
| Grok (xAI) | `grok-4-1-fast-reasoning` | `xai-api-key` |

To update secrets (no rebuild):
```bash
echo -n "NEW_VALUE" | gcloud secrets versions add SECRET_NAME --data-file=- --project=ai-subs-poc
```

To update env vars (no rebuild):
```bash
gcloud run services update ai-subs-backend --platform=managed --region=us-central1 --project=ai-subs-poc --update-env-vars="VAR=value"
```

## Resource Configuration

| Resource | Value |
|----------|-------|
| Memory | 8Gi |
| CPU | 2 |
| Timeout | 300s |
| Min instances | 0 |
| Max instances | 3 |
| Port | 8000 |

## Deployment Scripts

| Script | Purpose |
|--------|---------|
| `backend/deploy.sh` | Full build and deploy |
| `backend/deploy-yaml.sh` | Deploy using YAML config |
| `backend/update-secrets.sh` | Update secrets only (no rebuild) |
| `backend/cloudrun-service.yaml` | Declarative service config |

## Frontend Deployment

Frontend auto-deploys via Netlify on push to main branch.
- URL: https://ai-subs.netlify.app

## Service URLs

- **Backend API**: https://ai-subs-backend-1052285886390.us-central1.run.app
- **API Docs**: https://ai-subs-backend-1052285886390.us-central1.run.app/docs
- **Frontend**: https://ai-subs.netlify.app
