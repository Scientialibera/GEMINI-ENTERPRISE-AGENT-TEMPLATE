output "reasoning_engine_name" {
  value = module.agent_engine.reasoning_engine_name
}

output "reasoning_engine_id" {
  value = module.agent_engine.reasoning_engine_id
}

output "agent_identity" {
  value = module.agent_engine.agent_identity
}

output "runtime_config_parameter" {
  value = google_parameter_manager_parameter.runtime_config.id
}

output "runtime_config_version" {
  value = google_parameter_manager_parameter_version.runtime_config.id
}

output "runtime_config_hash" {
  value = local.runtime_config_hash
}

output "log_bucket" {
  value = module.observability.log_bucket
}
