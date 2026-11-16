terraform {
  required_version = ">= 1.5"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "8.9.0"
    }
  }

  # Created by infra/bootstrap_state_bucket.sh; Terraform cannot create its own state bucket.
  backend "gcs" {
    bucket = "ai-subs-poc-tfstate"
    prefix = "terraform/state"
  }
}
