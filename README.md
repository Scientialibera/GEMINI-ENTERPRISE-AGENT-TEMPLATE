# Gemini Enterprise ADK agent template

Application template for independently deployable Google ADK agents that share a common Python runtime package.

This branch contains agent code, shared application libraries, tests, deterministic packaging and developer-only local/dev deployment helpers. Shared Google Cloud infrastructure, IAM, Parameter Manager, Secret Manager, observability and production deployment belong to the companion Terraform branch.

## Repository layout

```text
agents/
├── auth_reference_agent/
└── basic_assistant/

packages/
└── gemini_shared/

dev/
├── .env.local.example
├── .env.dev.example
├── bigquery_fixture.py
├── bootstrap.py
├── bootstrap_dev.py
├── common.py
├── package_agent.py
├── run_local.py
├── deploy_dev.py
├── update_dev.py
├── register_agent.py
└── release_dev.py

tests/
pyproject.toml
```

Each folder under `agents/` is an independently deployable ADK application. Shared runtime behavior belongs in `packages/gemini_shared`. Agent-specific tools and orchestration stay inside the agent package.

Tool schemas are code. ADK derives the function declaration sent to the model from each tool's signature, type hints and docstring, so a tool without a docstring is advertised to the model with no description.

Instruction text is not code. Both agents resolve `instruction` through a callable that reads the live runtime configuration per request, so the prompt is authored in the Terraform `runtime_config` desired state, delivered through Parameter Manager, and supplied locally by `AGENT_INSTRUCTION`. No agent package contains a prompt literal.

## Before first use

Install Python 3.12+, `uv` and the Google Cloud CLI.

For local Google Cloud access:

```bash
gcloud auth application-default login
```

For remote developer deployment configure both CLI authentication and ADC:

```bash
gcloud auth login
gcloud auth application-default login
```

Install and validate the workspace:

```bash
uv sync --all-packages --group dev
uv run --group dev ruff format --check .
uv run --group dev ruff check .
uv run --group dev pytest
```

`ruff` enforces Python 3.12 syntax, PEP 8 conventions, import ordering, bug-prone constructs and security-oriented static checks. Tests use strict marker handling. These checks are part of the template contract; do not rely on README guidance alone.

## Configuration model

The template separates configuration by runtime behavior.

| Configuration | Runtime source | Change behavior |
|---|---|---|
| Live non-secret application config | Parameter Manager | Existing agent refreshes after TTL; no Agent Runtime revision |
| Bootstrap/process-construction config | Agent Engine environment | Change can create a new Agent Runtime revision |
| Secrets | Secret Manager | Secret-specific rotation/deployment behavior |
| Local developer config | `dev/.env.local` / `dev/.env.dev` | Workstation/developer sandbox only |

Live configuration includes values such as model name, instruction, log level, query/result limits, MCP endpoint and runtime resource identifiers. It is validated by `gemini_shared.RuntimeConfig`.

The deployed agent reads the Parameter Manager resource identified by `CONFIG_PARAMETER` and resolves `versions/latest`. `CONFIG_REFRESH_SECONDS` controls the cache TTL. If a refresh fails after at least one successful load, the agent continues with the last-known-good configuration and retries later.

`before_model_callback` resolves the current model before each LLM request, subject to the configuration cache TTL. A model-name change therefore does not require a source deployment.

Do not duplicate live settings in Agent Engine bootstrap environment variables.

## Bootstrap environment

Remote deployments pass only the small bootstrap contract:

```text
CONFIG_PARAMETER
CONFIG_PARAMETER_LOCATION
CONFIG_REFRESH_SECONDS
BOOTSTRAP_MODEL
GEMINI_MODEL_LOCATION
GEMINI_ENTERPRISE_AUTHORIZATION_ID   # auth_reference_agent only
```

`GOOGLE_CLOUD_PROJECT` and `GOOGLE_CLOUD_LOCATION` are used locally and are supplied by Agent Runtime when deployed. Do not add reserved Agent Runtime variables to the deployed env map.

## Local execution

Copy the local example:

```bash
cp dev/.env.local.example dev/.env.local
```

Fill the required values, then run:

```bash
uv run --group dev python dev/run_local.py --agent basic_assistant
```

or:

```bash
uv run --group dev python dev/run_local.py --agent auth_reference_agent
```

Local execution intentionally omits `CONFIG_PARAMETER`; the shared runtime reads live values directly from the local process environment.

The delegated BigQuery tool itself requires a delegated Gemini Enterprise user token, so a direct local ADK invocation cannot fully reproduce that authorization path. The optional BigQuery fixture described below is created from the developer workstation with ADC and provides a real dataset/table for debugging and for the final deployed Gemini Enterprise end-to-end test.

## First remote developer deployment

