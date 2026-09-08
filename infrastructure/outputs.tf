output "agent_identity_principal_set" {
  description = "Trust-domain principal set covering every Agent Identity in this project. Roles granted to it apply to agents this stack never sees."
  value       = local.agent_identity_principal_set
}

output "log_bucket" {
  value = module.observability.log_bucket
}

output "managed_secret_ids" {
  description = "Secret Manager secret ids created by this stack, keyed by runtime environment variable name. Consumers read the payload from Secret Manager rather than receiving it directly."
  value       = { for env_name, config in var.managed_secrets : env_name => config.secret_id }
}
