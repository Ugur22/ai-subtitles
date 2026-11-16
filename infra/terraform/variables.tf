variable "project_id" {
  description = "GCP project that hosts AI-Subs."
  type        = string
  default     = "ai-subs-poc"
}

variable "region" {
  description = "Region of the Cloud Run Service, worker Job and Artifact Registry repo."
  type        = string
  default     = "us-central1"
}

# Existing resources referenced by name until a later phase imports them.

variable "uploads_bucket_name" {
  description = "Existing media bucket (not managed here yet)."
  type        = string
  default     = "ai-subs-uploads"
}

variable "worker_job_name" {
  description = "Existing Cloud Run worker Job (not managed here yet)."
  type        = string
  default     = "ai-subs-worker"
}

# Must match the --set-secrets lists in infra/scripts/deploy_image.sh; backend/tests/test_infra_contract.py checks this.
variable "api_secret_ids" {
  description = "Secret Manager secrets mounted into the API Service."
  type        = set(string)
  default = [
    "app-password-hash",
    "flagsmith-server-key",
    "groq-api-key",
    "huggingface-token",
    "internal-api-key",
    "stripe-pro-price-id",
    "stripe-secret-key",
    "stripe-webhook-secret",
    "supabase-service-key",
    "xai-api-key",
  ]
}

variable "worker_secret_ids" {
  description = "Secret Manager secrets mounted into the worker Job."
  type        = set(string)
  default = [
    "groq-api-key",
    "huggingface-token",
    "supabase-service-key",
    "xai-api-key",
  ]
}
