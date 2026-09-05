# Execution identities and IAM ownership

No application helper grants IAM to itself.

## Identity matrix

| Actor | Authentication | Access assigned by | Purpose |
|---|---|---|---|
| Developer local run | User ADC | Terraform/platform IAM | Local agent and permitted dev resources |
| Developer deploy/update | User ADC | This stack | Developer Agent Engine operations |
| Terraform runner | GitHub OIDC -> WIF -> dedicated service account | Foundation/bootstrap IaC | Infrastructure changes |
| Terraform-managed runtime | Agent Identity | This stack | Shared agent downstream access |
| Developer-created runtime | Agent Identity | Common project principal-set roles plus specific grants | Developer Agent Engine runtime access |
| Caller | User/group/workload identity | This stack | Reasoning Engine invocation |
| Delegated user | Forwarded OAuth credential | Gemini Enterprise/auth flow | User-scoped downstream calls |
| Agent Platform service agent | Google-managed | This stack grants secret access | Platform operations and `secret_env` reads |

## Developer identity

The agent repository `deploy_dev.py` and `update_dev.py` use ADC. Terraform can grant `developer_deployer_members` Agent Engine access, Parameter Manager read access and staging-bucket object access. Prefer a Google Group to repeated individual bindings.

The helpers do not change IAM when an operation is denied.

## Developer-created Agent Identity

Every Agent Engine created with `identity_type=AGENT_IDENTITY` receives a distinct runtime identity. Developer permissions are not inherited by that identity.

For common non-sensitive dev permissions, this stack uses the Agent Identity principal set for all Agent Runtime agents in the project. Organization and orgless projects use different trust-domain prefixes; configure exactly one through the provided variables.

The Terraform-managed Agent Engine is created before the project-wide principal-set grants. This ensures the Agent Identity trust domain has been initialized before Terraform applies common bindings.

Common roles should be limited to runtime basics such as model/quota use and Parameter Manager reads. Sensitive data permissions should target an individual Agent Identity.

## Terraform runner

The workload stack assumes its execution identity already exists and is authorized. Create the following in a separate foundation/bootstrap stack:

- Workload Identity Pool
- GitHub OIDC provider
- repository/branch/environment attribute restrictions
- dedicated Terraform service account
- `roles/iam.workloadIdentityUser` binding
- minimum Terraform infrastructure-management permissions
- remote-state bucket and IAM

Do not use downloaded long-lived service-account keys.

## Terraform-managed Agent Identity

The Agent Engine module obtains the runtime's effective Agent Identity and grants only `agent_project_roles`. Prefer resource-level IAM for sensitive resources when practical.

Do not grant Terraform administration permissions to the Agent Identity and do not reuse the Terraform runner service account as the runtime identity.

## Secrets

Agent Runtime application calls use Agent Identity. Agent Engine deployment-time `secret_env` handling is different: the Google-managed Agent Platform service agent needs `roles/secretmanager.secretAccessor` on referenced secrets. This stack grants that role only for configured secret references.
