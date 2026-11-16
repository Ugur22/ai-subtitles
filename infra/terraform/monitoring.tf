# Alerts by email: failed jobs, API uptime and spend. Error Reporting
# notifications have no Terraform resource; see docs/INFRASTRUCTURE.md.

resource "google_monitoring_notification_channel" "email" {
  display_name = "AI-Subs alerts (${var.alert_email})"
  type         = "email"
  labels = {
    email_address = var.alert_email
  }

  depends_on = [google_project_service.required]
}

# Counts the {"event":"job_failed",...} lines from JobQueueService._emit_job_failed,
# written by both the API Service (check-stale, dispatch errors) and the worker Job.
resource "google_logging_metric" "job_failed" {
  name        = "job_failed"
  description = "Jobs that ended as failed, by error_code and user_tier."
  filter      = <<-EOT
    resource.type=("cloud_run_revision" OR "cloud_run_job")
    jsonPayload.event="job_failed"
  EOT

  metric_descriptor {
    metric_kind  = "DELTA"
    value_type   = "INT64"
    unit         = "1"
    display_name = "Failed jobs"

    labels {
      key        = "error_code"
      value_type = "STRING"
    }
    labels {
      key        = "user_tier"
      value_type = "STRING"
    }
  }

  label_extractors = {
    error_code = "EXTRACT(jsonPayload.error_code)"
    user_tier  = "EXTRACT(jsonPayload.user_tier)"
  }

  depends_on = [google_project_service.required]
}

resource "google_monitoring_alert_policy" "job_failures" {
  display_name = "AI-Subs: more than 2 failed jobs in 1 hour"
  combiner     = "OR"

  conditions {
    display_name = "job_failed over the last hour > 2"

    # The metric comes from two monitored-resource types (the API on cloud_run_revision,
    # the worker on cloud_run_job). Cloud Monitoring PromQL requires a monitored_resource
    # matcher in that case, so each type is summed on its own and the two are added.
    # `or vector(0)` keeps an hour with failures on only one side from yielding no result.
    condition_prometheus_query_language {
      query               = <<-EOT
        (sum(increase(logging_googleapis_com:user_${google_logging_metric.job_failed.name}{monitored_resource="cloud_run_revision"}[1h])) or vector(0))
        + (sum(increase(logging_googleapis_com:user_${google_logging_metric.job_failed.name}{monitored_resource="cloud_run_job"}[1h])) or vector(0))
        > 2
      EOT
      duration            = "0s"
      evaluation_interval = "60s"
    }
  }

  alert_strategy {
    auto_close = "3600s"
  }

  documentation {
    mime_type = "text/markdown"
    content   = <<-EOT
      More than 2 jobs failed within an hour. Break them down by error_code in Logs Explorer:

      `jsonPayload.event="job_failed"`

      worker_timeout and max_continuations_reached are explained in docs/GCP_OPERATIONS.md ("Long jobs, continuations and timeouts").
    EOT
  }

  notification_channels = [google_monitoring_notification_channel.email.id]
}

resource "google_monitoring_uptime_check_config" "api_root" {
  display_name = "AI-Subs API GET /"
  # A scale-to-zero cold start loads the ML stack; give it the maximum.
  timeout = "60s"
  period  = var.uptime_check_period

  http_check {
    path           = "/"
    port           = 443
    use_ssl        = true
    validate_ssl   = true
    request_method = "GET"

    accepted_response_status_codes {
      status_class = "STATUS_CLASS_2XX"
    }
  }

  content_matchers {
    content = "\"status\":\"healthy\""
    matcher = "CONTAINS_STRING"
  }

  monitored_resource {
    type = "uptime_url"
    labels = {
      project_id = var.project_id
      host       = var.api_uptime_host
    }
  }

  depends_on = [google_project_service.required]
}

resource "google_monitoring_alert_policy" "api_down" {
  display_name = "AI-Subs: API uptime check failing"
  combiner     = "OR"

  conditions {
    display_name = "GET / failing from more than one location"

    condition_threshold {
      filter          = "metric.type=\"monitoring.googleapis.com/uptime_check/check_passed\" AND resource.type=\"uptime_url\" AND metric.label.check_id=\"${google_monitoring_uptime_check_config.api_root.uptime_check_id}\""
      comparison      = "COMPARISON_GT"
      threshold_value = 1
      duration        = "0s"

      aggregations {
        # Two probe periods, so every location has reported at least once.
        alignment_period     = "1800s"
        per_series_aligner   = "ALIGN_NEXT_OLDER"
        cross_series_reducer = "REDUCE_COUNT_FALSE"
        group_by_fields      = ["resource.label.project_id", "resource.label.host"]
      }

      trigger {
        count = 1
      }
    }
  }

  alert_strategy {
    auto_close = "1800s"
  }

  documentation {
    mime_type = "text/markdown"
    content   = "GET / on ${var.api_uptime_host} is failing from more than one location. Check the latest revision: `gcloud run services logs read ai-subs-backend --region=${var.region} --limit=100`."
  }

  notification_channels = [google_monitoring_notification_channel.email.id]
}

resource "google_billing_budget" "monthly" {
  billing_account = var.billing_account_id
  display_name    = "${var.project_id} monthly"

  budget_filter {
    projects        = ["projects/${data.google_project.this.number}"]
    calendar_period = "MONTH"
  }

  amount {
    specified_amount {
      currency_code = var.budget_currency_code
      units         = tostring(var.budget_amount)
    }
  }

  dynamic "threshold_rules" {
    for_each = [0.5, 0.9, 1.0]
    content {
      threshold_percent = threshold_rules.value
      spend_basis       = "CURRENT_SPEND"
    }
  }

  all_updates_rule {
    monitoring_notification_channels = [google_monitoring_notification_channel.email.id]
    # Billing admins keep getting the default budget emails as well.
    disable_default_iam_recipients = false
  }

  depends_on = [google_project_service.required]
}
