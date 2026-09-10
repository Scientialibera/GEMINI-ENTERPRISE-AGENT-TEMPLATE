mock_provider "google" {
  mock_data "google_project" {
    defaults = { number = "123456789" }
  }
}
mock_provider "google-beta" {}

variables {
  project_id                               = "unit-test-project"
  developer_deployer_members               = []
  developer_agent_identity_organization_id = null
  developer_agent_identity_orgless         = false
  managed_secrets                          = {}
  secret_values                            = {}
  developer_staging_bucket_name            = null
  agent_identity_project_roles             = ["roles/aiplatform.expressUser"]
}

run "runtime_roles_require_trust_domain" {
  command         = plan
  expect_failures = [terraform_data.configuration_validation]
}

run "orgless_runtime_roles" {
  command = plan
  variables { developer_agent_identity_orgless = true }
  assert {
    condition     = strcontains(local.agent_identity_principal_set, "proj-123456789")
    error_message = "Orgless runtime roles must use the project's trust domain."
  }
}

run "organization_runtime_roles" {
  command = plan
  variables { developer_agent_identity_organization_id = "999" }
  assert {
    condition     = strcontains(local.agent_identity_principal_set, "org-999")
    error_message = "Organization runtime roles must use the organization's trust domain."
  }
}

run "ambiguous_trust_domain_rejected" {
  command = plan
  variables {
    developer_agent_identity_organization_id = "999"
    developer_agent_identity_orgless         = true
  }
  expect_failures = [terraform_data.configuration_validation]
}

run "default_policy_limits_storage_to_staging" {
  command = plan
  variables {
    developer_agent_identity_orgless = true
    developer_staging_bucket_name    = "unit-test-staging"
    agent_identity_project_roles     = null
  }
  assert {
    condition     = !contains(keys(google_project_iam_member.agent_identity_common), "roles/storage.objectViewer")
    error_message = "The default runtime policy must not grant project-wide bucket reads."
  }
  assert {
    condition     = google_storage_bucket_iam_member.agent_identity_staging_reader[0].bucket == "unit-test-staging" && google_storage_bucket_iam_member.agent_identity_staging_reader[0].role == "roles/storage.objectViewer"
    error_message = "Runtime archive reads must be bound to the configured staging bucket."
  }
}

run "staging_access_alone_requires_trust_domain" {
  command = plan
  variables {
    agent_identity_project_roles  = []
    developer_staging_bucket_name = "unit-test-staging"
  }
  expect_failures = [terraform_data.configuration_validation]
}
