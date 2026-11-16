output "api_service_account" {
  description = "Runtime SA for the API Service; used by infra/scripts/deploy_image.sh."
  value       = google_service_account.api.email
}

output "worker_service_account" {
  description = "Runtime SA for the worker Job; used by infra/scripts/deploy_image.sh."
  value       = google_service_account.worker.email
}
