# Runtime identities for the API Service and the GPU worker Job, replacing the
# default compute SA (which holds project Editor). Grants follow the API audit in
# docs/INFRASTRUCTURE.md and sit on the bucket, secret or job, never the project.

locals {
  runtime_accounts = {
    api    = google_service_account.api
    worker = google_service_account.worker
  }

  api_secret_bindings    = { for s in var.api_secret_ids : "api/${s}" => { secret = s, member = google_service_account.api.member } }
  worker_secret_bindings = { for s in var.worker_secret_ids : "worker/${s}" => { secret = s, member = google_service_account.worker.member } }
}

resource "google_service_account" "api" {
  account_id   = "ai-subs-api"
  display_name = "AI-Subs API (Cloud Run Service)"
  description  = "Runtime identity of the ai-subs-backend Service. Managed by infra/terraform."

  depends_on = [google_project_service.required]
}

resource "google_service_account" "worker" {
  account_id   = "ai-subs-worker"
  display_name = "AI-Subs worker (Cloud Run Job)"
  description  = "Runtime identity of the ai-subs-worker GPU Job. Managed by infra/terraform."

  depends_on = [google_project_service.required]
}

# Both read, write, copy and delete media objects (uploads, processed media,
# screenshots, the media-deletion outbox drain). objectUser has no IAM or bucket-config rights.
resource "google_storage_bucket_iam_member" "runtime_objects" {
  for_each = local.runtime_accounts

  bucket = var.uploads_bucket_name
  role   = "roles/storage.objectUser"
  member = each.value.member
}

# V4 signed URLs are signed through IAM signBlob as the runtime SA itself
# (services/gcs_service.py); the worker signs screenshot URLs while indexing.
resource "google_service_account_iam_member" "runtime_self_sign" {
  for_each = local.runtime_accounts

  service_account_id = each.value.name
  role               = "roles/iam.serviceAccountTokenCreator"
  member             = each.value.member
}

# The API dispatches jobs and the worker dispatches its own continuations, both
# with per-execution args overrides (services/job_dispatcher.py).
resource "google_cloud_run_v2_job_iam_member" "runtime_run_worker" {
  for_each = local.runtime_accounts

  project  = var.project_id
  location = var.region
  name     = var.worker_job_name
  role     = "roles/run.jobsExecutorWithOverrides"
  member   = each.value.member
}

resource "google_secret_manager_secret_iam_member" "runtime_secrets" {
  for_each = merge(local.api_secret_bindings, local.worker_secret_bindings)

  project   = var.project_id
  secret_id = each.value.secret
  role      = "roles/secretmanager.secretAccessor"
  member    = each.value.member
}