Copy the remote example:

```bash
cp dev/.env.dev.example dev/.env.dev
```

The initial sequence is:

```text
1. configure gcloud + ADC
2. fill dev/.env.dev deployment coordinates
3. run bootstrap_dev.py
4. bootstrap reuses or prepares the developer project/APIs/staging bucket
5. bootstrap optionally creates/reuses the BigQuery test fixture
6. package the selected agent
7. apply the companion Terraform dev stack where a shared Terraform-managed runtime is required
8. copy Terraform output runtime_config_parameter into dev/.env.dev
9. run tests/lint
10. run deploy_dev.py for a developer-owned Agent Engine copy
11. run register_agent.py to publish that runtime into a Gemini Enterprise app
```

`release_dev.py --agent <name>` runs steps 6, 10 and 11 in one command.

Deploying an Agent Engine does not make it visible in Gemini Enterprise. Step 11 is what puts it on the Agents page and enables the delegated consent flow.

Run the developer platform preflight:

```bash
uv run --group dev python dev/bootstrap_dev.py
```

The preflight is idempotent.

| Resource | Existing | Missing |
|---|---|---|
| GCP project | Reuse | Stop by default; create only when `DEV_CREATE_PROJECT_IF_MISSING=true` |
| Billing | Leave unchanged | Required only when the helper creates a project |
| Required APIs | Reuse enabled APIs | Enable only missing APIs when allowed |
| Dev staging bucket | Reuse | Create when `DEV_CREATE_STAGING_BUCKET_IF_MISSING=true` |
| Optional BigQuery test fixture | Reuse and validate | Create/seed when enabled; otherwise skip/fail according to fixture flags |
| Parameter Manager runtime config | Verify when configured | Stop at deploy time and require Terraform |
| IAM | Use existing grants | Never self-grant; fix through the appropriate platform/IAM process |

Project creation is disabled by default because it affects organization placement, quota and billing.

## Optional BigQuery developer fixture

`auth_reference_agent` includes a delegated BigQuery tool. A clean project may not contain any queryable data, which makes it difficult to verify the complete delegated-auth flow. The developer bootstrap therefore includes a small optional BigQuery fixture.

Default behavior:

```text
DEV_PREPARE_BIGQUERY_FIXTURE=true
DEV_CREATE_BIGQUERY_FIXTURE_IF_MISSING=true
DEV_BIGQUERY_DATASET_ID=gemini_agent_template_dev
DEV_BIGQUERY_TABLE_ID=sample_orders
DEV_BIGQUERY_LOCATION=
```

On a fresh sandbox, `bootstrap_dev.py` enables the BigQuery API, creates the dataset/table when missing and inserts five deterministic sample order rows only when the table is empty. Existing non-empty fixture tables are not modified.

The fixture is not an application dependency and is not production infrastructure. If the project already contains BigQuery data that the signed-in Gemini Enterprise test user can query, set:

```text
DEV_PREPARE_BIGQUERY_FIXTURE=false
```

The agent does not hardcode the fixture dataset or table. Its BigQuery discovery flow lists the datasets/tables visible to the delegated user, so an existing real development dataset can be used instead.

The fixture helper does not grant BigQuery IAM. The identity running `bootstrap_dev.py` must already be allowed to create/read the fixture resources when creation is enabled. To exercise the deployed delegated tool, the signed-in Gemini Enterprise user must independently have permission to create BigQuery query jobs and read the target dataset/table. If those permissions are missing, fix IAM outside the application helper rather than adding self-grant logic.

Terraform intentionally does not create or seed this sample dataset. The fixture belongs to developer test support in this branch.

## Deterministic application packaging

Build the artifact consumed by Terraform with:

```bash
uv run --group dev python dev/package_agent.py --agent basic_assistant
```

or:

```bash
uv run --group dev python dev/package_agent.py --agent auth_reference_agent
```

The default output is `artifacts/<agent_name>.tar.gz`, which is gitignored. The packager normalizes archive timestamps and ownership metadata and writes a deterministic `requirements.txt`. Rebuilding unchanged source produces the same archive bytes.

The archive contains only the selected agent package and `gemini_shared`; unrelated agents are not bundled into the deployment.

## Developer-owned Agent Engine deployment

After Terraform has created the runtime parameter and IAM, deploy:

```bash
uv run --group dev python dev/deploy_dev.py --agent basic_assistant
```

The resulting Reasoning Engine resource is stored under ignored `dev/.state/`.

Update the same developer-owned instance after code or bootstrap changes:

```bash
uv run --group dev python dev/update_dev.py --agent basic_assistant
```

Do not run `update_dev.py` for normal Parameter Manager changes. The already-running agent reads those changes automatically after the refresh TTL.

## Gemini Enterprise registration

