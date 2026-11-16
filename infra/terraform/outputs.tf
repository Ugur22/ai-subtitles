output "api_service_account" {
  description = "Runtime SA for the API Service; used by infra/scripts/deploy_image.sh."
  value       = google_service_account.api.email
}

output "worker_service_account" {
  description = "Runtime SA for the worker Job; used by infra/scripts/deploy_image.sh."
  value       = google_service_account.worker.email
}

output "job_failed_metric" {
  description = "Log-based metric counting failed jobs."
  value       = "logging.googleapis.com/user/${google_logging_metric.job_failed.name}"
}

output "deployer_service_account" {
  description = "Set as the GitHub repository variable GCP_DEPLOYER_SA."
  value       = google_service_account.deployer.email
}

output "workload_identity_provider" {
  description = "Set as the GitHub repository variable GCP_WIF_PROVIDER."
  value       = google_iam_workload_identity_pool_provider.github.name
}

output "build_staging_bucket" {
  description = "Cloud Build source and logs; must match BUILD_STAGING_BUCKET in infra/scripts/deploy_image.sh."
  value       = "gs://${google_storage_bucket.build_staging.name}"
}
