variable "project_id" {
  description = "Existing Google Cloud project ID. Shared project creation belongs to foundation/bootstrap IaC."
  type        = string
}

variable "region" {
  description = "Agent Engine region."
  type        = string
  default     = "us-central1"
}

variable "agent_display_name" {
  description = "Human-readable Agent Engine name."
  type        = string
}

variable "agent_description" {
  description = "Agent Engine description."
  type        = string
  default     = "Managed Gemini Enterprise ADK agent"
}

variable "source_archive_path" {
  description = "Path to the deterministic agent source archive produced by the application build."
  type        = string
}

variable "entrypoint_module" {
  description = "Python module containing the ADK root agent."
  type        = string
}

variable "entrypoint_object" {
  description = "Python object exported by entrypoint_module."
  type        = string
  default     = "root_agent"
}

variable "python_version" {
  description = "Python runtime version for source deployment."
  type        = string
  default     = "3.12"
}

variable "requirements_file" {
  description = "Requirements file inside the supplied source archive."
  type        = string
  default     = "requirements.txt"
}

variable "config_parameter_id" {
  description = "Parameter Manager parameter ID containing live non-secret runtime configuration."
  type        = string
}

variable "config_revision" {
  description = "Unique source-control revision used when publishing a runtime configuration version. A 12-character Git SHA is recommended."
  type        = string

  validation {
    condition     = can(regex("^[a-z0-9][a-z0-9_-]{0,19}$", var.config_revision))
    error_message = "config_revision must be 1-20 lowercase letters, numbers, underscores or hyphens."
  }
}

variable "config_refresh_seconds" {
  description = "Maximum runtime config cache interval before the agent checks Parameter Manager latest again."
  type        = number
  default     = 30

  validation {
    condition     = var.config_refresh_seconds >= 5
    error_message = "config_refresh_seconds must be at least 5 seconds."
  }
}

variable "runtime_config" {
  description = "Live non-secret application configuration. Terraform/Git is authoritative; this map is published as JSON to Parameter Manager. config_revision is injected automatically."
  type        = map(string)

  validation {
    condition = alltrue([
      for required_key in ["model", "instruction"] : contains(keys(var.runtime_config), required_key)
    ])
    error_message = "runtime_config must define model and instruction."
  }
}

variable "bootstrap_env" {
  description = "Process-construction Agent Engine environment variables only. Normal live settings belong in runtime_config."
  type        = map(string)
  default     = {}

  validation {
    condition = length(setintersection(
      toset(keys(var.bootstrap_env)),
      toset([
        "GOOGLE_CLOUD_PROJECT",
        "GOOGLE_CLOUD_QUOTA_PROJECT",
        "GOOGLE_CLOUD_LOCATION",
        "PORT",
        "K_SERVICE",
        "K_REVISION",
        "K_CONFIGURATION",
        "GOOGLE_APPLICATION_CREDENTIALS",
      ])
    )) == 0
    error_message = "bootstrap_env contains a reserved Agent Runtime environment variable."
  }
}

variable "managed_secrets" {
  description = "Secret Manager secrets owned by this stack, keyed by runtime environment variable name."
  type = map(object({
    secret_id     = string
    value_version = optional(number, 1)
    labels        = optional(map(string), {})
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

variable "external_secret_env" {
  description = "References to pre-existing Secret Manager secrets not created by this stack."
  type = map(object({
    secret  = string
    version = optional(string, "latest")
  }))
  default = {}
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
  description = "Whether developer_deployer_members may read the shared dev Parameter Manager config."
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
  description = "Set true when the dev project does not belong to a Google Cloud organization."
  type        = bool
  default     = false
}

variable "developer_agent_identity_project_roles" {
  description = "Common non-sensitive project roles granted to all Agent Runtime Agent Identities in this dev project."
  type        = set(string)
  default = [
    "roles/aiplatform.expressUser",
    "roles/serviceusage.serviceUsageConsumer",
    "roles/parametermanager.parameterAccessor",
  ]
}

variable "invoker_members" {
  description = "Users, groups or service accounts allowed to invoke the Terraform-managed Reasoning Engine."
  type        = set(string)
  default     = []
}

variable "invoker_role" {
  description = "Optional existing Reasoning Engine invoker role. When null, the module creates a query-only custom role."
  type        = string
  default     = null
  nullable    = true
}

variable "agent_project_roles" {
  description = "Project-level roles granted directly to the Terraform-managed Agent Identity."
  type        = set(string)
  default = [
    "roles/aiplatform.expressUser",
    "roles/serviceusage.serviceUsageConsumer",
    "roles/parametermanager.parameterAccessor",
  ]
}

variable "min_instances" {
  type    = number
  default = 1
}

variable "max_instances" {
  type    = number
  default = 10
}

variable "container_concurrency" {
  type    = number
  default = 9
}

variable "resource_limits" {
  type = map(string)
  default = {
    cpu    = "4"
    memory = "4Gi"
  }
}

variable "log_retention_days" {
  description = "Retention for the dedicated Agent Engine log bucket."
  type        = number
  default     = 90
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
