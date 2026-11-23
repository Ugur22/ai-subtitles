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
  ]
}

variable "worker_secret_ids" {
  description = "Secret Manager secrets mounted into the worker Job."
  type        = set(string)
  default = [
    "groq-api-key",
    "huggingface-token",
    "supabase-service-key",
  ]
}

# Monitoring and budget (monitoring.tf)

variable "alert_email" {
  description = "Address that receives job-failure, uptime and budget alerts."
  type        = string
}

variable "billing_account_id" {
  description = "Billing account paying for the project, as XXXXXX-XXXXXX-XXXXXX."
  type        = string

  validation {
    condition     = can(regex("^[0-9A-F]{6}-[0-9A-F]{6}-[0-9A-F]{6}$", var.billing_account_id))
    error_message = "billing_account_id must look like 012345-6789AB-CDEF01."
  }
}

variable "budget_amount" {
  description = "Monthly budget in whole units of the billing account's currency."
  type        = number

  validation {
    condition     = var.budget_amount > 0 && floor(var.budget_amount) == var.budget_amount
    error_message = "budget_amount must be a positive whole number."
  }
}

variable "budget_currency_code" {
  description = "ISO 4217 code; leave null to use the billing account's currency (a mismatch is rejected by the API)."
  type        = string
  default     = null
}

variable "api_uptime_host" {
  description = "Host of the API Service that the uptime check calls at GET /."
  type        = string
  default     = "ai-subs-backend-qtpkqndqoq-uc.a.run.app"
}

variable "uptime_check_period" {
  description = "How often each uptime location probes the API; one of 60s, 300s, 600s, 900s."
  type        = string
  default     = "900s"

  validation {
    condition     = contains(["60s", "300s", "600s", "900s"], var.uptime_check_period)
    error_message = "uptime_check_period must be 60s, 300s, 600s or 900s."
  }
}

# CI deploys (wif.tf)

variable "github_repository" {
  description = "Only GitHub Actions runs from this owner/repo can get tokens."
  type        = string
  default     = "Ugur22/ai-subtitles"
}

variable "github_environment" {
  description = "GitHub environment whose jobs may impersonate the deployer (add required reviewers there)."
  type        = string
  default     = "production"
}

variable "api_service_name" {
  description = "Existing Cloud Run API Service (not managed here yet)."
  type        = string
  default     = "ai-subs-backend"
}

variable "artifact_registry_repository" {
  description = "Existing Artifact Registry Docker repository (not managed here yet)."
  type        = string
  default     = "ai-subs-repo"
}
