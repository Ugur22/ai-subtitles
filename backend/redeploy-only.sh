#!/bin/bash
# Re-run only the deploy steps (no image rebuild) for the new Service+Job pair.
# Use after a successful Cloud Build when you only need to redeploy.

set -e
set -u

PROJECT_ID="ai-subs-poc"
REGION="us-central1"
SERVICE_NAME="ai-subs-backend"
WORKER_JOB_NAME="ai-subs-worker"
IMAGE="us-central1-docker.pkg.dev/ai-subs-poc/ai-subs-repo/ai-subs-backend:latest"
SA="1052285886390-compute@developer.gserviceaccount.com"

echo "==> Deploying Service (HTTP, no GPU)..."
gcloud run deploy "${SERVICE_NAME}" \
  --image="${IMAGE}" \
  --platform=managed \
  --region="${REGION}" \
  --project="${PROJECT_ID}" \
  --service-account="${SA}" \
  --memory=8Gi --cpu=2 \
  --timeout=300 --min-instances=0 --max-instances=2 --port=8000 \
  --allow-unauthenticated \
  --set-env-vars='CORS_ORIGINS=["https://ai-subs.netlify.app"],ENABLE_GCS_UPLOADS=true,GCS_BUCKET_NAME=ai-subs-uploads,SUPABASE_URL=https://ngfcjdxfhppnzpocgktw.supabase.co,XAI_MODEL=grok-4-1-fast-reasoning,ENVIRONMENT=production,MIN_SPEAKERS=1,MAX_SPEAKERS=0,FASTWHISPER_DEVICE=cuda,PUBLIC_APP_URL=https://ai-subs.netlify.app,WORKER_JOB_PROJECT=ai-subs-poc,WORKER_JOB_REGION=us-central1,WORKER_JOB_NAME=ai-subs-worker' \
  --set-secrets='SUPABASE_SERVICE_KEY=supabase-service-key:latest,APP_PASSWORD_HASH=app-password-hash:latest,HUGGINGFACE_TOKEN=huggingface-token:latest,GROQ_API_KEY=groq-api-key:latest,XAI_API_KEY=xai-api-key:latest,STRIPE_SECRET_KEY=stripe-secret-key:latest,STRIPE_PRO_PRICE_ID=stripe-pro-price-id:latest,STRIPE_WEBHOOK_SECRET=stripe-webhook-secret:latest'

echo ""
echo "==> Deploying Worker Job (GPU)..."
gcloud run jobs deploy "${WORKER_JOB_NAME}" \
  --image="${IMAGE}" \
  --region="${REGION}" \
  --project="${PROJECT_ID}" \
  --service-account="${SA}" \
  --memory=16Gi --cpu=4 \
  --gpu=1 --gpu-type=nvidia-l4 --no-gpu-zonal-redundancy \
  --task-timeout=3600 --max-retries=0 --parallelism=1 --tasks=1 \
  --command=python --args=-m,worker_main \
  --set-env-vars='ENABLE_GCS_UPLOADS=true,GCS_BUCKET_NAME=ai-subs-uploads,SUPABASE_URL=https://ngfcjdxfhppnzpocgktw.supabase.co,XAI_MODEL=grok-4-1-fast-reasoning,ENVIRONMENT=production,MIN_SPEAKERS=1,MAX_SPEAKERS=0,FASTWHISPER_DEVICE=cuda' \
  --set-secrets='SUPABASE_SERVICE_KEY=supabase-service-key:latest,HUGGINGFACE_TOKEN=huggingface-token:latest,GROQ_API_KEY=groq-api-key:latest,XAI_API_KEY=xai-api-key:latest'

echo ""
echo "==> Done. Service URL:"
gcloud run services describe "${SERVICE_NAME}" --region="${REGION}" --project="${PROJECT_ID}" --format='value(status.url)'
