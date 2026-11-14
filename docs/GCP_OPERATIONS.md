# GCP Operations

Resources, secrets and env vars for the Cloud Run service and the GPU worker job are defined in `backend/deploy.sh`, which is the source of truth. This page holds the operational notes that live outside it. Moved out of `CLAUDE.md` on 2026-10-27.

Run the commands below from your own terminal with Owner credentials, not from inside a Claude Code session.

### GCS Storage
- **Bucket**: `ai-subs-uploads`
- **Screenshots Path**: `screenshots/{video_hash}/{filename}`
- **Uploads Path**: `uploads/{user_id}/{upload_intent_id}/{filename}`
- **Processed Path**: `processed/{user_id}/{upload_intent_id}/{filename}` (copied at finalization; the upload is then deleted through the media-delete outbox)

### GPU Quota
Each worker execution uses one L4 without zonal redundancy, and up to 3 jobs process at once (`GLOBAL_CONCURRENT_LIMIT` in `backend/services/job_queue_service.py`), so the quota must cover 3 concurrent executions. A continuation starts while the previous execution is still shutting down, so it can briefly need one more. The unit figures below were written for the earlier single-service GPU deploy; confirm them in the console.
- **Quota Name**: `NvidiaL4GpuAllocNoZonalRedundancyPerProjectRegion`
- **Default**: 3 units (need to request increase)
- **Request quota**: https://console.cloud.google.com/iam-admin/quotas?project=ai-subs-poc

### Scheduled Jobs (Cloud Scheduler)

| Job | Endpoint | Frequency | Purpose |
|-----|----------|-----------|---------|
| `check-stale` | `POST /api/jobs/check-stale` | every 5 min | Recover one stuck job per call: stale `finalizing`, a `worker_timeout` failure (one automatic retry), stale `processing` (no heartbeat for 90s), or `pending` for over 10 min. Also drains pending media deletions. |
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
- **Grok Model**: set via the `XAI_MODEL` env var in `backend/deploy.sh`

To update secrets:
```bash
echo -n "NEW_VALUE" | gcloud secrets versions add SECRET_NAME --data-file=- --project=ai-subs-poc
```

To update env vars (no rebuild needed):
```bash
gcloud run services update ai-subs-backend --platform=managed --region=us-central1 --project=ai-subs-poc --update-env-vars="VAR=value"
gcloud run jobs update ai-subs-worker --region=us-central1 --project=ai-subs-poc --update-env-vars="VAR=value"
```
Mirror lasting changes in `backend/deploy.sh`, or the next deploy reverts them.

### Long jobs, continuations and timeouts

A worker execution is limited to 1 hour (`--task-timeout=3600`, the Cloud Run maximum for GPU tasks). Long files are checkpointed per 5-minute chunk and continued in a new execution; see "Long files" in [ARCHITECTURE.md](ARCHITECTURE.md).

| Setting | Default | Where | Meaning |
|---------|---------|-------|---------|
| `CLOUD_RUN_TASK_TIMEOUT` | `3600` | worker, set by `deploy.sh` | Lets the worker know its own task timeout |
| `WORKER_TIME_BUDGET_SECONDS` | `0` | worker | Explicit budget per execution. `0` = task timeout minus 600s (3000s) |
| `MAX_JOB_CONTINUATIONS` | `12` | worker | Hand-overs allowed per job before it fails with `max_continuations_reached` |
| `PROCESSING_REALTIME_FACTOR` | `0.35` | API + worker | Estimated processing seconds per media second; only drives `[Quota] WARNING` log lines |

Useful queries:
```sql
-- Jobs currently spread over several executions
SELECT id, status, stage, continuation_count, retry_count, gpu_seconds_accumulated
FROM jobs WHERE continuation_count > 0 AND status IN ('pending', 'processing');

-- Timeouts and whether their automatic retry was used
SELECT id, failed_at, timeout_auto_retries, retry_count
FROM jobs WHERE status = 'failed' AND error_code = 'worker_timeout' ORDER BY failed_at DESC;

-- Checkpoints held for a video
SELECT stage, updated_at FROM pipeline_cache WHERE video_hash = '<hash>' ORDER BY stage;
```

