# Gemini Enterprise Terraform template

Infrastructure template for the Google Cloud runtime used by the companion ADK agent repository.

This branch owns shared, agent-agnostic platform state: APIs, IAM, secrets and observability. It contains no agent prompts, tools or business logic, and it deploys no agents.

## Repository layout

```text
main.tf                     APIs, IAM, Secret Manager, Agent Identity roles
variables.tf                input contract with blocking validation
outputs.tf                  values the agent repository consumes
versions.tf                 Terraform and provider version constraints
terraform.tfvars.example    copy per environment; replace every placeholder

modules/
└── observability/          log bucket, retention, metrics, dashboard

CONFIGURATION.md            which setting lives where and how it changes
IDENTITY_AND_IAM.md         the principals involved and what each may do
```

## Scope

Terraform manages:

- required Google Cloud APIs
- Secret Manager resources
- developer deployment IAM
- baseline project-wide runtime IAM for every Agent Identity
- Cloud Logging retention and Log Analytics for all agent runtimes
- log-based metrics, dashboard and alerting

A separate foundation/bootstrap layer should manage project creation, billing association, Terraform remote state, GitHub OIDC, Workload Identity Federation and the Terraform execution service account.

## What Terraform deliberately does not manage

Terraform does not create Agent Engines, their runtime configuration, their Gemini Enterprise registration, or the Discovery Engine authorization used for delegated user consent.

The agent repository owns those resources through its deployment and registration helpers. Adding an agent is an entry in `AGENTS`; the new runtime automatically receives its own Agent Identity and inherits this stack's baseline principal-set IAM and observability without a Terraform change. Registration and the authorization are additionally unsuited to Terraform because the provider exposes no resource for either and the authorization requires an OAuth client secret that must not enter Terraform state.

Exact per-agent data access is also intentionally outside this shared stack because the Reasoning Engine ID does not exist until the agent is deployed. The companion agent repository can apply explicitly configured exact-Agent-Identity IAM after deployment when the caller already has IAM-administration permission on the target resource. Shared Terraform remains authoritative for baseline platform grants.

Each agent reads its own Parameter Manager parameter, named after its package. The agent repository creates and publishes that parameter, so config changes never require an infrastructure change.

## Before first apply

Confirm:

1. Terraform 1.11+ is installed.
2. The target GCP project already exists and has billing enabled.
3. The Terraform execution identity is already authorized.
4. A remote backend exists for shared environments.
5. `terraform.tfvars.example` was copied and every applicable placeholder was replaced.
6. Secret payloads are supplied outside `terraform.tfvars`.
7. Developer and baseline Agent Identity roles match the intended environment.

Validate and apply:

```bash
terraform fmt -check -recursive
terraform init
terraform validate
terraform plan -out=tfplan
terraform apply tfplan
```

This stack is applied once per project and then changes rarely. Deploying an agent does not require an apply.

## Configuration ownership

| Configuration | Authoritative source | Runtime delivery | Change behavior |
|---|---|---|---|
| Shared infrastructure and baseline IAM | Terraform | Google Cloud resources | Terraform apply |
| Exact per-agent workload IAM | Agent repository dev IAM helper / approved IAM process | IAM binding on the specific Agent Identity and resource | No Terraform apply |
| Live non-secret settings | Agent repository | Parameter Manager | No Agent Runtime revision |
| Process/bootstrap settings | Agent repository `dev/.env.dev` | Agent Engine env | New Agent Runtime revision possible |
| Secrets | Approved secret process + Terraform metadata | Secret Manager | Secret-specific behavior |

Shared infrastructure, baseline IAM and managed secret metadata belong to this stack. Runtime, bootstrap and exact-agent workload IAM live with the agent deployment lifecycle so adding an agent does not require a second platform Terraform apply.

Each agent reads its own parameter at `<parameter>/versions/latest` and refreshes on a cache interval, so a published configuration change takes effect without redeploying the runtime.

## Developer deployment IAM

The companion agent repository can create developer-owned Agent Engine instances. Those helpers use developer ADC and never grant IAM to themselves.

Terraform can grant configured developers/groups:

- `roles/aiplatform.user` by default for Agent Engine create/update
- Parameter Manager read access
- object write access to the existing developer staging bucket

The staging bucket may be created by the developer-sandbox bootstrap; this workload stack only grants access to the configured bucket.

If the same developer or automation identity also runs the per-agent IAM helper, it needs separate permission to update IAM on each configured target resource. Deployment permission alone does not imply IAM-administration permission.

## Developer-created Agent Identities

A developer-created Agent Engine receives a separate Agent Identity. Developer ADC permissions do not transfer to it.

This stack pre-authorizes every Agent Runtime Agent Identity in the project for common platform roles, using Google's project Agent Identity principal-set format. Because the grant targets the trust domain rather than a named identity, an agent deployed later inherits it with no Terraform change. That is what keeps the agent repository extensible.

