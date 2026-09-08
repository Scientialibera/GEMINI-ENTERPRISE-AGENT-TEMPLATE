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
