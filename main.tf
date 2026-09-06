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
  published_runtime_config = merge(
    var.runtime_config,
    { config_revision = var.config_revision }
  )
  runtime_config_hash       = substr(sha256(jsonencode(local.published_runtime_config)), 0, 12)
  runtime_config_version_id = "cfg-${var.config_revision}-${local.runtime_config_hash}"

  agent_resource_key      = substr(sha1(join("/", [var.region, var.agent_display_name])), 0, 12)
  effective_log_bucket_id = coalesce(var.log_bucket_id, "agent-engine-${local.agent_resource_key}")

  # Orgless trust domains use the "proj-" prefix. Public documentation shows
  # "project-", but IAM rejects that form with "member is of an unknown type";
  # the effectiveIdentity reported by a deployed Agent Engine confirms "proj-".
  developer_agent_identity_principal_set = var.developer_agent_identity_organization_id != null ? (
    "principalSet://agents.global.org-${var.developer_agent_identity_organization_id}.system.id.goog/attribute.platformContainer/aiplatform/projects/${data.google_project.current.number}"
    ) : (
    "principalSet://agents.global.proj-${data.google_project.current.number}.system.id.goog/attribute.platformContainer/aiplatform/projects/${data.google_project.current.number}"
  )

  bootstrap_env_names = setunion(
    toset(keys(var.bootstrap_env)),
    toset([
      "CONFIG_PARAMETER",
      "CONFIG_PARAMETER_LOCATION",
      "CONFIG_REFRESH_SECONDS",
      "GOOGLE_CLOUD_AGENT_ENGINE_ENABLE_TELEMETRY",
      "OTEL_SEMCONV_STABILITY_OPT_IN",
    ])
  )

  # Secrets are stored, never injected into the Agent Runtime. Runtime secret
  # injection is not supported for source-archive deployments: a Reasoning
  # Engine that starts correctly is still reported as failed once secret_env is
  # attached, with no application-level error. An agent that needs a secret
  # reads it from Secret Manager at runtime using its own Agent Identity, which
  # works on every deployment path and keeps the value out of the environment.
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
  input = "agent-template-configuration"

  lifecycle {
    precondition {
      condition = length(var.developer_deployer_members) == 0 || (
        (var.developer_agent_identity_organization_id != null) != var.developer_agent_identity_orgless
      )
      error_message = "When developer_deployer_members is non-empty, set developer_agent_identity_organization_id for an organization project or developer_agent_identity_orgless=true for an orgless project. Set exactly one."
    }

    precondition {
      condition     = var.min_instances <= var.max_instances
      error_message = "min_instances cannot exceed max_instances."
    }

  }
}

resource "google_parameter_manager_parameter" "runtime_config" {
  project      = var.project_id
  parameter_id = var.config_parameter_id
  format       = "JSON"

  depends_on = [
    google_project_service.required,
    terraform_data.configuration_validation,
  ]
}

resource "google_parameter_manager_parameter_version" "runtime_config" {
  parameter            = google_parameter_manager_parameter.runtime_config.id
  parameter_version_id = local.runtime_config_version_id
  parameter_data       = jsonencode(local.published_runtime_config)

  deletion_policy = "ABANDON"

  lifecycle {
    create_before_destroy = true
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

locals {
  agent_bootstrap_env = merge(
    var.bootstrap_env,
    {
      CONFIG_PARAMETER                           = google_parameter_manager_parameter.runtime_config.id
      CONFIG_PARAMETER_LOCATION                  = "global"
      CONFIG_REFRESH_SECONDS                     = tostring(var.config_refresh_seconds)
      GOOGLE_CLOUD_AGENT_ENGINE_ENABLE_TELEMETRY = "true"
      OTEL_SEMCONV_STABILITY_OPT_IN              = "gen_ai_latest_experimental"
    }
  )
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

# Principals that must read a managed secret directly, such as the release
# process that creates a Gemini Enterprise authorization from the OAuth client
# secret. Keeping the payload in Secret Manager means it is never copied into a
# developer environment file.
resource "google_secret_manager_secret_iam_member" "managed_secret_readers" {
  for_each = local.managed_secret_reader_bindings

  project   = var.project_id
  secret_id = each.value.secret
  role      = "roles/secretmanager.secretAccessor"
  member    = each.value.member

  depends_on = [google_secret_manager_secret.managed]
}

module "agent_engine" {
  source = "./modules/agent_engine"

  providers = {
    google      = google
    google-beta = google-beta
  }

  project_id            = var.project_id
  region                = var.region
  display_name          = var.agent_display_name
  description           = var.agent_description
  source_archive_path   = var.source_archive_path
  entrypoint_module     = var.entrypoint_module
  entrypoint_object     = var.entrypoint_object
  python_version        = var.python_version
  requirements_file     = var.requirements_file
  runtime_env           = local.agent_bootstrap_env
  invoker_members       = var.invoker_members
  invoker_role          = var.invoker_role
  agent_project_roles   = var.agent_project_roles
  min_instances         = var.min_instances
  max_instances         = var.max_instances
  container_concurrency = var.container_concurrency
  resource_limits       = var.resource_limits

  depends_on = [
    terraform_data.configuration_validation,
    google_project_service.required,
    google_parameter_manager_parameter_version.runtime_config,
    google_secret_manager_secret_version.managed,
  ]
}

resource "google_project_iam_member" "developer_agent_identity_common" {
  for_each = length(var.developer_deployer_members) == 0 ? toset([]) : var.developer_agent_identity_project_roles

  project = var.project_id
  role    = each.value
  member  = local.developer_agent_identity_principal_set

  # Intentionally independent of module.agent_engine. This grant covers Agent
  # Identities of developer-created Agent Engines, which are deployed from the
  # agent repository and must be able to read runtime configuration even when
  # no Terraform-managed Agent Engine exists yet. Ordering it after the module
  # would make a first-time developer deployment unusable.
  depends_on = [google_project_service.required]
}

module "observability" {
  source = "./modules/observability"

  project_id            = var.project_id
  region                = var.region
  reasoning_engine_id   = module.agent_engine.reasoning_engine_id
  log_bucket_id         = local.effective_log_bucket_id
  log_retention_days    = var.log_retention_days
  notification_channels = var.notification_channels

  depends_on = [google_project_service.required]
}
