# GCP Operations

Resources, secrets and env vars for the Cloud Run service and the GPU worker job are defined in `backend/deploy.sh`, which is the source of truth. This page holds the operational notes that live outside it. Moved out of `CLAUDE.md` on 2026-10-27.

Run the commands below from your own terminal with Owner credentials, not from inside a Claude Code session.

### GCS Storage
- **Bucket**: `ai-subs-uploads`
- **Screenshots Path**: `screenshots/{video_hash}/{timestamp}.jpg`
- **Videos Path**: `uploads/{uuid}_{filename}`

### GPU Quota
Written for the earlier single-service GPU deploy; re-check the per-instance units against the GPU worker job in `backend/deploy.sh`.
- **Quota Name**: `NvidiaL4GpuAllocNoZonalRedundancyPerProjectRegion`
- **Default**: 3 units (need to request increase)
- **Per Instance**: 10 units
- **Request quota**: https://console.cloud.google.com/iam-admin/quotas?project=ai-subs-poc

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
