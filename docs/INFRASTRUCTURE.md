# Infrastructure

How the GCP side of AI-Subs (project `ai-subs-poc`, region `us-central1`) is defined, applied and rolled back. Operational notes (Scheduler endpoints, GPU quota, key rotation) stay in [GCP_OPERATIONS.md](GCP_OPERATIONS.md).

Run every command here from your own terminal with Owner credentials. The Claude Code agent's gcloud account is read-only.

## What is managed where

Terraform is being introduced in three phases. Phase 1 (this one) creates only new resources. Existing resources are referenced by name through variables and get IAM bindings, but Terraform does not own them yet.

| Resource | Managed by | Notes |
|---|---|---|
| Runtime SAs `ai-subs-api`, `ai-subs-worker` and their IAM bindings | Terraform `infra/terraform/iam.tf` | Bindings sit on the bucket, secret or job, not the project |
| CI deployer `ai-subs-deployer`, Workload Identity pool `github`, bucket `gs://ai-subs-poc-build-staging` | Terraform `wif.tf` | Keyless GitHub Actions deploys |
| Email channel, `job_failed` metric, alerts, uptime check, billing budget | Terraform `monitoring.tf` | |
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

## Monitoring

All alerts go to one email channel (`alert_email`). Defined in `infra/terraform/monitoring.tf`.

| What | How | Alert |
|---|---|---|
| Failed jobs | Every job that ends as `failed` writes one stdout line `{"event":"job_failed","job_id","error_code","user_tier"}` (`JobQueueService._emit_job_failed`). That covers `mark_failed` (every Python-side error code), `worker_timeout`, `max_continuations_reached` and `finalization_retries_exhausted`. Log-based metric `logging.googleapis.com/user/job_failed`, labelled by `error_code` and `user_tier` | More than 2 in a rolling hour (PromQL, summed over the Service and the Job) |
| Crashes | Unhandled exceptions in the API (FastAPI exception handler), the worker (`sys.excepthook`, `threading.excepthook`) and failed pipeline runs are written to stderr as **one** JSON line with `severity: ERROR` and the full trace (`backend/utils/structured_log.py`). Cloud Run would otherwise split a trace into one entry per line, which Error Reporting cannot group. No SDK | Error Reporting notifications, set up in the Console (below) |
| API up | Uptime check `GET /` on the Service URL, expecting `"status":"healthy"`, every `uptime_check_period` (default 15 min; each probe can wake a scaled-to-zero instance) | Failing from more than one location |
| Spend | `google_billing_budget` on the project, `budget_amount` per calendar month | 50%, 90% and 100% of actual spend, to the channel and the billing admins |

Failed jobs in Logs Explorer: `jsonPayload.event="job_failed"`. Crashes: Error Reporting, or `severity=ERROR jsonPayload."@type":"type.googleapis.com/google.devtools.clouderrorreporting.v1beta1.ReportedErrorEvent"`.

### Error Reporting notifications (manual)

Terraform (google provider 8.9) has no resource for Error Reporting notification settings, so turn them on once in the Console:

1. Open [Error Reporting](https://console.cloud.google.com/errors?project=ai-subs-poc) and choose **Configure notifications**.
2. Select the email channel Terraform created, "AI-Subs alerts (…)", and save.
3. New error groups are then emailed when they first occur. Recurring groups are not emailed again until they are resolved and reappear.

The budget needs the Billing Budgets API (enabled by `apis.tf`). The account running `terraform apply` needs **Billing Account Administrator** or **Billing Account Costs Manager** on the billing account; project Owner alone is not enough.

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

## Deploys from GitHub Actions

`.github/workflows/deploy.yml` runs on a pushed `v*` tag, or by hand (Actions → deploy → Run workflow) on `main`.

1. The `check` job reuses `check.yml`: lint, pytest, tsc, `terraform fmt` and `validate`.
2. The `deploy` job runs in the GitHub environment `production`, so required reviewers there must approve it first. It gets a GitHub OIDC token and exchanges it through Workload Identity Federation for `ai-subs-deployer`. There are no JSON keys.
3. It runs `infra/scripts/deploy_image.sh --yes`: migration check, Cloud Build, then both deploys with the same SHA tag.

Only the pool provider's `attribute_condition` (repository `Ugur22/ai-subtitles`) and the binding on `attribute.environment/production` let a token in. A job outside that environment, or a fork, cannot impersonate the deployer.

What the deployer can do:

| Grant | Scope | Why |
|---|---|---|
| `roles/run.developer` | Service `ai-subs-backend`, Job `ai-subs-worker` | Deploy new revisions; it cannot change IAM policies, so deploys omit `--allow-unauthenticated` |
| `roles/iam.serviceAccountUser` | `ai-subs-api`, `ai-subs-worker`, itself | Deploy revisions running as those SAs; Cloud Build runs as the deployer |
| `roles/artifactregistry.writer` | Repository `ai-subs-repo` | Push images, check tags |
| `roles/cloudbuild.builds.editor` | Project (Cloud Build has no per-resource IAM) | Submit and follow builds |
| `roles/storage.objectAdmin` + `legacyBucketReader` | `gs://ai-subs-poc-build-staging` | Source upload and build logs |

Repository variables (Settings → Secrets and variables → Actions → Variables): `GCP_WIF_PROVIDER` and `GCP_DEPLOYER_SA` from `terraform output`, and `SUPABASE_ANON_KEY` (the public anon key the frontend already ships; not a secret).

## Database migrations

Deploys never apply migrations. Apply them by hand in the Supabase SQL editor, before deploying the code that needs them.

`public.schema_migrations` (migration 023) records what is applied. `infra/scripts/check_migrations.sh` runs before every build (locally and in CI). It reads the table with the anon key, which RLS limits to `SELECT`, and fails with the file names when any non-rollback file in `backend/sql/migrations` is missing from it. A rollback (`rollback.sh`) skips the check. `--skip-migration-check` exists for emergencies.

Every migration after 023 ends with its own row, inside its transaction, and has a `_rollback.sql` (enforced by `backend/tests/test_schema_migrations.py`):

```sql
INSERT INTO public.schema_migrations (version) VALUES ('024') ON CONFLICT (version) DO NOTHING;
COMMIT;
```

Its rollback deletes that row: `DELETE FROM public.schema_migrations WHERE version = '024';`.

## Rolling back Terraform

- **A bad Terraform change:** revert the commit and apply again. Bindings and SAs that phase 1 creates can be removed by an apply without affecting existing resources, except that the Service and Job would lose their runtime permissions. Roll the Service back first (`--service-account` of the previous revision) when removing SAs.
- **Corrupted state:** the state bucket is versioned. List versions with `gcloud storage ls -a gs://ai-subs-poc-tfstate/terraform/state/`, then copy a previous generation over `default.tfstate` (`gcloud storage cp gs://…/default.tfstate#<generation> gs://…/default.tfstate`). Run `terraform plan` to confirm the state matches reality.

## Still manual

- The GitHub environment `production` (required reviewers, deployment branches and tags) and the three repository variables.
- Applying SQL migrations, including 023.
- The `allUsers` invoker binding on the Service. It exists today; deploys no longer re-assert it, so a recreated Service needs it again (`gcloud run services add-iam-policy-binding ai-subs-backend --member=allUsers --role=roles/run.invoker`).
- Tag immutability on `ai-subs-repo` (an Artifact Registry repository setting; it belongs to the phase that imports the repository).
- Error Reporting notification settings (see Monitoring above).
- Removing `roles/editor` from the default compute SA `1052285886390-compute@developer.gserviceaccount.com`, once the new SAs are verified in production.
