# Terraform phases: handoff

State of bringing the GCP infrastructure (project `ai-subs-poc`, region `us-central1`) under Terraform, written 2026-11-16 at the end of Phase 1. Start a new session here. How things work today is in [INFRASTRUCTURE.md](INFRASTRUCTURE.md); this page covers what is done, what is left and what to watch.

## Where things stand

| Phase | Scope | Status |
|---|---|---|
| 1 | Create only **new** resources: least-privilege SAs, monitoring, budget, Workload Identity + CI deployer, immutable image tags, migration gate | **Done** (PR #26, released as `v0.1.0`) |
| 2 | Import existing bucket, Artifact Registry repo, secret containers, Scheduler jobs | Not started |
| 3 | Import the Cloud Run Service and worker Job | Not started |

### Phase 1 as live in production

- **Terraform** in `infra/terraform`, google provider `8.9.0`, Terraform `>= 1.5` (CI uses 1.17.1). State in `gs://ai-subs-poc-tfstate` (prefix `terraform/state`, versioned, created by `infra/bootstrap_state_bucket.sh`). 53 resources; `terraform plan` shows no changes.
- **Runtime SAs:** the Service runs as `ai-subs-api@`, the worker Job as `ai-subs-worker@`. Grants sit on the bucket, the job and each secret (`iam.tf`). Verified end to end on 2026-11-16 with an upload, a full job, chat, video playback, screenshots and both Scheduler jobs. **`roles/editor` was removed from the default compute SA** `1052285886390-compute@developer.gserviceaccount.com`.
- **CI deploys:** `.github/workflows/deploy.yml` on a `v*` tag runs the checks, then the `deploy` job in the GitHub environment `production` (required reviewer `Ugur22`; branch `main`, tag `v*`). It authenticates through Workload Identity (`projects/1052285886390/locations/global/workloadIdentityPools/github/providers/github-actions`) as `ai-subs-deployer@`; no JSON keys. Repository variables: `GCP_WIF_PROVIDER`, `GCP_DEPLOYER_SA`, `SUPABASE_ANON_KEY` (the publishable key).
- **Images:** tagged with the 12-char git SHA; `infra/scripts/deploy_image.sh` is the single definition of the Service and Job. Running now: `cb5527672057`. Rollback: `infra/scripts/rollback.sh <tag>` (`--list` shows tags; `sha256:<digest>` reaches the pre-Phase-1 `:latest` image).
- **Monitoring:** email channel to `ugurertas9@gmail.com`; log metric `job_failed` with an alert at more than 2 per hour (PromQL over both resource types); uptime check on `GET /` every 15 min; billing budget €10/month at 50/90/100%. The old manual €5 budget was deleted.
- **Migrations:** `public.schema_migrations` (migration 023, applied 2026-11-16) gates every deploy through `infra/scripts/check_migrations.sh`. Each new migration must insert its own row and ship a `_rollback.sql` (enforced by `backend/tests/test_schema_migrations.py`).
- **Release flow:** merge to `main` → apply new migrations (with approval) → push a `v*` tag → approve in Actions. `backend/deploy.sh` is emergency-only. Frontend-only changes deploy through Netlify on push to `main`.

### Loose ends from Phase 1

- [ ] Error Reporting notifications: Console → Error Reporting → Configure notifications → "AI-Subs alerts (ugurertas9@gmail.com)". Terraform has no resource for this. Confirm whether it was done.
- [ ] Merge the PR for branch `docs/deploy-via-actions` (CLAUDE.md release flow and this page).
- [ ] The GitHub environment `wholesome-transformation / production` belongs to another integration. Check that the reviewer and `main`/`v*` rules added to it by mistake were removed.
- [ ] `frontend/.env` holds a `REPLACE_ME` placeholder for `VITE_SUPABASE_ANON_KEY`, so a local emergency deploy needs `export SUPABASE_ANON_KEY=…` first.

## Phase 2: import existing supporting resources

**Goal:** Terraform owns the resources that Phase 1 only references by name, without changing any of them.

| Resource | Import ID (verify before use) | Notes |
|---|---|---|
| Bucket `ai-subs-uploads` | `ai-subs-uploads` | CORS (`backend/gcs-cors.json`) and lifecycle (`backend/gcs-lifecycle.json`) must be modelled exactly. Retention rules are in the memory note on GCS retention; a lifecycle change can delete user media |
| Artifact Registry `ai-subs-repo` | `projects/ai-subs-poc/locations/us-central1/repositories/ai-subs-repo` | After a clean import, turn on tag immutability as a separate, reviewed change. Add a cleanup policy for old SHA tags |
| Secret containers (the 10 in `api_secret_ids`; the worker uses a subset) | `projects/ai-subs-poc/secrets/<name>` | `google_secret_manager_secret` only. **Never** `google_secret_manager_secret_version`: values must not reach state |
| Scheduler jobs `check-stale`, `refresh-screenshot-urls` | `projects/ai-subs-poc/locations/us-central1/jobs/<name>` | Their `X-Internal-Key` header would land in state. Decide first: move them to OIDC auth (a Scheduler SA with `run.invoker`, plus backend support for verifying the token) or keep them out of Terraform |

Steps:
1. Describe each resource read-only and write its Terraform block to match exactly. The agent's gcloud account cannot read IAM policies, secrets or Scheduler jobs, so the user may need to paste `describe` output.
2. Add `import {}` blocks, one resource type at a time. `terraform plan` must show only `import` with **0 to add, 0 to change, 0 to destroy**. Fix the block until it does; never apply a plan that changes an imported resource in the same step.
3. Switch `var.uploads_bucket_name`, `var.artifact_registry_repository` and the `*_secret_ids` bindings in `iam.tf` / `wif.tf` to resource references. That plan must also show no changes.
4. Add `lifecycle { prevent_destroy = true }` to the bucket, the repo and the secrets.
5. Only then make real changes (tag immutability, AR cleanup policy), each as its own reviewed plan.

## Phase 3: import the Cloud Run Service and Job

**Goal:** Terraform owns the resources, env vars and secret mounts of `ai-subs-backend` and `ai-subs-worker`. CI only changes the image.

Steps:
1. Model both as `google_cloud_run_v2_service` / `google_cloud_run_v2_job` from `infra/scripts/deploy_image.sh` (the current source of truth) and from `gcloud run services describe` / `gcloud run jobs describe` output. Watch for settings gcloud sets implicitly (CPU boost, `--no-gpu-zonal-redundancy`, the GPU node selector, `--gpu=0` on the Service, execution environment, annotations).
2. `lifecycle { ignore_changes = [template[0].containers[0].image] }` on both (exact path per resource), plus the client/annotation fields gcloud writes, so CI deploys and Terraform don't fight.
3. Import; the plan must show no changes.
4. Move the `allUsers` invoker binding (`google_cloud_run_v2_service_iam_member`) into Terraform. Its absence is why deploys omit `--allow-unauthenticated`.
5. Reduce `deploy_image.sh` to building and updating the image (`gcloud run services update --image`, `gcloud run jobs update --image`). Remove resource and env flags from it, and update `backend/tests/test_deployment_contract.py` and `test_infra_contract.py`, which assert on those flags today.
6. Env var and secret changes then go through Terraform PRs. Update `docs/INFRASTRUCTURE.md`, `docs/GCP_OPERATIONS.md` and `backend/DEPLOYMENT.md` ("Changing configuration without a rebuild").

**Risk:** this phase touches the live Service and Job. Do it when a short outage is acceptable; make sure `rollback.sh` works first; re-run the Phase 1 test matrix (upload, job + continuation, chat, playback, screenshots, both Scheduler jobs) after every apply.

## Rules for the next session

- Follow `CLAUDE.md`: plan mode first, written plan, explicit approval. Never `terraform apply`/`destroy`, never deploy, push, tag or approve; the user runs those. Ask before any Supabase migration (with a rollback file).
- The agent sandbox **cannot run `terraform validate` or `plan`**: the provider plugin needs a local unix socket, which the sandbox blocks. Also, `terraform init` cannot reach the registry (TLS); providers can be fetched with `curl` into a local mirror under the scratchpad. `terraform fmt` works. `validate` runs in CI (`check.yml`, job `terraform`); `plan` and `apply` run in the user's terminal from `infra/terraform` with `terraform.tfvars` present (gitignored; holds `alert_email`, `billing_account_id`, `budget_amount = 10`, `budget_currency_code = "EUR"`).
- Read-only gcloud in the sandbox: `CLOUDSDK_CONFIG=~/.config/gcloud-agent`. It can describe Cloud Run, Artifact Registry and logs, but not IAM policies, secrets, Scheduler, Monitoring or billing.
- Every plan the user runs should be checked with:
  ```bash
  terraform show -no-color tfplan | grep -E '^Plan:|will be (updated|destroyed|replaced)|must be replaced'
  ```

## Prompt for the new session

> Read CLAUDE.md and docs/TERRAFORM_PHASES_HANDOFF.md. Start Phase 2 of the Terraform migration: import the existing bucket, Artifact Registry repository and secret containers without changing them, and propose how to handle the Scheduler jobs' X-Internal-Key. Enter plan mode first; don't apply or deploy anything.
