# AI-Subs Backend - Cloud Run Deployment Guide

This guide covers deploying the AI-Subs backend to Google Cloud Run with proper configuration and secret management.

## Prerequisites

- Google Cloud SDK (`gcloud`) installed
- Authenticated with GCP: `gcloud auth login`
- Project access: `ai-subs-poc`
- Required APIs enabled:
  - Cloud Run API
  - Cloud Build API
  - Secret Manager API
  - Container Registry API

## Project Configuration

**GCP Project Details:**
- Project ID: `ai-subs-poc`
- Region: `us-central1`
- Service Name: `ai-subs-backend`
- Image Repository: `us-central1-docker.pkg.dev/ai-subs-poc/ai-subs-repo/ai-subs-backend`
- Service Account: `1052285886390-compute@developer.gserviceaccount.com`

**Resource Configuration:**
- Memory: 8Gi
- CPU: 2 cores
- Timeout: 300 seconds (5 minutes)
- Min instances: 0 (scales to zero)
- Max instances: 3
- Port: 8000

## Secrets Management

The deployment uses Google Secret Manager for sensitive data:

### Secrets Configuration

| Secret Name | Description | Purpose |
|------------|-------------|---------|
| `huggingface-token` | HuggingFace API token | Speaker diarization models |
| `supabase-service-key` | Supabase service role key | Database operations |
| `app-password-hash` | SHA-256 hash of app password | Authentication |

### Creating Secrets (Already Done)

```bash
# Create supabase-service-key
echo -n "YOUR_SUPABASE_KEY" | gcloud secrets create supabase-service-key \
  --data-file=- --project=ai-subs-poc

# Create app-password-hash
echo -n "YOUR_PASSWORD_HASH" | gcloud secrets create app-password-hash \
  --data-file=- --project=ai-subs-poc

# Grant access to service account
gcloud secrets add-iam-policy-binding supabase-service-key \
  --member="serviceAccount:1052285886390-compute@developer.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor" \
  --project=ai-subs-poc

gcloud secrets add-iam-policy-binding app-password-hash \
  --member="serviceAccount:1052285886390-compute@developer.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor" \
  --project=ai-subs-poc
```

## Environment Variables

### Non-Sensitive Variables (Set in deployment)

| Variable | Value | Purpose |
|----------|-------|---------|
| `CORS_ORIGINS` | `["https://REDACTED_FRONTEND_URL"]` | Frontend URL for CORS |
| `ENABLE_GCS_UPLOADS` | `true` | Enable GCS for persistent storage |
| `GCS_BUCKET_NAME` | `ai-subs-uploads` | GCS bucket name |
| `SUPABASE_URL` | `https://REDACTED_SUPABASE_URL` | Supabase instance URL |

### Secret Variables (From Secret Manager)

| Variable | Secret | Purpose |
|----------|--------|---------|
| `SUPABASE_SERVICE_KEY` | `supabase-service-key:latest` | Database auth |
| `APP_PASSWORD_HASH` | `app-password-hash:latest` | App authentication |
| `HUGGINGFACE_TOKEN` | `huggingface-token:latest` | Model downloads |

## Deployment Methods

### Method 1: Using deploy.sh (Recommended)

The `deploy.sh` script handles the entire deployment process:

```bash
cd backend
./deploy.sh
```

**What it does:**
1. Checks prerequisites (gcloud authentication, etc.)
2. Builds Docker image using Cloud Build
3. Pushes image to Artifact Registry
4. Deploys to Cloud Run with all configurations
5. Retrieves and displays service URL
6. Runs health check verification

### Method 2: Using YAML Configuration

For declarative deployments:

```bash
cd backend
./deploy-yaml.sh
```

This uses the `cloudrun-service.yaml` file for deployment configuration.

### Method 3: Manual Deployment

If you need to deploy manually:

```bash
# 1. Build and push image
cd backend
gcloud builds submit \
  --tag us-central1-docker.pkg.dev/ai-subs-poc/ai-subs-repo/ai-subs-backend:latest \
  --project=ai-subs-poc

# 2. Deploy to Cloud Run
gcloud run deploy ai-subs-backend \
  --image=us-central1-docker.pkg.dev/ai-subs-poc/ai-subs-repo/ai-subs-backend:latest \
  --platform=managed \
  --region=us-central1 \
  --project=ai-subs-poc \
  --service-account=1052285886390-compute@developer.gserviceaccount.com \
  --memory=8Gi \
  --cpu=2 \
  --timeout=300 \
  --min-instances=0 \
  --max-instances=3 \
  --port=8000 \
  --allow-unauthenticated \
  --set-env-vars="CORS_ORIGINS=[\"https://REDACTED_FRONTEND_URL\"],ENABLE_GCS_UPLOADS=true,GCS_BUCKET_NAME=ai-subs-uploads,SUPABASE_URL=https://REDACTED_SUPABASE_URL" \
  --set-secrets="SUPABASE_SERVICE_KEY=supabase-service-key:latest,APP_PASSWORD_HASH=app-password-hash:latest,HUGGINGFACE_TOKEN=huggingface-token:latest" \
  --no-cpu-throttling
```

