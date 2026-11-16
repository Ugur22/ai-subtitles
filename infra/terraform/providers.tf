provider "google" {
  project = var.project_id
  region  = var.region

  # The Billing Budgets API rejects user ADC credentials unless calls are billed to a quota project.
  user_project_override = true
  billing_project       = var.project_id
}

data "google_project" "this" {
  project_id = var.project_id
}
