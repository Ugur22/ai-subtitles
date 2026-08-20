# AI-Subs Production Deployment Configuration Guide

This document provides step-by-step instructions for configuring the AI-Subs production environment across Cloud Run (backend) and Netlify (frontend).

## Prerequisites

- Google Cloud CLI (`gcloud`) installed and authenticated
- Access to the GCP project: `ai-subs-backend` (project number: 1052285886390)
- Access to the Netlify dashboard for the ai-subs site
- Docker installed (for building images locally)

## 1. Cloud Run CORS Configuration

The backend needs CORS configured to allow requests from the Netlify frontend.

### Update CORS Environment Variable

```bash
# Set the project
gcloud config set project ai-subs-backend

# Update the Cloud Run service with CORS origins
gcloud run services update ai-subs-backend \
  --region=us-central1 \
  --update-env-vars='CORS_ORIGINS=["https://REDACTED_FRONTEND_URL","http://localhost:5173"]'
```

### Verify CORS Configuration

```bash
# Check current environment variables
gcloud run services describe ai-subs-backend \
  --region=us-central1 \
  --format='yaml(spec.template.spec.containers[0].env)'
```

### How CORS is Processed

The backend (`/Users/ugurertas/projects/ai-subs/backend/config.py`) parses the `CORS_ORIGINS` environment variable as a JSON array:

```python
# From config.py - CORS_ORIGINS property
cors_env = os.getenv("CORS_ORIGINS")
if cors_env:
    origins = json.loads(cors_env)  # Expects JSON array format
```

**Important**: The value must be a valid JSON array string. Single quotes around the entire value, double quotes for array elements.

---

## 2. Netlify Frontend Environment Variable

The frontend needs to know the backend API URL.

### Setting via Netlify CLI

```bash
# Install Netlify CLI if not already installed
npm install -g netlify-cli

# Login to Netlify
netlify login

# Link to your site (run from frontend directory)
cd /Users/ugurertas/projects/ai-subs/frontend
netlify link

```

### Trigger a Rebuild

After setting the environment variable, you must trigger a new build for the changes to take effect:

**Option A: Via Dashboard**

1. Go to **Deploys** tab
2. Click **Trigger deploy** > **Deploy site**

**Option B: Via CLI**

```bash
netlify deploy --build --prod
```

**Option C: Push a commit**
Any new commit to the main branch will trigger a rebuild with the new environment variable.

### Local Development Reference

For local development, create or update `/Users/ugurertas/projects/ai-subs/frontend/.env`:

```bash
VITE_API_URL=http://localhost:8000
```

---

## 3. Supabase Database Setup

The backend uses Supabase (Postgres + pgvector) as the metadata and vector store in production, and a SQLite drop-in (`LOCAL_MODE=true`) for local development. See [Configuration Guide](CONFIGURATION.md) for `SUPABASE_URL`/`SUPABASE_SERVICE_KEY` setup and the project's `CLAUDE.md` for secret management via Secret Manager.

---

## 4. Full Deployment Commands

Complete sequence for deploying updates to the backend.

### Step 1: Build and Push Docker Image

```bash
# Navigate to backend directory
cd /Users/ugurertas/projects/ai-subs/backend

# Set project and configure Docker for GCR
gcloud config set project ai-subs-backend
gcloud auth configure-docker us-central1-docker.pkg.dev

# Build the Docker image
docker build -t us-central1-docker.pkg.dev/ai-subs-backend/ai-subs/backend:latest .

# Push to Artifact Registry
docker push us-central1-docker.pkg.dev/ai-subs-backend/ai-subs/backend:latest
```

**Alternative: Build with Cloud Build (no local Docker required)**

```bash
# Submit build to Cloud Build
gcloud builds submit \
  --tag us-central1-docker.pkg.dev/ai-subs-backend/ai-subs/backend:latest \
  --region=us-central1
```

### Step 2: Deploy to Cloud Run

```bash
# Deploy with all environment variables
gcloud run deploy ai-subs-backend \
  --image=us-central1-docker.pkg.dev/ai-subs-backend/ai-subs/backend:latest \
  --region=us-central1 \
  --platform=managed \
  --allow-unauthenticated \
  --memory=4Gi \
  --cpu=2 \
  --timeout=3600 \
  --set-env-vars='CORS_ORIGINS=["https://REDACTED_FRONTEND_URL","http://localhost:5173"]' \
  --set-env-vars='ENABLE_GCS_UPLOADS=true' \
  --set-env-vars='GCS_BUCKET_NAME=ai-subs-uploads'
```

### Step 3: Set Sensitive Environment Variables

For API keys and tokens, use `--update-env-vars` separately or use Secret Manager:

```bash
# Using environment variables directly (less secure, but simpler)
gcloud run services update ai-subs-backend \
  --region=us-central1 \
  --update-env-vars='HUGGINGFACE_TOKEN=your_token_here' \
  --update-env-vars='GROQ_API_KEY=your_groq_key_here'

# Using Secret Manager (recommended for production)
# First, create secrets
gcloud secrets create huggingface-token --replication-policy="automatic"
echo -n "your_token_here" | gcloud secrets versions add huggingface-token --data-file=-

# Then reference in Cloud Run
gcloud run services update ai-subs-backend \
  --region=us-central1 \
  --update-secrets='HUGGINGFACE_TOKEN=huggingface-token:latest'
```

