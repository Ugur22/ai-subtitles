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