Use an organization ID for organization projects, or `developer_agent_identity_orgless=true` for orgless projects. The default baseline covers Agent Platform use, Service Usage, Parameter Manager reads and project-wide Cloud Storage object reads, so the reference agents work on a fresh project without further configuration. Every role in that list reaches every current and future runtime, so add one only when that is intended; access to a particular bucket, dataset or secret belongs on the exact Agent Identity instead.

After a runtime exists, the agent repository can derive its exact Agent Identity principal from the project, location and Reasoning Engine ID. Explicitly configured per-agent roles can then be granted at the narrowest practical resource scope without a second platform Terraform apply. If no per-agent IAM is configured, the runtime still has its unique Agent Identity and only receives the baseline principal-set grants.

## Secret handling

`managed_secrets` describes Secret Manager objects owned by this stack. Payloads arrive through the sensitive, ephemeral `secret_values` variable and are referenced only by Secret Manager's write-only argument. Do not store payloads in `terraform.tfvars` or source control.

Terraform restricts ephemeral values to ephemeral/write-only contexts. Do not reuse `secret_values` in outputs, ordinary locals, validation/check expressions or non-write-only resource arguments.

Secrets are stored, never injected into the Agent Runtime. Runtime `secret_env` injection is unsupported for source-archive deployments: a Reasoning Engine that starts correctly is still reported as failed once `secret_env` is attached, with no application-level error. An agent that needs a secret reads it from Secret Manager at runtime using its own Agent Identity, which works on every deployment path and lets the value rotate without a new Agent Runtime revision.

Use `accessor_members` to grant read access to a principal that must read a payload itself, such as the release process that creates a Gemini Enterprise authorization from an OAuth client secret.

## Identities

Keep these principals separate:

1. Developer identity: local execution and developer-owned deployment.
2. Terraform execution identity: infrastructure changes; normally GitHub OIDC -> WIF -> dedicated Terraform service account.
3. Agent Identity: unique runtime identity for each deployed Agent Engine, covered by this stack's baseline principal-set roles and optionally exact per-agent workload grants.
4. Agent caller: user/group/workload allowed to query a Reasoning Engine.
5. Delegated end user: user-scoped OAuth token used by delegated tools.
6. Agent Platform service agent: Google-managed identity used for platform operations.

Do not reuse the Terraform execution service account as an Agent Identity.

## Agent source boundary

Terraform never sees agent source. The agent repository builds a deterministic `.tar.gz` with `dev/deploy/package_agent.py` and deploys it with `dev/deploy/deploy_dev.py`, which owns the entrypoint, requirements and bootstrap environment for that agent.

## Multi-agent safety

This stack is applied once per project and carries no per-agent runtime resources, so agents cannot collide in it. Observability is project-wide and groups by runtime id, which means a new agent appears in the existing dashboard and alert without configuration.

Agents that need more than the shared baseline roles should receive exact-Agent-Identity grants on the specific resource rather than widening the all-agent principal set. The companion dev IAM helper supports that pattern after the runtime exists.

For broader platform-wide resources such as WIF, Terraform runner IAM or remote state, use the foundation/bootstrap layer.

## Environment layout

For production use, prefer independent root configurations/state:

```text
environments/
├── dev/
├── qa/
└── prod/

modules/
└── observability/
```

The root files in this branch are a compact platform template. Split them into environment roots when adopting the template for a real platform repository.

## Change behavior

| Change | Terraform apply | New Agent Runtime revision |
|---|---:|---:|
| Agent runtime config (agent repository) | No | No |
| Agent bootstrap env (agent repository) | No | Yes/possible |
| Agent source archive (agent repository) | No | Yes |
| Adding an agent to the monorepo | No | n/a |
| Exact per-agent workload IAM after deploy | No | No |
| Shared baseline IAM, APIs, secrets, observability | Yes | No |

## Terraform standards

- Run `terraform fmt -check -recursive` and `terraform validate` before every plan.
- Pin provider versions and upgrade intentionally.
- Use typed variables and variable validation for single-variable constraints.
- Use blocking lifecycle preconditions for cross-variable deployment invariants; do not use warning-only `check` blocks for conditions that must prevent apply.
- Keep repeated derived values in `locals`; do not duplicate resource-name or configuration formulas.
- Use `for_each` for repeatable IAM/config resources rather than copied blocks.
- Prefer resource-level IAM for sensitive data access.
- Do not use `Owner`/`Editor` as convenience roles in the template.
- Keep ephemeral secret values exclusively in supported write-only/ephemeral contexts.
- Do not put secret payloads in Git, tfvars, plan output or normal state.
- Do not bootstrap the permissions of the Terraform identity from the workload stack it is already executing.
- Do not let a live-config-only change accidentally modify Agent Engine deployment fields.

## Repository rules

- Shared project/bootstrap resources belong to the foundation layer.
- Git/Terraform is authoritative for shared desired state.
- Parameter Manager is not an independent config authoring surface for QA/prod.
- No secret payloads in source control or `terraform.tfvars`.
- No long-lived service-account keys.
- No application business logic in this branch.
- No production changes through developer helper scripts.
- Keep provider versions pinned and upgrade intentionally after validation.
