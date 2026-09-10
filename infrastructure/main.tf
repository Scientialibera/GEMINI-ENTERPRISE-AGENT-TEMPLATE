data "google_project" "current" {
  project_id = var.project_id
}

resource "google_project_service" "required" {
  for_each = var.required_services

  project            = var.project_id
  service            = each.value
  disable_on_destroy = false
}

locals {
  effective_log_bucket_id      = coalesce(var.log_bucket_id, "agent-engine-runtimes")
  runtime_iam_policy           = jsondecode(file("${path.module}/runtime_iam_policy.json"))
  agent_identity_project_roles = var.agent_identity_project_roles != null ? var.agent_identity_project_roles : toset(local.runtime_iam_policy.baseline_project_roles)

  # Orgless trust domains use "proj-". Documentation shows "project-", which
  # IAM rejects as an unknown member type.
  agent_identity_principal_set = var.developer_agent_identity_organization_id != null ? (
    "principalSet://agents.global.org-${var.developer_agent_identity_organization_id}.system.id.goog/attribute.platformContainer/aiplatform/projects/${data.google_project.current.number}"
    ) : (
    "principalSet://agents.global.proj-${data.google_project.current.number}.system.id.goog/attribute.platformContainer/aiplatform/projects/${data.google_project.current.number}"
  )

  # Secrets are stored, never injected. An agent that needs a secret reads it
  # from Secret Manager at runtime using its own Agent Identity.
  managed_secret_reader_bindings = merge([
    for env_name, config in var.managed_secrets : {
      for member in config.accessor_members :
      "${env_name}/${member}" => {
        secret = config.secret_id
        member = member
      }
    }
  ]...)
}

resource "terraform_data" "configuration_validation" {
  input = "agent-platform-configuration"

  lifecycle {
    precondition {
      condition = (length(var.developer_deployer_members) == 0 && length(local.agent_identity_project_roles) == 0 && var.developer_staging_bucket_name == null) || (
        (var.developer_agent_identity_organization_id != null) != var.developer_agent_identity_orgless
      )
      error_message = "When developer or runtime IAM bindings are configured, set exactly one of developer_agent_identity_organization_id or developer_agent_identity_orgless=true."
    }
  }
}

resource "google_secret_manager_secret" "managed" {
  for_each = var.managed_secrets

  project   = var.project_id
  secret_id = each.value.secret_id
  labels    = each.value.labels

  replication {
    auto {}
  }

  depends_on = [
    google_project_service.required,
    terraform_data.configuration_validation,
  ]
}

resource "google_secret_manager_secret_version" "managed" {
  for_each = var.managed_secrets

  secret                 = google_secret_manager_secret.managed[each.key].id
  secret_data_wo         = var.secret_values[each.key]
  secret_data_wo_version = each.value.value_version
  deletion_policy        = "DISABLE"

  lifecycle {
    precondition {
      condition     = contains(keys(var.secret_values), each.key)
      error_message = "managed_secrets[\"${each.key}\"] has no payload in secret_values. Supply it at apply time from an approved ephemeral secret source (never in tfvars or state)."
    }
  }
}

resource "google_project_iam_member" "developer_agent_deployer" {
  for_each = var.developer_deployer_members

  project = var.project_id
  role    = var.developer_deployer_role
  member  = each.value
}

resource "google_project_iam_member" "developer_parameter_accessor" {
  for_each = var.developer_parameter_access ? var.developer_deployer_members : toset([])

  project = var.project_id
  role    = "roles/parametermanager.parameterAccessor"
  member  = each.value
}

resource "google_storage_bucket_iam_member" "developer_staging_bucket_writer" {
  for_each = var.developer_staging_bucket_name == null ? toset([]) : var.developer_deployer_members

  bucket = var.developer_staging_bucket_name
  role   = "roles/storage.objectAdmin"
  member = each.value
}

# Principals that read a managed secret themselves, such as the release process
# that creates a Gemini Enterprise authorization from the OAuth client secret.
resource "google_secret_manager_secret_iam_member" "managed_secret_readers" {
  for_each = local.managed_secret_reader_bindings

  project   = var.project_id
  secret_id = each.value.secret
  role      = "roles/secretmanager.secretAccessor"
  member    = each.value.member

  depends_on = [google_secret_manager_secret.managed]
}

# Runtime permissions for every Agent Identity in this project. The principal
# set covers Agent Engines this stack never sees, which is what lets a developer
# add an agent to the repository and deploy it without a Terraform change.
resource "google_project_iam_member" "agent_identity_common" {
  for_each = local.agent_identity_project_roles

  project = var.project_id
  role    = each.value
  member  = local.agent_identity_principal_set

  depends_on = [
    google_project_service.required,
    terraform_data.configuration_validation,
  ]
}

# Source archives are readable only in the configured staging bucket. Business
# data buckets need explicit grants to the individual runtime identity.
resource "google_storage_bucket_iam_member" "agent_identity_staging_reader" {
  count = var.developer_staging_bucket_name == null ? 0 : 1

  bucket = var.developer_staging_bucket_name
  role   = local.runtime_iam_policy.staging_bucket_reader_role
  member = local.agent_identity_principal_set

  depends_on = [
    google_project_service.required,
    terraform_data.configuration_validation,
  ]
}

module "observability" {
  source = "./modules/observability"

  project_id            = var.project_id
  region                = var.region
  log_bucket_id         = local.effective_log_bucket_id
  log_retention_days    = var.log_retention_days
  notification_channels = var.notification_channels

  depends_on = [google_project_service.required]
}