Error codes introduced by this flow: `worker_timeout` (task timeout reached; one automatic retry, then manual) and `max_continuations_reached` (continuation cap hit; manual retry starts a new chain and still resumes from the checkpoints).

### Encryption key rotation

Users' saved LLM API keys (`user_api_keys.encrypted_key`) are encrypted with AES-256-GCM. The key is a 32-byte value stored as 64 hex characters in the Supabase Vault secret `api_key_encryption`, read through the `get_vault_secret` RPC and cached in memory per process (`backend/services/encryption.py`). It is not in Secret Manager, on disk, or in any env var.

Rotate it whenever the key may have been exposed. Run everything from your own terminal; steps 2 and 4 run in the Supabase SQL editor.

1. Generate the new key and keep it in your shell only:
   ```bash
   export NEW_ENCRYPTION_KEY_HEX="$(openssl rand -hex 32)"
   ```
2. Read the current key from Vault and export it as `OLD_ENCRYPTION_KEY_HEX`:
   ```sql
   SELECT decrypted_secret FROM vault.decrypted_secrets WHERE name = 'api_key_encryption';
   ```
3. Dry run. It writes nothing and must report `undecryptable 0`:
   ```bash
   cd backend && source venv/bin/activate
   python scripts/rotate_encryption_key.py
   ```
   A row that decrypts with neither key was encrypted with some third key. Find out why before continuing; the script will not touch it.
4. Store the new key in Vault:
   ```sql
   SELECT vault.update_secret(
     (SELECT id FROM vault.secrets WHERE name = 'api_key_encryption'),
     '<value of NEW_ENCRYPTION_KEY_HEX>'
   );
   ```
5. Re-encrypt the stored keys:
   ```bash
   python scripts/rotate_encryption_key.py --apply
   ```
6. Roll the API service so no instance keeps the old key cached (worker executions are short-lived and pick up the new key on their next start):
   ```bash
   gcloud run services update ai-subs-backend --region=us-central1 --project=ai-subs-poc \
     --update-env-vars="ENCRYPTION_KEY_ROTATED_AT=$(date -u +%Y%m%dT%H%M%SZ)"
   ```
7. Run the script again with `--apply`. An instance that still had the old key cached may have saved a key between steps 4 and 6; this catches it. Then run once more without `--apply` and confirm it reports `would rotate 0` and `undecryptable 0`.
8. `unset OLD_ENCRYPTION_KEY_HEX NEW_ENCRYPTION_KEY_HEX` and clear the SQL editor history that shows the old key.

Between steps 4 and 6, chat with a user's own key can fail for instances holding the other key. The window is as long as steps 5 and 6 take. The script is idempotent: a successful AES-GCM decrypt identifies which key a row is under, rows already on the new key are skipped, and each update is conditional on the ciphertext it read.

### Removing a leaked file from git history

`backend/local_data/encryption.key` was committed in `f789445` and removed from the tree later, but it stays readable in history until the history is rewritten. Rotate the key first (above); the rewrite only stops future readers.

```bash
brew install git-filter-repo
git clone --mirror git@github.com:Ugur22/ai-subtitles.git ai-subtitles-rewrite.git
cd ai-subtitles-rewrite.git
git filter-repo --invert-paths --path backend/local_data/encryption.key
git log --all --oneline -- backend/local_data/encryption.key   # must print nothing
git remote add origin git@github.com:Ugur22/ai-subtitles.git   # filter-repo removes the remote
git push origin --force --all
git push origin --force --tags
```

Merge or close open pull requests before the rewrite. Afterwards:

- Every commit hash changes. Anyone with a clone or fork must delete it and clone again. Pulling, merging or pushing an old clone puts the file back.
- GitHub keeps the old commits reachable through pull-request refs and cached views. Ask GitHub Support to remove cached views and dereference the old commits for the repository, and list the affected pull requests.
- Forks are not rewritten. They keep the file until their owners delete or rewrite them.
