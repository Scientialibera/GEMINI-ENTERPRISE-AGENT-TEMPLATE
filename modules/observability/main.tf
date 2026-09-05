resource "google_logging_project_bucket_config" "agent_logs" {
  project          = var.project_id
  location         = "global"
  bucket_id        = var.log_bucket_id
  description      = "Analytics-enabled logs for managed Agent Engine runtime ${var.reasoning_engine_id}."
  retention_days   = var.log_retention_days
  enable_analytics = true
}

resource "google_logging_project_sink" "agent_logs" {
  project     = var.project_id
  name        = "agent-engine-${var.reasoning_engine_id}"
  description = "Routes logs for one Agent Engine runtime into its analytics bucket."
  destination = "logging.googleapis.com/projects/${var.project_id}/locations/global/buckets/${google_logging_project_bucket_config.agent_logs.bucket_id}"
  filter      = <<-EOT
    resource.type="aiplatform.googleapis.com/ReasoningEngine"
    resource.labels.reasoning_engine_id="${var.reasoning_engine_id}"
  EOT

  unique_writer_identity = false
}

resource "google_logging_metric" "agent_errors" {
  project     = var.project_id
  name        = "agent_engine_${replace(var.reasoning_engine_id, "-", "_")}_errors"
  description = "ERROR-or-higher log entries for this Agent Engine runtime."
  filter      = <<-EOT
    resource.type="aiplatform.googleapis.com/ReasoningEngine"
    resource.labels.reasoning_engine_id="${var.reasoning_engine_id}"
    severity>=ERROR
  EOT

  metric_descriptor {
    metric_kind = "DELTA"
    value_type  = "INT64"
    unit        = "1"
  }
}

resource "google_monitoring_dashboard" "agent" {
  project = var.project_id

  dashboard_json = jsonencode({
    displayName = "Agent Engine - ${var.reasoning_engine_id}"
    mosaicLayout = {
      columns = 12
      tiles = [
        {
          width  = 6
          height = 4
          widget = {
            title = "Request rate"
            xyChart = {
              dataSets = [
                {
                  plotType = "LINE"
                  timeSeriesQuery = {
                    timeSeriesFilter = {
                      filter = "metric.type=\"aiplatform.googleapis.com/reasoning_engine/request_count\" resource.type=\"aiplatform.googleapis.com/ReasoningEngine\" resource.label.reasoning_engine_id=\"${var.reasoning_engine_id}\""
                      aggregation = {
                        alignmentPeriod    = "60s"
                        perSeriesAligner   = "ALIGN_RATE"
                        crossSeriesReducer = "REDUCE_SUM"
                      }
                    }
                  }
                }
              ]
              yAxis = {
                label = "requests/sec"
                scale = "LINEAR"
              }
            }
          }
        },
        {
          xPos   = 6
          width  = 6
          height = 4
          widget = {
            title = "Request latency"
            xyChart = {
              dataSets = [
                {
                  plotType = "LINE"
                  timeSeriesQuery = {
                    timeSeriesFilter = {
                      filter = "metric.type=\"aiplatform.googleapis.com/reasoning_engine/request_latencies\" resource.type=\"aiplatform.googleapis.com/ReasoningEngine\" resource.label.reasoning_engine_id=\"${var.reasoning_engine_id}\""
                      aggregation = {
                        alignmentPeriod  = "60s"
                        perSeriesAligner = "ALIGN_PERCENTILE_95"
                      }
                    }
                  }
                }
              ]
              yAxis = {
                label = "p95 latency"
                scale = "LINEAR"
              }
            }
          }
        }
      ]
    }
  })
}

resource "google_monitoring_alert_policy" "server_errors" {
  project      = var.project_id
  display_name = "Agent Engine ${var.reasoning_engine_id}: server errors"
  combiner     = "OR"

  conditions {
    display_name = "5xx request rate above zero"

    condition_threshold {
      filter = "metric.type=\"aiplatform.googleapis.com/reasoning_engine/request_count\" AND resource.type=\"aiplatform.googleapis.com/ReasoningEngine\" AND resource.labels.reasoning_engine_id=\"${var.reasoning_engine_id}\" AND metric.labels.response_code_class=\"5xx\""

      comparison      = "COMPARISON_GT"
      threshold_value = 0
      duration        = "300s"

      aggregations {
        alignment_period     = "60s"
        per_series_aligner   = "ALIGN_RATE"
        cross_series_reducer = "REDUCE_SUM"
      }
    }
  }

  notification_channels = var.notification_channels

  documentation {
    content   = "Investigate Agent Engine request failures in Cloud Logging and Cloud Trace."
    mime_type = "text/markdown"
  }
}
