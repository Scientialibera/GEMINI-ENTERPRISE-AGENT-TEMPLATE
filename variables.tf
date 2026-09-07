variable "project_id" {
  description = "Existing Google Cloud project ID. Shared project creation belongs to foundation/bootstrap IaC."
  type        = string
}

variable "region" {
  description = "Region the agent runtimes in this project are deployed to."
  type        = string
  default     = "us-central1"
}

variable "managed_secrets" {
  description = <<-EOT
    Secret Manager secrets owned by this stack. Secrets are stored, not injected
    into the Agent Runtime: runtime secret_env is unsupported for source-archive
    deployments, and an agent that needs a secret reads it from Secret Manager
    using its own Agent Identity. `accessor_members` grants read access to the
    principals that must read the payload themselves, such as the release
    process that creates a Gemini Enterprise authorization from an OAuth client
    secret, so the value is stored once and never copied to a workstation.
  EOT
  type = map(object({
    secret_id        = string
    value_version    = optional(number, 1)
    labels           = optional(map(string), {})
    accessor_members = optional(set(string), [])
  }))
  default = {}
}

variable "secret_values" {
  description = "Ephemeral secret payloads keyed exactly like managed_secrets. Supply from an approved CI/secret source."
  type        = map(string)
  sensitive   = true
  ephemeral   = true
  default     = {}
}

variable "developer_deployer_members" {
  description = "Developers/groups allowed to use the agent repository dev deployment helpers."
  type        = set(string)
  default     = []
}

variable "developer_deployer_role" {
  description = "Project role granted to developer_deployer_members for Agent Engine create/update operations."
  type        = string
  default     = "roles/aiplatform.user"
}

variable "developer_parameter_access" {
  description = "Whether developer_deployer_members may read agent runtime configuration in Parameter Manager."
  type        = bool
  default     = true
}

variable "developer_staging_bucket_name" {
  description = "Optional existing developer staging bucket. Terraform grants object write access but does not create the bucket."
  type        = string
  default     = null
  nullable    = true
}

variable "developer_agent_identity_organization_id" {
  description = "Organization ID used to construct the Agent Identity trust-domain principal set. Null for an orgless project."
  type        = string
  default     = null
  nullable    = true
}

variable "developer_agent_identity_orgless" {
  description = "Set true when the project does not belong to a Google Cloud organization."
  type        = bool
  default     = false
}

variable "agent_identity_project_roles" {
  description = <<-EOT
    Baseline project roles granted to every Agent Identity in this project,
    through a trust-domain principal set rather than per-agent bindings. Keep
    this list limited to common platform plumbing required by every runtime.
    Workload/data access such as Cloud Storage, datasets and secrets belongs on
    the exact Agent Identity and the narrowest practical target resource.
  EOT
  type        = set(string)
  default = [
    "roles/aiplatform.expressUser",
    "roles/serviceusage.serviceUsageConsumer",
    "roles/parametermanager.parameterAccessor",
  ]
}

variable "log_bucket_id" {
  description = "Optional Cloud Logging bucket ID for agent runtime logs."
  type        = string
  default     = null
  nullable    = true
}

variable "log_retention_days" {
  description = "Retention for the Agent Engine log bucket."
  type        = number
  default     = 90

  validation {
    condition     = var.log_retention_days >= 1
    error_message = "log_retention_days must be at least 1."
  }
}

variable "notification_channels" {
  description = "Existing Cloud Monitoring notification channel IDs."
  type        = list(string)
  default     = []
}

variable "required_services" {
  description = "Google Cloud APIs required by the workload stack."
  type        = set(string)
  default = [
    "aiplatform.googleapis.com",
    "parametermanager.googleapis.com",
    "logging.googleapis.com",
    "monitoring.googleapis.com",
    "cloudtrace.googleapis.com",
    "telemetry.googleapis.com",
    "secretmanager.googleapis.com",
    "serviceusage.googleapis.com",
    "storage.googleapis.com",
  ]
}
