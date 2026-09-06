# Gemini Enterprise Terraform template

Infrastructure template for the Google Cloud runtime used by the companion ADK agent repository.

This branch owns shared infrastructure, IAM, configuration delivery, secrets, observability and Terraform-managed Agent Engine deployment. It contains no agent prompts, tools or business logic.

## Scope

Terraform manages:

- required Google Cloud APIs
- Agent Engine / Reasoning Engine
- Agent Identity
- Parameter Manager live configuration
- Secret Manager resources
- developer deployment IAM
- common IAM for developer-created Agent Identities
- caller access
- Terraform-managed Agent Identity permissions
- Cloud Logging retention and Log Analytics
- log-based metrics, dashboard and alerting

A separate foundation/bootstrap layer should manage project creation, billing association, Terraform remote state, GitHub OIDC, Workload Identity Federation and the Terraform execution service account.

Terraform does not manage Gemini Enterprise agent registration or the Discovery Engine authorization used for delegated user consent. Both are application-release concerns tied to a specific Reasoning Engine, the Google provider exposes no resource for either, and the authorization requires an OAuth client secret that must not enter Terraform state. The agent repository owns them through `dev/register_agent.py`.

## Before first apply

Confirm:

1. Terraform 1.11+ is installed.
2. The target GCP project already exists and has billing enabled.
3. The Terraform execution identity is already authorized.
4. A remote backend exists for shared environments.
5. The agent repository produced the archive referenced by `source_archive_path`.
6. `terraform.tfvars.example` was copied and every applicable placeholder was replaced.
7. Secret payloads are supplied outside `terraform.tfvars`.
8. Developer, caller and Agent Identity roles match the intended environment.

Set the config publish revision:

```bash
export TF_VAR_config_revision="$(git rev-parse --short=12 HEAD)"
```

Validate and apply:

```bash
terraform fmt -check -recursive
terraform init
terraform validate
terraform plan -out=tfplan
terraform apply tfplan
```

Do not apply a plan that contains unexpected Agent Engine source/bootstrap changes when the intended change is runtime configuration only.

## Configuration ownership

| Configuration | Authoritative source | Runtime delivery | Change behavior |
|---|---|---|---|
| Infrastructure and IAM | Terraform | Google Cloud resources | Terraform apply |
| Live non-secret settings | Terraform `runtime_config` | Parameter Manager | No Agent Runtime revision |
| Process/bootstrap settings | Terraform `bootstrap_env` | Agent Engine env | New Agent Runtime revision possible |
| Secrets | Approved secret process + Terraform metadata | Secret Manager | Secret-specific behavior |

`runtime_config` is published as JSON. Terraform injects `config_revision`, computes a content hash and creates an immutable Parameter Manager version named from both values.

The agent reads `<parameter>/versions/latest` and refreshes after `config_refresh_seconds`. Changing only `runtime_config` does not modify Agent Engine source or deployment environment.

Git/Terraform is the desired-state source of truth. Parameter Manager is the runtime delivery store. A direct UI version may be used for dev experimentation; retained values must be reconciled into Terraform.

## Bootstrap environment

Keep `bootstrap_env` small. Typical values are:

```text
BOOTSTRAP_MODEL
GEMINI_MODEL_LOCATION
GEMINI_ENTERPRISE_AUTHORIZATION_ID   # auth_reference_agent only
```

Terraform automatically adds:

```text
CONFIG_PARAMETER
CONFIG_PARAMETER_LOCATION
CONFIG_REFRESH_SECONDS
GOOGLE_CLOUD_AGENT_ENGINE_ENABLE_TELEMETRY
OTEL_SEMCONV_STABILITY_OPT_IN
```

Do not set Agent Runtime-reserved values such as `GOOGLE_CLOUD_PROJECT` or `GOOGLE_CLOUD_LOCATION`.

## Parameter Manager lifecycle

Parameter values are immutable. Each approved config publish creates a new version. Previous versions use `deletion_policy = "ABANDON"`, so they remain in Parameter Manager for history after Terraform stops managing the previous current version.

Rollback is a new reviewed Git/Terraform change that republishes the prior desired values under a new version. Do not make production rollback depend on manually repointing to an unmanaged old version.

Retaining those versions is deliberate, and it means `terraform destroy` cannot delete the parameter while abandoned versions still exist:

```text
Error: Resource '...parameters/<id>' has nested resources.
```

Tearing an environment down completely therefore requires deleting the abandoned versions first:

