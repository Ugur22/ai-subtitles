# Keyless deploys from GitHub Actions: a workflow job in the production
# environment of var.github_repository exchanges its OIDC token for the
# deployer SA. No JSON keys exist for any account here.

resource "google_iam_workload_identity_pool" "github" {
  workload_identity_pool_id = "github"
  display_name              = "GitHub Actions"
  description               = "OIDC tokens from GitHub Actions runs of ${var.github_repository}."

  depends_on = [google_project_service.required]
}

resource "google_iam_workload_identity_pool_provider" "github" {
  workload_identity_pool_id          = google_iam_workload_identity_pool.github.workload_identity_pool_id
  workload_identity_pool_provider_id = "github-actions"
  display_name                       = "GitHub Actions OIDC"

  attribute_mapping = {
    "google.subject"          = "assertion.sub"
    "attribute.repository"    = "assertion.repository"
    "attribute.repository_id" = "assertion.repository_id"
    "attribute.environment"   = "assertion.environment"
    "attribute.ref"           = "assertion.ref"
  }

  # Tokens from any other repository are rejected before any IAM check.
  attribute_condition = "assertion.repository == \"${var.github_repository}\""

  oidc {
    issuer_uri = "https://token.actions.githubusercontent.com"
  }
}

resource "google_service_account" "deployer" {
  account_id   = "ai-subs-deployer"
  display_name = "AI-Subs deployer (GitHub Actions, Cloud Build)"
  description  = "Builds images and deploys the Service and worker Job. Managed by infra/terraform."

  depends_on = [google_project_service.required]
}

# Only jobs that run in the GitHub environment (where approval can be required) get in.
resource "google_service_account_iam_member" "deployer_wif" {
  service_account_id = google_service_account.deployer.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "principalSet://iam.googleapis.com/${google_iam_workload_identity_pool.github.name}/attribute.environment/${var.github_environment}"
}

# Deploy the Service and the Job, on those two resources only. run.developer
# cannot change IAM policies, which is why deploy_image.sh omits --allow-unauthenticated.
resource "google_cloud_run_v2_service_iam_member" "deployer_service" {
  project  = var.project_id
  location = var.region
  name     = var.api_service_name
  role     = "roles/run.developer"
  member   = google_service_account.deployer.member
}

resource "google_cloud_run_v2_job_iam_member" "deployer_job" {
  project  = var.project_id
  location = var.region
  name     = var.worker_job_name
  role     = "roles/run.developer"
  member   = google_service_account.deployer.member
}

resource "google_secret_manager_secret_iam_member" "deployer_secret_metadata" {
  for_each  = setunion(var.api_secret_ids, var.worker_secret_ids)
  project   = var.project_id
  secret_id = each.value
  role      = "roles/secretmanager.viewer"
  member    = google_service_account.deployer.member
}

# Deploying a revision that runs as an SA requires actAs on it. The deployer acts as
# itself because Cloud Build runs the build as the deployer (--service-account).
resource "google_service_account_iam_member" "deployer_act_as" {
  for_each = {
    api      = google_service_account.api.name
    worker   = google_service_account.worker.name
    deployer = google_service_account.deployer.name
  }

  service_account_id = each.value
  role               = "roles/iam.serviceAccountUser"
  member             = google_service_account.deployer.member
}

resource "google_artifact_registry_repository_iam_member" "deployer_push" {
  project    = var.project_id
  location   = var.region
  repository = var.artifact_registry_repository
  role       = "roles/artifactregistry.writer"
  member     = google_service_account.deployer.member
}

# Cloud Build has no per-resource IAM; this lets the deployer submit and read builds.
resource "google_project_iam_member" "deployer_cloudbuild" {
  project = var.project_id
  role    = "roles/cloudbuild.builds.editor"
  member  = google_service_account.deployer.member
}

# Build source uploads and build logs. A dedicated bucket keeps the deployer away
# from the default <project>_cloudbuild bucket, which gcloud would otherwise try to create.
resource "google_storage_bucket" "build_staging" {
  name                        = "${var.project_id}-build-staging"
  location                    = var.region
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  # Only build tarballs and logs live here.
  force_destroy = true

  lifecycle_rule {
    condition {
      age = 7
    }
    action {
      type = "Delete"
    }
  }

  depends_on = [google_project_service.required]
}

resource "google_storage_bucket_iam_member" "deployer_staging" {
  for_each = toset([
    "roles/storage.objectAdmin",
    # storage.buckets.get, which gcloud builds submit checks before uploading.
    "roles/storage.legacyBucketReader",
  ])

  bucket = google_storage_bucket.build_staging.name
  role   = each.value
  member = google_service_account.deployer.member
}

# Lets the Claude Code agent's read-only account run `gcloud builds log`;
# the logs are GCS-only, so it can't see them otherwise.
resource "google_storage_bucket_iam_member" "agent_staging_reader" {
  bucket = google_storage_bucket.build_staging.name
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:agent-readonly@${var.project_id}.iam.gserviceaccount.com"
}
