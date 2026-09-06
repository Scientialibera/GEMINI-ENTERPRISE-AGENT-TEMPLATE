# Execution identities and IAM ownership

No application helper grants IAM to itself.

## Identity matrix

| Actor | Authentication | Access assigned by | Purpose |
|---|---|---|---|
| Developer local run | User ADC | Terraform/platform IAM | Local agent and permitted dev resources |
| Developer deploy/update | User ADC | This stack | Agent Engine deploy and update operations |
| Terraform runner | GitHub OIDC -> WIF -> dedicated service account | Foundation/bootstrap IaC | Infrastructure changes |
| Agent runtime | Agent Identity | Common project principal-set roles plus specific grants | Agent Engine runtime access |
| Caller | User/group/workload identity | Granted per runtime outside this stack | Reasoning Engine invocation |
| Delegated user | Forwarded OAuth credential | Gemini Enterprise/auth flow | User-scoped downstream calls |
| Agent Platform service agent | Google-managed | This stack grants secret access | Platform operations |

## Developer identity

The agent repository `deploy_dev.py` and `update_dev.py` use ADC. Terraform can grant `developer_deployer_members` Agent Engine access, Parameter Manager read access and staging-bucket object access. Prefer a Google Group to repeated individual bindings.

The helpers do not change IAM when an operation is denied.

## Agent Identity

Every Agent Engine created with `identity_type=AGENT_IDENTITY` receives a distinct runtime identity. Developer permissions are not inherited by that identity.

This stack grants `agent_identity_project_roles` to the Agent Identity principal set covering all Agent Runtime agents in the project, rather than to named identities. An agent deployed later therefore inherits those roles with no Terraform change, which is what allows agents to be added to the monorepo independently of infrastructure.

Organization and orgless projects use different trust-domain prefixes; configure exactly one through the provided variables.

Common roles should be limited to runtime basics such as model/quota use and Parameter Manager reads. Sensitive data permissions should target an individual Agent Identity on the specific resource.

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

## Caller access

This stack does not grant Reasoning Engine invocation. Callers are granted on the specific runtime by whatever deploys it, because the resource does not exist until then.

Do not grant Terraform administration permissions to an Agent Identity, and do not reuse the Terraform runner service account as a runtime identity.

## Secrets

Agent Runtime application calls use Agent Identity, including reads from Secret Manager. This stack does not inject secrets into the runtime environment, so no deployment-time secret access is granted to the Agent Platform service agent.