```bash
gcloud parametermanager parameters versions list <parameter-id> --location=global
gcloud parametermanager parameters versions delete <version-id> \
  --parameter=<parameter-id> --location=global
```

## Developer deployment IAM

The companion agent repository can create developer-owned Agent Engine instances. Those helpers use developer ADC and never grant IAM to themselves.

Terraform can grant configured developers/groups:

- `roles/aiplatform.user` by default for Agent Engine create/update
- Parameter Manager read access
- object write access to the existing developer staging bucket

The staging bucket may be created by the developer-sandbox bootstrap; this workload stack only grants access to the configured bucket.

## Developer-created Agent Identities

A developer-created Agent Engine receives a separate Agent Identity. Developer ADC permissions do not transfer to it.

This stack can pre-authorize all Agent Runtime Agent Identities in the dev project for common non-sensitive roles using Google's project Agent Identity principal-set format. The Terraform-managed Agent Engine is created first so the Agent Identity trust domain is initialized before the common principal-set bindings are applied.

Use an organization ID for organization projects, or `developer_agent_identity_orgless=true` for orgless projects. Do not grant sensitive datasets, buckets or production data through the all-agent principal set; grant those to the specific Agent Identity that requires them.

## Secret handling

`managed_secrets` describes Secret Manager objects owned by this stack. Payloads arrive through the sensitive, ephemeral `secret_values` variable and are referenced only by Secret Manager's write-only argument. Do not store payloads in `terraform.tfvars` or source control.

Terraform restricts ephemeral values to ephemeral/write-only contexts. Do not reuse `secret_values` in outputs, ordinary locals, validation/check expressions or non-write-only resource arguments.

Secrets are stored, never injected into the Agent Runtime. Runtime `secret_env` injection is unsupported for source-archive deployments: a Reasoning Engine that starts correctly is still reported as failed once `secret_env` is attached, with no application-level error. An agent that needs a secret reads it from Secret Manager at runtime using its own Agent Identity, which works on every deployment path and lets the value rotate without a new Agent Runtime revision.

Use `accessor_members` to grant read access to a principal that must read a payload itself, such as the release process that creates a Gemini Enterprise authorization from an OAuth client secret.

## Identities

Keep these principals separate:

1. Developer identity: local execution and developer-owned dev deployment.
2. Terraform execution identity: infrastructure changes; normally GitHub OIDC -> WIF -> dedicated Terraform service account.
3. Terraform-managed Agent Identity: runtime access for the shared Reasoning Engine.
4. Developer-created Agent Identity: runtime identity for each developer Agent Engine copy.
5. Agent caller: user/group/workload allowed to query the Reasoning Engine.
6. Delegated end user: user-scoped OAuth token used by delegated tools.
7. Agent Platform service agent: Google-managed identity used for platform operations.

Do not reuse the Terraform execution service account as an Agent Identity.

## Agent source boundary

Terraform consumes a deterministic `.tar.gz` from the application repository:

```hcl
source_archive_path = "./artifacts/example-agent.tar.gz"
entrypoint_module   = "auth_reference_agent.agent"
entrypoint_object   = "app"
requirements_file   = "requirements.txt"
```

Build the archive with the companion agent repository's `dev/package_agent.py`. Application packaging is not implemented in Terraform.

## Multi-agent safety

This root template deploys one Agent Engine workload. A production IaC repository may instantiate the module once per independently deployable agent or use separate environment/workload roots.

Generated shared-project resource names must not collide across agents. The template therefore:

- derives a deterministic custom invoker-role ID from project, region and agent display name when `invoker_role` is not supplied;
- derives a deterministic per-agent Logging bucket ID when `log_bucket_id` is null;
- requires callers to provide a unique `config_parameter_id` for each independently managed runtime config.

For broader platform-wide resources such as WIF, Terraform runner IAM or remote state, use the foundation/bootstrap layer rather than duplicating them per agent.

## Environment layout

For production use, prefer independent root configurations/state:

```text
environments/
├── dev/
├── qa/
└── prod/

modules/
├── agent_engine/
└── observability/
```

The root files in this branch are a compact workload template. Split them into environment roots when adopting the template for a real platform repository.

## Change behavior

| Change | New Parameter version | New Agent Runtime revision |
|---|---:|---:|
| `runtime_config` | Yes | No |
| `bootstrap_env` | No | Yes/possible |
| source archive | No | Yes |
| IAM only | No | No unless deployment config also changes |
| Parameter Manager UI version in dev | Yes | No |

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
