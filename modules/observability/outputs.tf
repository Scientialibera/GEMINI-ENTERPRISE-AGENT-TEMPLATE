output "log_bucket" {
  value = google_logging_project_bucket_config.agent_logs.id
}
