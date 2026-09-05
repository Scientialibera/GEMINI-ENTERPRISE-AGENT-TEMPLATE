# Developer workflows

This directory supports workstation execution and developer-owned Agent Engine instances in a development Google Cloud environment. It is not a QA or production deployment path.

Shared desired state, IAM, Parameter Manager, Secret Manager, observability and production deployment are owned by the Terraform branch.

## Authentication

Remote developer workflows use two local credential stores:

```bash
gcloud auth login
gcloud auth application-default login
```

The bootstrap uses the active `gcloud` account for discovery and optional sandbox resource creation. The Python SDK uses ADC for Agent Engine operations.

## Local workstation execution

Copy:

```bash
cp dev/.env.local.example dev/.env.local
```

Required values:

```text
GOOGLE_CLOUD_PROJECT
GOOGLE_CLOUD_LOCATION
GEMINI_MODEL
GEMINI_MODEL_LOCATION
AGENT_INSTRUCTION
LOG_LEVEL
```

`auth_reference_agent` additionally requires `GEMINI_ENTERPRISE_AUTHORIZATION_ID`. Its storage example requires `AGENT_IDENTITY_BUCKET_NAME` when that tool is exercised.

Run:

```bash
uv sync --all-packages --group dev
uv run --group dev python dev/run_local.py --agent basic_assistant
```

Local execution does not use Parameter Manager unless explicitly changed by the developer.

## Remote developer configuration

Copy:

```bash
cp dev/.env.dev.example dev/.env.dev
```

Required deployment coordinates:

```text
GOOGLE_CLOUD_PROJECT
GOOGLE_CLOUD_LOCATION
DEV_STAGING_BUCKET
ENVIRONMENT=dev
```

After the Terraform dev stack exists, also set:

```text
CONFIG_PARAMETER
CONFIG_PARAMETER_LOCATION
CONFIG_REFRESH_SECONDS
```

Use the exact Terraform output `runtime_config_parameter` for `CONFIG_PARAMETER`.

`auth_reference_agent` additionally requires `GEMINI_ENTERPRISE_AUTHORIZATION_ID` as bootstrap configuration because ADK constructs its authenticated tool during process startup.

## Initial sandbox preparation

Run:

```bash
uv run --group dev python dev/bootstrap_dev.py
```

This command can run before the Terraform workload stack. It prepares only the developer-sandbox layer:

- checks/reuses the GCP project
- optionally creates the project when explicitly enabled
- links billing when it creates a project
- checks required APIs and enables only missing APIs when allowed
- checks/reuses the staging bucket
- optionally creates the staging bucket

If `CONFIG_PARAMETER` is already configured, the command also verifies that the parameter exists and is readable. If it is not configured yet, the command finishes platform preparation and tells the developer to apply Terraform next.

### Optional creation controls

```text
DEV_CREATE_PROJECT_IF_MISSING=false
DEV_BILLING_ACCOUNT_ID=
DEV_PROJECT_FOLDER_ID=
DEV_PROJECT_ORGANIZATION_ID=
DEV_ENABLE_REQUIRED_APIS=true
DEV_CREATE_STAGING_BUCKET_IF_MISSING=true
DEV_STAGING_BUCKET_LOCATION=
```

Project creation is opt-in. When enabled, `DEV_BILLING_ACCOUNT_ID` is required. Set at most one of `DEV_PROJECT_FOLDER_ID` or `DEV_PROJECT_ORGANIZATION_ID`.

The current identity must already have any project-creation, billing-association, Service Usage and bucket-creation permissions required by the enabled operations. The helper consumes existing permissions; it does not grant them.

## Terraform handoff

After developer platform preparation, apply the Terraform dev stack. Terraform creates or manages:

- Parameter Manager runtime config
- developer IAM
- common runtime IAM for developer-created Agent Identities
- shared Agent Engine resources where applicable
- Secret Manager references
- observability

Then set `CONFIG_PARAMETER` in `dev/.env.dev` from Terraform output.

## Deploy and update

Create a developer-owned Agent Engine:

```bash
uv run --group dev python dev/deploy_dev.py --agent basic_assistant
```

or:

```bash
uv run --group dev python dev/deploy_dev.py --agent auth_reference_agent
```

The resource name is saved under `dev/.state/`.

Update source/bootstrap configuration on the same developer instance:

```bash
uv run --group dev python dev/update_dev.py --agent basic_assistant
```

Normal live config changes are made in Parameter Manager/Terraform and do not require this update helper.

## Guardrails

- Remote helpers refuse to run unless `ENVIRONMENT=dev`.
- Existing sandbox resources are reused.
- Project creation is disabled by default.
- Required placeholders fail before Agent Engine calls.
- No IAM self-assignment.
- No local creation of shared Parameter Manager desired state.
- No QA/prod deployment from these helpers.
- `.env.local`, `.env.dev` and `dev/.state/` are gitignored.
