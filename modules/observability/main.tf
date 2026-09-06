resource "google_logging_project_bucket_config" "agent_logs" {
  project          = var.project_id
  location         = "global"
  bucket_id        = var.log_bucket_id
  description      = "Analytics-enabled logs for every Agent Engine runtime in this project."
  retention_days   = var.log_retention_days
  enable_analytics = true
}

resource "google_logging_project_sink" "agent_logs" {
  project     = var.project_id
  name        = "agent-engine-runtimes"
  description = "Routes logs from every Agent Engine runtime into the shared analytics bucket."
  destination = "logging.googleapis.com/projects/${var.project_id}/locations/global/buckets/${google_logging_project_bucket_config.agent_logs.bucket_id}"
  filter      = <<-EOT
    resource.type="aiplatform.googleapis.com/ReasoningEngine"
  EOT

  unique_writer_identity = false
}

resource "google_logging_metric" "agent_errors" {
  project     = var.project_id
  name        = "agent_engine_errors"
  description = "ERROR-or-higher log entries from any Agent Engine runtime, labelled by runtime."
  filter      = <<-EOT
    resource.type="aiplatform.googleapis.com/ReasoningEngine"
    severity>=ERROR
  EOT

  metric_descriptor {
    metric_kind = "DELTA"
    value_type  = "INT64"
    unit        = "1"

    # Keeps one metric usable for every runtime: a chart or alert groups by
    # this label instead of needing a metric per agent.
    labels {
      key         = "reasoning_engine_id"
      value_type  = "STRING"
      description = "Agent Engine runtime that produced the entry."
    }
  }

  label_extractors = {
    reasoning_engine_id = "EXTRACT(resource.labels.reasoning_engine_id)"
  }
}

resource "google_monitoring_dashboard" "agent" {
  project = var.project_id

  dashboard_json = jsonencode({
    displayName = "Agent Engine runtimes"
    mosaicLayout = {
      columns = 12
      tiles = [
        {
          width  = 6
          height = 4
          widget = {
            title = "Request rate by runtime"
            xyChart = {
              dataSets = [
                {
                  plotType = "LINE"
                  timeSeriesQuery = {
                    timeSeriesFilter = {
                      filter = "metric.type=\"aiplatform.googleapis.com/reasoning_engine/request_count\" resource.type=\"aiplatform.googleapis.com/ReasoningEngine\""
                      aggregation = {
                        alignmentPeriod    = "60s"
                        perSeriesAligner   = "ALIGN_RATE"
                        crossSeriesReducer = "REDUCE_SUM"
                        groupByFields      = ["resource.label.reasoning_engine_id"]
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
            title = "Request latency by runtime"
            xyChart = {
              dataSets = [
                {
                  plotType = "LINE"
                  timeSeriesQuery = {
                    timeSeriesFilter = {
                      filter = "metric.type=\"aiplatform.googleapis.com/reasoning_engine/request_latencies\" resource.type=\"aiplatform.googleapis.com/ReasoningEngine\""
                      aggregation = {
                        alignmentPeriod    = "60s"
                        perSeriesAligner   = "ALIGN_PERCENTILE_95"
                        crossSeriesReducer = "REDUCE_MEAN"
                        groupByFields      = ["resource.label.reasoning_engine_id"]
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
  display_name = "Agent Engine runtimes: server errors"
  combiner     = "OR"

  conditions {
    display_name = "5xx request rate above zero"

    condition_threshold {
      filter = "metric.type=\"aiplatform.googleapis.com/reasoning_engine/request_count\" AND resource.type=\"aiplatform.googleapis.com/ReasoningEngine\" AND metric.labels.response_code_class=\"5xx\""

      comparison      = "COMPARISON_GT"
      threshold_value = 0
      duration        = "300s"

      aggregations {
        alignment_period     = "60s"
        per_series_aligner   = "ALIGN_RATE"
        cross_series_reducer = "REDUCE_SUM"

        # One incident per failing runtime rather than one for the project.
        group_by_fields = ["resource.label.reasoning_engine_id"]
      }
    }
  }

  notification_channels = var.notification_channels

  documentation {
    content   = "Investigate Agent Engine request failures in Cloud Logging and Cloud Trace. The incident labels name the affected runtime."
    mime_type = "text/markdown"
  }
}
