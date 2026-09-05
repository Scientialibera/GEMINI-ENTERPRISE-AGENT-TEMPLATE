terraform {
  required_providers {
    google = {
      source = "hashicorp/google"
    }
    google-beta = {
      source = "hashicorp/google-beta"
    }
  }
}

locals {
  invoker_role_scope        = join("/", [var.project_id, var.region, var.display_name])
  generated_invoker_role_id = "agentRuntimeUser_${substr(sha1(local.invoker_role_scope), 0, 12)}"
}

resource "google_project_iam_custom_role" "agent_user" {
  count = var.invoker_role == null ? 1 : 0

  project     = var.project_id
  role_id     = local.generated_invoker_role_id
  title       = "Agent runtime user - ${var.display_name}"
  description = "Allows querying one approved Vertex AI Agent Engine runtime."
  permissions = ["aiplatform.reasoningEngines.query"]
}

locals {
  effective_invoker_role = var.invoker_role != null ? var.invoker_role : google_project_iam_custom_role.agent_user[0].name
}

resource "google_vertex_ai_reasoning_engine" "this" {
  provider = google-beta

  project      = var.project_id
  region       = var.region
  display_name = var.display_name
  description  = var.description

  spec {
    class_methods   = file("${path.module}/adk_class_methods.json")
    agent_framework = "google-adk"
    identity_type   = "AGENT_IDENTITY"

    source_code_spec {
      inline_source {
        source_archive = filebase64(var.source_archive_path)
      }

      python_spec {
        entrypoint_module = var.entrypoint_module
        entrypoint_object = var.entrypoint_object
        requirements_file = var.requirements_file
        version           = var.python_version
      }
    }

    deployment_spec {
      min_instances         = var.min_instances
      max_instances         = var.max_instances
      container_concurrency = var.container_concurrency
      resource_limits       = var.resource_limits

      dynamic "env" {
        for_each = var.runtime_env
        content {
          name  = env.key
          value = env.value
        }
      }

      dynamic "secret_env" {
        for_each = var.secret_env
        content {
          name = secret_env.key
          secret_ref {
            secret  = secret_env.value.secret
            version = secret_env.value.version
          }
        }
      }
    }
  }
}

locals {
  agent_identity_member = startswith(
    google_vertex_ai_reasoning_engine.this.spec[0].effective_identity,
    "principal://",
  ) ? google_vertex_ai_reasoning_engine.this.spec[0].effective_identity : "principal://${google_vertex_ai_reasoning_engine.this.spec[0].effective_identity}"
}

resource "google_vertex_ai_reasoning_engine_iam_binding" "invokers" {
  count = length(var.invoker_members) > 0 ? 1 : 0

  project          = var.project_id
  region           = var.region
  reasoning_engine = google_vertex_ai_reasoning_engine.this.name
  role             = local.effective_invoker_role
  members          = sort(tolist(var.invoker_members))
}

resource "google_project_iam_member" "agent_project_roles" {
  for_each = var.agent_project_roles

  project = var.project_id
  role    = each.value
  member  = local.agent_identity_member
}