## Monitoring and Debugging

### View Logs

```bash
# Tail logs in real-time
gcloud run logs tail ai-subs-backend \
  --project=ai-subs-poc \
  --region=us-central1

# View recent logs
gcloud run logs read ai-subs-backend \
  --project=ai-subs-poc \
  --region=us-central1 \
  --limit=50
```

### View Service Details

```bash
# Get service URL
gcloud run services describe ai-subs-backend \
  --platform=managed \
  --region=us-central1 \
  --project=ai-subs-poc \
  --format='value(status.url)'

# Get full service configuration
gcloud run services describe ai-subs-backend \
  --platform=managed \
  --region=us-central1 \
  --project=ai-subs-poc
```

### Health Check

```bash
# Test the health endpoint
SERVICE_URL=$(gcloud run services describe ai-subs-backend \
  --platform=managed \
  --region=us-central1 \
  --project=ai-subs-poc \
  --format='value(status.url)')

curl ${SERVICE_URL}/
```

## Troubleshooting

### Common Issues

**1. Secret Access Denied**
- Ensure service account has `secretmanager.secretAccessor` role
- Verify secrets exist in Secret Manager
- Check secret versions are `latest`

**2. Memory/CPU Limits Exceeded**
- Increase memory limit if cold starts fail
- Monitor logs for OOM (Out of Memory) errors
- Consider increasing timeout for large video processing

**3. Cold Start Timeouts**
- Models are pre-downloaded in Docker image
- Startup probe allows 5 minutes for cold start
- Consider setting `min-instances=1` for production

**4. CORS Errors**
- Update `CORS_ORIGINS` environment variable
- Ensure frontend URL matches exactly (including https://)

**5. GCS Upload Failures**
- Verify service account has Storage Object Admin role
- Check `GCS_BUCKET_NAME` is correct
- Ensure bucket exists and is in same region

### Debug Commands

```bash
# Check service account permissions
gcloud projects get-iam-policy ai-subs-poc \
  --flatten="bindings[].members" \
  --filter="bindings.members:1052285886390-compute@developer.gserviceaccount.com"

# List all secrets
gcloud secrets list --project=ai-subs-poc

# Check secret access
gcloud secrets get-iam-policy supabase-service-key --project=ai-subs-poc
gcloud secrets get-iam-policy app-password-hash --project=ai-subs-poc
gcloud secrets get-iam-policy huggingface-token --project=ai-subs-poc

# View Cloud Build logs
gcloud builds list --project=ai-subs-poc --limit=5
```

## Updating Configuration

### Update Environment Variables

```bash
gcloud run services update ai-subs-backend \
  --platform=managed \
  --region=us-central1 \
  --project=ai-subs-poc \
  --update-env-vars="NEW_VAR=value"
```

### Update Secrets

```bash
# Add new secret version
echo -n "new_value" | gcloud secrets versions add secret-name \
  --data-file=- \
  --project=ai-subs-poc

# Service will automatically use 'latest' version
```

### Update Resource Limits

```bash
gcloud run services update ai-subs-backend \
  --platform=managed \
  --region=us-central1 \
  --project=ai-subs-poc \
  --memory=16Gi \
  --cpu=4
```

## Cost Optimization

**Current Configuration:**
- Scales to zero when not in use (no cost)
- Max 3 instances for high traffic
- 8Gi memory, 2 CPU per instance

**Tips:**
- Monitor actual resource usage in Cloud Console
- Adjust memory/CPU based on actual needs
- Consider increasing `min-instances` for production (reduces cold starts but increases cost)
- Use Cloud Build for image builds (more reliable than local builds)

## Security Considerations

1. **Secrets Management**: All sensitive data stored in Secret Manager
2. **Service Account**: Dedicated service account with minimal permissions
3. **Authentication**: App password protection via `APP_PASSWORD_HASH`
4. **CORS**: Strict CORS policy (only allows frontend domain)
5. **IAM**: Service account has only required permissions
6. **Network**: Public access enabled for API endpoints

## Files in This Directory

- `deploy.sh` - Main deployment script (recommended)
- `deploy-yaml.sh` - YAML-based deployment script
- `cloudrun-service.yaml` - Declarative service configuration
- `Dockerfile` - Container image definition
- `DEPLOYMENT.md` - This file (deployment documentation)

## Additional Resources

- [Cloud Run Documentation](https://cloud.google.com/run/docs)
- [Secret Manager Documentation](https://cloud.google.com/secret-manager/docs)
- [Cloud Build Documentation](https://cloud.google.com/build/docs)
- [GCS Documentation](https://cloud.google.com/storage/docs)
