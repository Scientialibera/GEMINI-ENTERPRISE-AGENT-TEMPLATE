# Developer workflows

This directory supports workstation execution and developer-owned Agent Engine instances in a development Google Cloud environment. It is not a QA or production deployment path.

Shared desired state, IAM, Parameter Manager, Secret Manager, observability and production deployment are owned by the `template/terraform-iac-only` branch. Optional developer test fixtures, including the BigQuery sample dataset, remain local to this branch.

| Script | Purpose |
|---|---|
| `common.py` | Agent registry (`AGENTS`), requirements, bootstrap env contract |
| `bootstrap.py` / `bootstrap_dev.py` | Idempotent project, API, bucket and parameter preflight |
| `bigquery_fixture.py` | Optional sample dataset for the delegated BigQuery tool |
| `run_local.py` | Run one agent on the workstation |
| `package_agent.py` | Deterministic archive: one agent plus `gemini_shared` |
| `deploy_dev.py` / `update_dev.py` | Create or update a developer-owned Agent Engine |
| `register_agent.py` | Publish that runtime into a Gemini Enterprise app |
| `release_dev.py` | Package, deploy and register in one command |

Adding an agent to `AGENTS` in `common.py` is what makes it visible to every script above.

## Authentication

Remote developer workflows use two local credential stores:

```bash
gcloud auth login
gcloud auth application-default login
```

The bootstrap uses the active `gcloud` account for discovery and optional sandbox resource creation. Python Google Cloud clients use ADC.

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

The delegated BigQuery tool cannot be fully exercised through a direct local ADK call because it expects the OAuth token forwarded by Gemini Enterprise. The BigQuery fixture created by `bootstrap_dev.py` still provides a concrete dataset/table that can be inspected with ADC during local debugging and queried later through the deployed delegated-auth path.

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

This command can run before the Terraform workload stack. It prepares only the developer-sandbox/test layer:

- checks/reuses the GCP project
- optionally creates the project when explicitly enabled
- links billing when it creates a project
- checks required APIs and enables only missing APIs when allowed
- checks/reuses the staging bucket
- optionally creates the staging bucket
- optionally creates/reuses a small BigQuery test dataset and table
- seeds deterministic BigQuery sample rows only when the fixture table is empty

If `CONFIG_PARAMETER` is already configured, the command also verifies that the parameter exists and is readable. If it is not configured yet, the command finishes platform/test preparation and tells the developer to apply Terraform next.

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

## BigQuery end-to-end test fixture

A fresh project has no BigQuery data, so the delegated tool cannot be tested end to end even when the wiring is correct. A small fixture is enabled by default:

```text
DEV_PREPARE_BIGQUERY_FIXTURE=true
DEV_CREATE_BIGQUERY_FIXTURE_IF_MISSING=true
DEV_BIGQUERY_DATASET_ID=gemini_agent_template_dev
DEV_BIGQUERY_TABLE_ID=sample_orders
DEV_BIGQUERY_LOCATION=
```

When enabled, the bootstrap:

1. ensures the BigQuery API is enabled with the other dev APIs;
2. reuses the configured dataset when it exists;
3. creates it only when missing and creation is enabled;
4. reuses and validates the configured table when it exists;
5. creates the table when missing and creation is enabled;
6. inserts five deterministic sample order rows only when the table is empty.

Repeated runs do not append duplicate fixture rows. Existing non-empty tables are left unchanged. If an existing table has the same configured name but a different schema, bootstrap stops rather than modifying it.

If the development project already has BigQuery data that the Gemini Enterprise test user can query, disable the fixture:

```text
DEV_PREPARE_BIGQUERY_FIXTURE=false
```

Nothing points at the sample table. `auth_reference_agent` lists the datasets visible to the delegated user before querying, so real data works too.

The helper grants no IAM. Two identities need permissions already:

- developer ADC: BigQuery permissions to create the fixture
- signed-in Gemini Enterprise user: create query jobs and read the dataset

These are often granted separately. Fix gaps in IAM, never with self-grant logic in the helper.

Developer test support only. Terraform does not create or seed it.

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

## Register in Gemini Enterprise

A deployed Agent Engine is not visible in Gemini Enterprise until it is registered:

```bash
uv run --group dev python dev/register_agent.py --agent basic_assistant
```

Requires `GEMINI_ENTERPRISE_APP_ID`, the app/engine id rather than the web app client id shown in the console URL. Re-running patches the existing agent instead of creating a duplicate.

Agents with delegated tools also need a Gemini Enterprise authorization. The helper reuses `GEMINI_ENTERPRISE_AUTHORIZATION_ID` when it already exists, and creates it when `GEMINI_ENTERPRISE_OAUTH_CLIENT_ID` and `GEMINI_ENTERPRISE_OAUTH_CLIENT_SECRET` are supplied for that run. One authorization serves one agent.

## Guardrails

- Remote helpers refuse to run unless `ENVIRONMENT=dev`.
- Existing sandbox resources are reused.
- Project creation is disabled by default.
- Required placeholders fail before Agent Engine calls.
- No IAM self-assignment.
- No local creation of shared Parameter Manager desired state.
- BigQuery fixture creation is optional and bounded to the configured dev dataset/table.
- No QA/prod deployment from these helpers.
- `.env.local`, `.env.dev` and `dev/.state/` are gitignored.
