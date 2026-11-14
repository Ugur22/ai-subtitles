# AI-Subs Backend - Cloud Run Deployment Guide

The backend is deployed as two Cloud Run resources built from one image:

| Resource | Kind | Hardware | Runs |
|----------|------|----------|------|
| `ai-subs-backend` | Cloud Run **Service** | CPU only | FastAPI: auth, uploads, job API, search, chat |
| `ai-subs-worker` | Cloud Run **Job** | 1x NVIDIA L4 | `python -m worker_main <job_id>`: one execution per transcription job |

`backend/deploy.sh` is the only definition of both. Memory, CPU, timeouts, env vars and secrets are set there; read the script for current values instead of trusting a copy in a document. There is no Cloud Run YAML on purpose: the old `cloudrun-service.yaml` described a single GPU service and had drifted, and deploying a stale YAML with `gcloud run services replace` drops env vars and secrets.

Architecture and job flow: [docs/ARCHITECTURE.md](../docs/ARCHITECTURE.md). Scheduler jobs, GCS, quotas and key rotation: [docs/GCP_OPERATIONS.md](../docs/GCP_OPERATIONS.md).

## Prerequisites

- `gcloud` installed and authenticated with Owner credentials on project `ai-subs-poc` (region `us-central1`)
- Cloud Run, Cloud Build, Secret Manager, Artifact Registry and Cloud Scheduler APIs enabled
- Artifact Registry repository `ai-subs-repo`

Run deploys from your own terminal, not from a Claude Code session: the agent's shell uses a read-only service account.

## Deploying

```bash
cd backend
./deploy.sh               # Cloud Build, then deploy the Service and the worker Job
./deploy.sh --skip-build  # redeploy both from the existing image
```

The script asks for confirmation, builds with `cloudbuild.yaml`, deploys the Service without a GPU, deploys the worker Job with the GPU, and checks the Service's health endpoint.

Apply pending SQL migrations in `backend/sql/migrations/` to Supabase **before** deploying code that needs them. The worker and the API call the SQL functions directly; deploying first makes job claims, retries and continuations fail.

## What the worker Job needs

- `--task-timeout=3600`. One hour is the maximum Cloud Run allows for a GPU task. Longer files are handled by continuations, not by a longer timeout.
- `--max-retries=0`. Retries are driven by the job table and `check-stale`, not by Cloud Run.
- `CLOUD_RUN_TASK_TIMEOUT`, set by `deploy.sh` to the task timeout. Cloud Run does not expose the timeout to the container; the worker uses it to stop about 10 minutes early and continue in a new execution.
- `WORKER_JOB_PROJECT`, `WORKER_JOB_REGION`, `WORKER_JOB_NAME`, on both the Service and the Job. The Service dispatches executions; the worker dispatches its own continuation.
- A service account that can run the Job with overrides (`run.jobs.runWithOverrides`) and read/write the bucket. Both resources currently use the default compute service account.

## Secrets

Secrets come from Secret Manager and are mapped in `deploy.sh` (`--set-secrets`). The Service and the Job get different sets; the Job only gets what the pipeline uses.

```bash
# Add a new version; the next revision or execution picks up :latest
echo -n "NEW_VALUE" | gcloud secrets versions add SECRET_NAME --data-file=- --project=ai-subs-poc
```

The key that encrypts users' saved LLM API keys is not in Secret Manager. It lives in Supabase Vault; see "Encryption key rotation" in `docs/GCP_OPERATIONS.md`.

## Changing configuration without a rebuild

```bash
# API service
gcloud run services update ai-subs-backend --region=us-central1 --project=ai-subs-poc \
  --update-env-vars="VAR=value"

# Worker job (applies to executions started afterwards)
gcloud run jobs update ai-subs-worker --region=us-central1 --project=ai-subs-poc \
  --update-env-vars="VAR=value"
```

Put lasting changes in `deploy.sh` as well, or the next deploy reverts them.

## Logs and status

```bash
# API service
gcloud run services logs read ai-subs-backend --region=us-central1 --project=ai-subs-poc --limit=50

# Worker executions (one per job, plus one per continuation)
gcloud run jobs executions list --job=ai-subs-worker --region=us-central1 --project=ai-subs-poc
gcloud logging read 'resource.type="cloud_run_job" AND resource.labels.job_name="ai-subs-worker"' \
  --project=ai-subs-poc --limit=50 --freshness=1h
```

Worker log lines are prefixed `[worker_main]`, `[Worker]`, `[JobQueue]` and `[PipelineCache]`.

## Troubleshooting

| Symptom | Where to look |
|---------|---------------|
| Job stays `pending` | The execution did not start. Check `executions list`, GPU quota, and the Service log for `Cloud Run rejected worker dispatch`. `check-stale` re-dispatches pending jobs after 10 minutes. |
| Job fails with `gpu_unavailable` | CUDA was not usable in the execution; the worker refuses to fall back to CPU. |
| Job fails with `worker_timeout` | The execution hit the task timeout in a stage that is not checkpointed. It is retried once automatically from the chunk cache; after that the user retries from the UI. |
| Job fails with `max_continuations_reached` | The file needed more than `MAX_JOB_CONTINUATIONS` executions. Check per-chunk timings in the worker log. |
| `Could not find the function ... in the schema cache` | A migration has not been applied to Supabase. |
| Secret access denied | The service account lacks `roles/secretmanager.secretAccessor` on that secret. |
| CORS errors | `CORS_ORIGINS` on the Service does not match the frontend origin exactly. |