### Step 4: Verify Deployment

````bash
# Check service status
gcloud run services describe ai-subs-backend \
  --region=us-central1 \
  --format='yaml(status)'

# Check latest revision
gcloud run revisions list \
  --service=ai-subs-backend \
  --region=us-central1 \
  --limit=3

## 5. Complete Environment Variables Reference

### Required for Production

| Variable               | Value                                                     | Description                      |
| ---------------------- | --------------------------------------------------------- | -------------------------------- |
| `CORS_ORIGINS`         | `["","http://localhost:5173"]` | Allowed origins for CORS         |
| `SUPABASE_URL`         | `https://your-project.supabase.co`                        | Supabase instance URL            |
| `SUPABASE_SERVICE_KEY` | `service-role-key`                                         | Supabase service role key        |
| `HUGGINGFACE_TOKEN`    | `hf_xxx...`                                               | Required for speaker diarization |

### Optional Configuration

| Variable                     | Default           | Description                   |
| ---------------------------- | ----------------- | ----------------------------- |
| `ENABLE_GCS_UPLOADS`         | `false`           | Enable GCS for file uploads   |
| `GCS_BUCKET_NAME`            | `ai-subs-uploads` | GCS bucket name               |
| `FASTWHISPER_MODEL`          | `small`           | Whisper model size            |
| `FASTWHISPER_DEVICE`         | `cpu`             | Device for inference          |
| `ENABLE_SPEAKER_DIARIZATION` | `true`            | Enable speaker identification |
| `DEFAULT_LLM_PROVIDER`       | `ollama`          | LLM provider for features     |
| `GROQ_API_KEY`               | -                 | Groq API key for cloud LLM    |

### Set All Variables at Once

```bash
gcloud run services update ai-subs-backend \
  --region=us-central1 \
  --set-env-vars='
CORS_ORIGINS=["https://REDACTED_FRONTEND_URL","http://localhost:5173"],
ENABLE_GCS_UPLOADS=true,
GCS_BUCKET_NAME=ai-subs-uploads,
FASTWHISPER_MODEL=small,
FASTWHISPER_DEVICE=cpu,
ENABLE_SPEAKER_DIARIZATION=true,
DEFAULT_LLM_PROVIDER=groq
'
````

---

## 6. Troubleshooting

### CORS Errors in Browser

**Symptom**: Browser console shows `Access-Control-Allow-Origin` errors

**Solutions**:

1. Verify `CORS_ORIGINS` is set correctly:
   ```bash
   gcloud run services describe ai-subs-backend --region=us-central1 --format='yaml(spec.template.spec.containers[0].env)'
   ```
2. Ensure the origin URL matches exactly (including protocol, no trailing slash)
3. Check Cloud Run logs for CORS-related warnings:
   ```bash
   gcloud run services logs read ai-subs-backend --region=us-central1 --limit=50
   ```

### Supabase Connection Issues

**Symptom**: Database errors in logs

**Solutions**:

1. Verify `SUPABASE_URL` and `SUPABASE_SERVICE_KEY` are set correctly:
   ```bash
   gcloud run services describe ai-subs-backend --region=us-central1 --format='yaml(spec.template.spec.containers[0].env)'
   ```
2. Check the Supabase project dashboard for outages or RLS policy issues

### Deployment Failures

**Symptom**: Cloud Run deployment fails

**Solutions**:

1. Check build logs:
   ```bash
   gcloud builds list --limit=5
   gcloud builds log BUILD_ID
   ```
2. Verify Docker image exists:
   ```bash
   gcloud artifacts docker images list us-central1-docker.pkg.dev/ai-subs-backend/ai-subs
   ```
3. Check Cloud Run logs for startup errors:
   ```bash
   gcloud run services logs read ai-subs-backend --region=us-central1 --limit=100
   ```

### Frontend Not Using Updated API URL

**Symptom**: Frontend still calling old API URL after changing `VITE_API_URL`

**Solutions**:

1. Trigger a new Netlify build (environment variables are baked in at build time)
2. Clear browser cache or use incognito mode
3. Verify the variable is set:
   ```bash
   netlify env:list
   ```

---

## 7. Quick Reference Commands

```bash
# View current Cloud Run configuration
gcloud run services describe ai-subs-backend --region=us-central1

# View Cloud Run logs (live)
gcloud run services logs tail ai-subs-backend --region=us-central1

# Update a single environment variable
gcloud run services update ai-subs-backend --region=us-central1 --update-env-vars='KEY=value'

# Remove an environment variable
gcloud run services update ai-subs-backend --region=us-central1 --remove-env-vars='KEY'

# Scale to zero when not in use (cost saving)
gcloud run services update ai-subs-backend --region=us-central1 --min-instances=0

# Force a new revision without changes (restart)
gcloud run services update ai-subs-backend --region=us-central1 --no-traffic
gcloud run services update-traffic ai-subs-backend --region=us-central1 --to-latest
```

---

## Document Information

- **Last Updated**: 2026-01-02
- **Project**: ai-subs
- **Author**: Generated from production configuration analysis
