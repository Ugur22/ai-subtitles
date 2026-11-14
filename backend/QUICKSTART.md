# Cloud Run Deployment - Quick Reference

Two resources, one image: the CPU Service `ai-subs-backend` (API) and the GPU Job `ai-subs-worker` (one execution per transcription job). `deploy.sh` defines both. Full guide: [DEPLOYMENT.md](DEPLOYMENT.md).

Run these from your own terminal with Owner credentials.

## Deploy

```bash
cd backend
./deploy.sh               # build + deploy Service and worker Job
./deploy.sh --skip-build  # redeploy both from the existing image
```

Apply new files in `sql/migrations/` to Supabase first.

## Scripts and files

| File | Purpose |
|------|---------|
| `deploy.sh` | Build and deploy the Service and the worker Job. Source of truth for resources, env vars and secrets. |
| `cloudbuild.yaml` | Cloud Build config used by `deploy.sh` |
| `Dockerfile` | Image shared by the Service and the Job |
| `worker_main.py` | Worker Job entrypoint |
| `scripts/rotate_encryption_key.py` | Re-encrypt stored user API keys after a key rotation |

## Status and logs

```bash
gcloud run services describe ai-subs-backend --region=us-central1 --project=ai-subs-poc \
  --format='value(status.url)'

gcloud run services logs read ai-subs-backend --region=us-central1 --project=ai-subs-poc --limit=50

gcloud run jobs executions list --job=ai-subs-worker --region=us-central1 --project=ai-subs-poc
```

The health endpoint is `GET /` on the Service URL and returns `{"status":"healthy",...}`.

## Change configuration

```bash
gcloud run services update ai-subs-backend --region=us-central1 --project=ai-subs-poc \
  --update-env-vars="VAR=value"
gcloud run jobs update ai-subs-worker --region=us-central1 --project=ai-subs-poc \
  --update-env-vars="VAR=value"

echo -n "new_value" | gcloud secrets versions add secret-name --data-file=- --project=ai-subs-poc
```

Mirror lasting changes in `deploy.sh`.

## Limits worth knowing

- A worker execution lasts at most 1 hour (Cloud Run GPU task cap). Long files continue across executions from per-chunk checkpoints, up to `MAX_JOB_CONTINUATIONS` (12).
- At most 3 jobs process at once (`GLOBAL_CONCURRENT_LIMIT` in `services/job_queue_service.py`); each uses one L4.
- The Service scales to zero. The worker costs nothing between jobs.
- Cloud Scheduler calls `POST /api/jobs/check-stale` every 5 minutes to recover stuck jobs.