Deployment and registration are separate. `deploy_dev.py` creates the Agent Engine; the agent only appears in a Gemini Enterprise app after it is registered:

```bash
uv run --group dev python dev/register_agent.py --agent basic_assistant
```

Set `GEMINI_ENTERPRISE_APP_ID` in `dev/.env.dev` to the app (engine) id. This is not the web app client id shown in the console URL.

Registration is idempotent. An agent with the same display name is patched to point at the current Reasoning Engine rather than duplicated.

Each agent's registration metadata — description, invocation description and starter prompts — lives in its `AgentSpec` in `dev/common.py`, so the registered listing stays in the repository rather than being maintained by hand in the console.

Agents with delegated tools additionally need a Gemini Enterprise authorization, which triggers the user consent flow and forwards the resulting token to the agent. `register_agent.py` reuses `GEMINI_ENTERPRISE_AUTHORIZATION_ID` when it already exists, and creates it otherwise. Set `GEMINI_ENTERPRISE_OAUTH_CLIENT_SECRET_NAME` to a Secret Manager secret so the payload never reaches a workstation; `GEMINI_ENTERPRISE_OAUTH_CLIENT_SECRET` remains available for a sandbox with no managed secret yet.

One authorization serves one agent. Registering a second agent against an authorization already bound elsewhere fails with `is used by another agent`; create a separate authorization id for each agent that needs delegated access.

## Identity model

Developer helpers authenticate with the developer's ADC identity. They do not create or modify IAM.

The companion Terraform stack should grant the developer/group the required Agent Engine deployment access, Parameter Manager read access when needed and object access to the developer staging bucket.

A developer-created Agent Engine receives a separate Agent Identity. The developer's permissions do not transfer to that runtime identity. The Terraform branch therefore supports pre-authorizing the project Agent Identity principal set for common non-sensitive runtime roles such as Parameter Manager access. Sensitive data access should remain specific to the individual agent.

Delegated BigQuery access is different: the BigQuery tool executes with the signed-in Gemini Enterprise user's forwarded OAuth token. BigQuery permissions for that user remain user-scoped and are not inherited from the Agent Identity.

## Authentication reference agent

`auth_reference_agent` preserves the two authentication patterns from the clean single-agent template:

1. Agent Identity for backend access under the runtime's own identity.
2. Gemini Enterprise delegated authentication using the OAuth token forwarded in session state.

The delegated-auth scheme, provider and registration live in `gemini_shared.delegated_auth`, so every agent shares one implementation.

A deployed scheme arrives as a base `CustomAuthScheme` and ADK rehydrates it by matching `type_` against `CustomAuthScheme.__subclasses__()`. The subclass therefore has to exist by the time a tool runs, which means the defining module must already be imported. Importing anything from `gemini_shared` satisfies that.

The failure mode is an unimported module, not a shared one:

```text
No auth provider registered for custom auth scheme
```

A new scheme must set a `type_` default, since rehydration matches on that value.

## Adding an agent

1. Create `agents/<agent_name>/` with its own Python package.
2. Give the ADK root agent a unique name.
3. Keep domain tools and orchestration in that agent package, and give every tool a docstring. Resolve the instruction from runtime configuration rather than hardcoding prompt text.
4. Move only genuinely shared runtime behavior into `gemini_shared`.
5. Add an `AgentSpec` entry in `dev/common.py` if the local/dev helpers should support the new agent.
6. Add live settings to the Terraform-managed Parameter Manager payload.
7. Add only process-construction values to bootstrap env.
8. Add required runtime IAM and secrets in Terraform.
9. Extend tests for agent-specific validation and packaging behavior.

## Code standards

- Python 3.12 and PEP 8 conventions.
- Constants and repeated configuration keys are declared at module scope rather than embedded throughout logic.
- Public/shared functions use type hints; dataclasses use immutable/slotted forms where appropriate.
- Subprocesses use argument arrays, no shell execution and a resolved executable path.
- Filesystem writes are limited to explicit ignored state/artifact locations or secure temporary directories.
- External inputs and environment values fail fast with actionable errors.
- Shared logic belongs in `gemini_shared` or `dev/common.py`; agent domain logic remains local to the agent.
- No production control flow depends on `assert` statements.
- No credentials, secrets or raw delegated tokens are logged.

## Repository rules

- No production/shared IAM mutation from application code.
- No Terraform state or shared infrastructure definitions in this branch.
- No committed `.env` files, credentials or secret payloads.
- No long-lived service-account keys.
- No duplicated shared configuration between `.env`, Parameter Manager and Terraform.
- No QA/prod deployment through developer helper scripts.
- No accidental extraction of the custom delegated-auth provider into shared code.
- Developer test fixtures must remain optional, bounded and separate from production/shared infrastructure.
