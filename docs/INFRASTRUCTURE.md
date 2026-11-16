# Infrastructure

How the GCP side of AI-Subs (project `ai-subs-poc`, region `us-central1`) is defined, applied and rolled back. Operational notes (Scheduler endpoints, GPU quota, key rotation) stay in [GCP_OPERATIONS.md](GCP_OPERATIONS.md).

Run every command here from your own terminal with Owner credentials. The Claude Code agent's gcloud account is read-only.

## What is managed where

Terraform is being introduced in three phases. Phase 1 (this one) creates only new resources. Existing resources are referenced by name through variables and get IAM bindings, but Terraform does not own them yet.

| Resource | Managed by | Notes |
|---|---|---|
| Runtime SAs `ai-subs-api`, `ai-subs-worker` and their IAM bindings | Terraform `infra/terraform/iam.tf` | Bindings sit on the bucket, secret or job, not the project |
| Project APIs used below | Terraform `apis.tf` | `disable_on_destroy = false`, so a destroy never switches an API off |
| Terraform state bucket `gs://ai-subs-poc-tfstate` | `infra/bootstrap_state_bucket.sh` | Versioned; Terraform cannot create its own backend |
| Cloud Run Service `ai-subs-backend`, worker Job `ai-subs-worker` | `infra/scripts/deploy_image.sh` | Resources, env vars, secret mounts and the image. Run by `backend/deploy.sh`, `infra/scripts/rollback.sh` and `.github/workflows/deploy.yml`. Terraform import in a later phase |
| Bucket `ai-subs-uploads`, Artifact Registry `ai-subs-repo`, Secret Manager secrets, Scheduler jobs | Manual (Console / gcloud) | Terraform import in a later phase |
| Secret **values** | Manual (`gcloud secrets versions add`) | Never in Terraform, tfvars or state |

## GCP API audit

What the code calls, and the narrowest grant that allows it. Supabase, Stripe, Flagsmith and the LLM providers are reached over the internet with keys from Secret Manager and need no GCP permission.

| Call | Code | Permission | API Service | Worker Job | Grant (Terraform) |
|---|---|---|---|---|---|
| Upload, download, exists, metadata, copy, delete and list objects | `services/gcs_service.py`, `services/media_storage.py`; both drain the media-deletion outbox | `storage.objects.*` | ✓ | ✓ | `roles/storage.objectUser` on bucket `ai-subs-uploads` |
| V4 signed URLs (upload, resumable upload, download) | `gcs_service.generate_*_signed_url`; the worker signs screenshot URLs while indexing (`services/image_embedding_service.py`) | `iam.serviceAccounts.signBlob` | ✓ | ✓ | `roles/iam.serviceAccountTokenCreator` on the SA itself |
| Start a worker execution with per-job args | `services/job_dispatcher.py` `CloudRunJobDispatcher`; the API dispatches jobs, the worker dispatches its own continuations (`background_worker._hand_over_to_continuation`) | `run.jobs.runWithOverrides` | ✓ | ✓ | `roles/run.jobsExecutorWithOverrides` on job `ai-subs-worker` |
| Secrets mounted as env vars | `--set-secrets` in the deploy script | `secretmanager.versions.access` | 10 secrets | 4 secrets | `roles/secretmanager.secretAccessor` per secret |
| Logs on stdout/stderr | Cloud Run log agent | none | | | none |

`backend/tests/test_infra_contract.py` fails when a secret mounted by `deploy_image.sh` has no matching accessor binding in `variables.tf`.

## Applying Terraform

One-time setup:

```bash
infra/bootstrap_state_bucket.sh --dry-run   # review
infra/bootstrap_state_bucket.sh
cd infra/terraform
cp terraform.tfvars.example terraform.tfvars  # fill in; gitignored
terraform init
```

Every change:

```bash
cd infra/terraform
terraform plan -out=tfplan
terraform apply tfplan
```

Phase 1 must never show `~ update`, `- destroy` or `-/+ replace` in a plan. If one appears, Terraform is about to touch something it does not own yet. Stop and investigate.

`.terraform.lock.hcl` is committed. After a provider version bump, refresh it for both the Mac and the CI runner:

```bash
terraform providers lock -platform=darwin_arm64 -platform=linux_amd64
```

CI (`.github/workflows/check.yml`, job `terraform`) runs `terraform fmt -check`, `init -backend=false` and `validate` on every push and pull request.

## Images, deploys and rollback

Every image is tagged with the 12-character git SHA of the commit it was built from (`…/ai-subs-backend:0123456789ab`). `:latest` is no longer written or deployed.

- `deploy_image.sh` refuses a working tree with uncommitted or untracked changes. `--allow-dirty` builds them as `<sha>-dirty`, a tag the next dirty build of the same commit overwrites.
- A clean tag that already exists is not rebuilt, so re-running a deploy for the same commit only redeploys.
- The Service and the worker Job are always deployed with the same image. The script compares both after deploying, fails if they differ, and prints the deployed tag last.
- Builds run on Cloud Build as `ai-subs-deployer`, with source and logs in `gs://ai-subs-poc-build-staging` (deleted after 7 days). The layer cache comes from the image the Service runs now.

List recent tags and what runs now:

```bash
infra/scripts/rollback.sh --list
```

Roll back the code to an earlier image (no rebuild, no migration check):

```bash
infra/scripts/rollback.sh 0123456789ab
# Images from before SHA tags (the old :latest) only have a digest:
infra/scripts/rollback.sh sha256:<digest>
```

Rollback changes the image only. Env vars, secrets and resources come from the current `deploy_image.sh`, and the database is not rolled back. An image older than a migration that changed existing functions may fail against the current schema.

## Rolling back Terraform

- **A bad Terraform change:** revert the commit and apply again. Bindings and SAs that phase 1 creates can be removed by an apply without affecting existing resources, except that the Service and Job would lose their runtime permissions. Roll the Service back first (`--service-account` of the previous revision) when removing SAs.
- **Corrupted state:** the state bucket is versioned. List versions with `gcloud storage ls -a gs://ai-subs-poc-tfstate/terraform/state/`, then copy a previous generation over `default.tfstate` (`gcloud storage cp gs://…/default.tfstate#<generation> gs://…/default.tfstate`). Run `terraform plan` to confirm the state matches reality.

## Still manual

- Removing `roles/editor` from the default compute SA `1052285886390-compute@developer.gserviceaccount.com`, once the new SAs are verified in production.
