# Cloud Run Deployment - Quick Start Guide

## Current Status

✅ **Deployment Complete**
- Service: `ai-subs-backend`
- Region: `us-central1`
- URL: https://REDACTED_BACKEND_URL
- Status: Healthy (HTTP 200)

✅ **Secrets Configured**
All sensitive data is now stored in Secret Manager:
- `supabase-service-key` ✓
- `app-password-hash` ✓
- `huggingface-token` ✓

## Quick Commands

### Deploy New Version

```bash
cd backend
./deploy.sh
```

This will:
1. Build Docker image with Cloud Build
2. Push to Artifact Registry
3. Deploy to Cloud Run
4. Verify health check

### Update Configuration Only

```bash
# Update environment variables
gcloud run services update ai-subs-backend \
  --region=us-central1 \
  --project=ai-subs-poc \
  --update-env-vars="NEW_VAR=value"
```

### Update Secrets

```bash
# Add new version to existing secret
echo -n "new_value" | gcloud secrets versions add secret-name \
  --data-file=- \
  --project=ai-subs-poc

# Service automatically uses latest version
```

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

### Check Service Status

```bash
# Get service URL
gcloud run services describe ai-subs-backend \
  --region=us-central1 \
  --project=ai-subs-poc \
  --format='value(status.url)'

# Test health endpoint
curl https://REDACTED_BACKEND_URL/

# Expected response:
# {"status":"healthy","service":"Video Transcription API","version":"1.0.0"}
```

## Available Scripts

| Script | Purpose |
|--------|---------|
| `deploy.sh` | Full deployment (build + deploy) |
| `deploy-yaml.sh` | Deploy using YAML config |
| `update-secrets.sh` | Update secret configuration |

## Configuration Files

| File | Purpose |
|------|---------|
| `Dockerfile` | Container image definition |
| `cloudrun-service.yaml` | Declarative service config |
| `DEPLOYMENT.md` | Comprehensive deployment guide |
| `QUICKSTART.md` | This file (quick reference) |

## Environment Variables

### Non-Sensitive (Plain Environment Variables)
- `CORS_ORIGINS`: `["https://REDACTED_FRONTEND_URL"]`
- `ENABLE_GCS_UPLOADS`: `true`
- `GCS_BUCKET_NAME`: `ai-subs-uploads`
- `SUPABASE_URL`: `https://REDACTED_SUPABASE_URL`

### Sensitive (Secret Manager)
- `SUPABASE_SERVICE_KEY`: From `supabase-service-key:latest`
- `APP_PASSWORD_HASH`: From `app-password-hash:latest`
- `HUGGINGFACE_TOKEN`: From `huggingface-token:latest`

## Resource Configuration

- **Memory**: 8Gi
- **CPU**: 2 cores
- **Timeout**: 300s (5 minutes)
- **Min Instances**: 0 (scales to zero)
- **Max Instances**: 3
- **Port**: 8000

## Useful Links

- **API Documentation**: https://REDACTED_BACKEND_URL/docs
- **Health Check**: https://REDACTED_BACKEND_URL/
- **GCP Console**: https://console.cloud.google.com/run/detail/us-central1/ai-subs-backend/metrics?project=ai-subs-poc
- **Cloud Build History**: https://console.cloud.google.com/cloud-build/builds?project=ai-subs-poc

## Troubleshooting

### Service not responding?
```bash
# Check if service is running
gcloud run services describe ai-subs-backend \
  --region=us-central1 \
  --project=ai-subs-poc

# View recent errors
gcloud run logs read ai-subs-backend \
  --project=ai-subs-poc \
  --region=us-central1 \
  --limit=100 | grep ERROR
```

### Secrets not working?
```bash
# Verify secret access
gcloud secrets get-iam-policy supabase-service-key --project=ai-subs-poc
gcloud secrets get-iam-policy app-password-hash --project=ai-subs-poc
gcloud secrets get-iam-policy huggingface-token --project=ai-subs-poc

# Should see: serviceAccount:1052285886390-compute@developer.gserviceaccount.com
# with role: roles/secretmanager.secretAccessor
```

### Build failing?
```bash
# View build logs
gcloud builds list --project=ai-subs-poc --limit=5

# Get specific build logs
gcloud builds log BUILD_ID --project=ai-subs-poc
```

## Security Best Practices

✅ **Implemented:**
- Secrets stored in Secret Manager (not env vars)
- Service account with minimal permissions
- CORS restricted to frontend domain
- IAM properly configured

⚠️ **Recommendations:**
- Rotate secrets regularly
- Monitor access logs
- Enable audit logging
- Use VPC connector for private resources (if needed)

## Cost Monitoring

Current configuration:
- **Scales to zero** when not in use = $0 when idle
- **Per-request billing** = Pay only for actual usage
- **Max 3 instances** = Cost cap during high traffic

Monitor costs:
```bash
# View cost breakdown in GCP Console
https://console.cloud.google.com/billing/01234-567890-ABCDEF?project=ai-subs-poc
```

## Next Steps

1. ✅ Deploy backend to Cloud Run
2. ✅ Configure secrets in Secret Manager
3. ✅ Update service to use secrets
4. ✅ Verify health checks passing
5. 🔲 Update frontend to use new backend URL
6. 🔲 Test end-to-end transcription flow
7. 🔲 Set up monitoring and alerts
8. 🔲 Configure custom domain (optional)

## Support

For detailed documentation, see `DEPLOYMENT.md`.

For API documentation, visit: https://REDACTED_BACKEND_URL/docs
