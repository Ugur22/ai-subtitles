---
paths:
  - "infra/**"
  - "backend/Dockerfile"
  - "backend/cloudbuild.yaml"
  - "backend/deploy.sh"
  - "backend/update-secrets.sh"
  - "backend/download_models.py"
  - "backend/gcs-cors.json"
  - "backend/gcs-lifecycle.json"
  - "backend/tests/test_infra_contract.py"
  - "backend/tests/test_deployment_contract.py"
  - "frontend/netlify.toml"
  - ".github/workflows/deploy.yml"
---

# Infrastructure rules

`infra/` is Sensitive (`tools/harness/risk.py`) and `.github/` is a guard path. What is managed where: `docs/INFRASTRUCTURE.md`; Scheduler jobs, GCS layout, GPU quota and LLM provider notes: `docs/GCP_OPERATIONS.md`.

## Layout
- **GCP project** `ai-subs-poc`, region `us-central1`.
- **Cloud Run**: CPU Service `ai-subs-backend` (HTTP only, no GPU) plus a separate GPU worker Job `ai-subs-worker` (nvidia-l4, 1h task timeout), both built and deployed by `infra/scripts/deploy_image.sh` (run by `backend/deploy.sh`, `infra/scripts/rollback.sh` and `.github/workflows/deploy.yml`). That script is the source of truth for resources, secrets and env vars. Keep heavy work out of the Service: it belongs in the worker Job.
- **Terraform** (`infra/terraform`): runtime service accounts and IAM bindings, the CI deployer and Workload Identity Federation, monitoring, project APIs. Bucket `ai-subs-uploads`, Artifact Registry, Secret Manager secrets and Scheduler jobs are still manual.
- **Artifact Registry**: the repo is `ai-subs-repo` (NOT `ai-subs`). Images are tagged with the 12-character git SHA; the Service and the worker Job always run the same image.
- **Frontend**: Netlify, deployed on push to `main`; `/api/*` is proxied to Cloud Run (`frontend/netlify.toml`).

## Secrets and IAM
- Secret values are added by hand (`gcloud secrets versions add`) and never go in Terraform, tfvars, state, the repo or logs.
- IAM bindings sit on the bucket, secret or job, not the project. Secrets and IAM changes are the user's.

## Production authority
`terraform apply`/`destroy`, deploys, tags, secrets and IAM are the user's alone ("Irreversible or production", Releases and Deployment in `CLAUDE.md`): prepare the files and the exact commands, then stop. The release path is `.github/workflows/deploy.yml` on a `v*` tag, with the `deploy` job approved in the `production` environment.

## Rollback
- `infra/scripts/rollback.sh <sha-tag>` points the Service and the worker Job back at an earlier image. It rolls back code only: env vars, secrets and resources come from the current `deploy_image.sh`, and the database is not touched. An image older than a migration that changed existing functions may fail against the current schema.
- Rolling back Terraform: "Rolling back Terraform" in `docs/INFRASTRUCTURE.md`.

## Verification
- `backend/tests/test_infra_contract.py` and `test_deployment_contract.py` pin the deploy script and Terraform contracts; CI's `check` job also runs `terraform fmt` and `validate`.
