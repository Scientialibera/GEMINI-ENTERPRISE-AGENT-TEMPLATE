# Gemini Enterprise ADK agent template

Application template for independently deployable Google ADK agents that share a common Python runtime package.

This branch contains agent code, shared application libraries, tests, deterministic packaging and the developer helpers that deploy and register agents. Shared Google Cloud infrastructure — APIs, IAM, Secret Manager and observability — belongs to the `template/terraform-iac-only` branch, which is applied once per project before any agent is deployed. See [What Terraform owns](#what-terraform-owns).

Start with [Which script to run](#which-script-to-run), then [Adding an agent](#adding-an-agent) for the full recipe: files, tools, MCP servers, identity, deployment.

## Which script to run

Three workflows. Only the second needs Terraform, and only the third touches Gemini Enterprise.

**Working on an agent locally** — no cloud deployment, no Terraform:

```bash
uv run --group dev python dev/run_local.py --agent <agent>
```

Reads `dev/.env.local`, runs the agent in-process against real Google Cloud APIs using your own credentials. Delegated tools cannot be fully exercised this way, because there is no Gemini Enterprise session to forward a user token.

**Preparing a project** — once, before the first deployment:

```bash
terraform apply                                        # the other branch: APIs, IAM, observability
uv run --group dev python dev/bootstrap_dev.py         # project, staging bucket, optional fixture
```

**Deploying an agent** — whenever its code or configuration changes:

```bash
uv run --group dev python dev/release_dev.py --agent <agent>
```

That runs preflight → package → deploy → register, and updates the existing Agent Engine rather than creating a second one when the agent has been deployed before. `--skip-register` stops after deployment.

Run the steps separately when you want just one:

| Step | Script | Creates |
|---|---|---|
| package | `package_agent.py` | the deterministic `.tar.gz` |
| deploy | `deploy_dev.py` | a new Agent Engine, and the agent's runtime parameter |
| update | `update_dev.py` | replaces the code in an Agent Engine that already exists |
| register | `register_agent.py` | the authorization and the Gemini Enterprise agent |

`deploy_dev.py` creates a new Agent Engine every time it runs, so use `update_dev.py` to change one that already exists. Deploying alone does not make an agent visible in Gemini Enterprise — registration does.

## Repository layout

```text
agents/                     one independently deployable ADK application each
├── auth_reference_agent/   reference for both authentication patterns
│   └── src/auth_reference_agent/
│       ├── agent.py        agent construction only
│       ├── config.py       bootstrap values resolved once at import
│       └── tools/          one module per tool
│           ├── bigquery_query.py        BigQuery as the signed-in user
│           ├── storage_objects.py       Cloud Storage as the agent
│           └── runtime_config_status.py active runtime configuration
├── bigquery_mcp_agent/     tools served by a remote MCP server, not written here
│   └── src/bigquery_mcp_agent/
│       ├── agent.py
│       ├── config.py
│       └── tools/
│           ├── bigquery_mcp.py          BigQuery via Google's managed server
│           └── runtime_config_status.py
└── basic_assistant/        minimal agent; the shape to copy for a new one
    └── src/basic_assistant/
        ├── agent.py
        ├── config.py
        └── tools/

packages/
└── gemini_shared/          runtime behaviour every agent shares, by concern
    ├── auth/               which identity a call is made with
    │   ├── delegated.py    Gemini Enterprise delegated user token
    │   └── tokens.py       read an access token out of a credential
    ├── config/             what the agent is configured to do
    │   ├── bootstrap.py    the small env contract read at process start
    │   ├── runtime_config.py  live config from Parameter Manager, local fallback
    │   └── runtime_agent.py   per-request instruction and model resolution
    ├── connectors/         clients for Google Cloud services
    │   └── cloud_storage.py   Cloud Storage under the runtime's own identity
    └── mcp/                remote MCP servers over Streamable HTTP
        ├── mcp_auth/       how to authenticate to any MCP server
        │   ├── toolset.py  build a toolset from a server URL
        │   └── headers.py  send the signed-in user's token to that server
        └── mcp_google_cloud/  one folder per server; add mcp_<name> beside it
            ├── servers.py     Google's endpoints, scopes and tool lists
            └── toolsets.py    ready-made toolsets for those servers

dev/                        developer tooling; never deployed with an agent
├── .env.local.example      local execution settings
├── .env.dev.example        developer sandbox deployment settings
│
│   run these:
├── run_local.py            run an agent on this workstation
├── bootstrap_dev.py        prepare the project once: APIs, bucket, fixture
├── package_agent.py        build the deterministic archive
├── deploy_dev.py           create the Agent Engine and its runtime parameter
├── update_dev.py           update that same Agent Engine in place
├── register_agent.py       publish it into a Gemini Enterprise app
├── release_dev.py          package, deploy and register in one command
│
│   imported by the above, never run directly:
├── common.py               agent registry and shared helpers
├── bootstrap.py            project, API, bucket and parameter preflight
└── bigquery_fixture.py     optional sample data for the delegated tool

tests/                      lint and behaviour checks for the above
pyproject.toml              workspace, dependencies and lint configuration
```

Each folder under `agents/` deploys on its own. Inside one: `agent.py` constructs, `config.py` resolves bootstrap values once, one module per tool under `tools/`. Shared behavior goes in `packages/gemini_shared`; domain logic stays in the agent.

Two rules follow from how ADK works:

- **Tool schemas are code.** ADK builds the declaration from the signature, type hints and docstring. No docstring, no description.
- **Prompts are not code.** `instruction` is a callable reading live config per request. Authored in the agent's Parameter Manager parameter, delivered from there, set locally by `AGENT_INSTRUCTION`. No agent package holds prompt text.

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

`ruff` enforces Python 3.12 syntax, PEP 8, import order, bug-prone constructs and security checks. These run in CI and are the contract; this README is not.

## What Terraform owns

Two repositories, and the split is what keeps agents independent of infrastructure.

| | Terraform (`template/terraform-iac-only`) | Agent repository (`dev/`) |
|---|---|---|
| Runs | once per project, then rarely | once per agent, whenever it changes |
| Creates | APIs, IAM, Secret Manager, observability | Agent Engines, runtime parameters, authorizations, registrations |
| Knows about agents | nothing | everything |

**Terraform runs first**, because it grants the IAM everything else depends on: the developer's permission to deploy, and the project-wide roles every Agent Identity inherits. That grant targets a trust-domain principal set rather than named identities, so an agent deployed later picks it up with no apply.

**Terraform creates no Agent Engines.** It has no agent names, no source archives, no per-agent configuration. Adding an agent to this repository therefore never touches Terraform, and observability is project-wide and grouped by runtime id, so a new agent appears in the existing dashboard and alerts on its own.

Everything an agent needs beyond that is created by the dev scripts at deploy time, including its Parameter Manager configuration and its Gemini Enterprise authorization. The only exception is its OAuth client, which no API can create.

## Configuration model

Where a value lives decides what changing it costs.

| Configuration | Source | Cost of a change |
|---|---|---|
| Live app config | Parameter Manager | Picked up after the TTL. No redeploy |
| Bootstrap config | Agent Engine env | Redeploy; can create a new revision |
| Secrets | Secret Manager | Per-secret rotation |
| Local dev config | `dev/.env.local`, `dev/.env.dev` | Workstation only |

Live config covers model, instruction, log level and query limits, validated by `gemini_shared.RuntimeConfig`. The MCP server URL is bootstrap, not live: the toolset is built at construction.

The agent reads `CONFIG_PARAMETER` at `versions/latest`, cached for `CONFIG_REFRESH_SECONDS`. After one successful load, a failed refresh keeps the last-known-good config and retries.

`before_model_callback` re-reads the model each request, so a model change needs no deployment.

Never put a live setting in bootstrap env as well.

## Bootstrap environment

Remote deployments pass only the small bootstrap contract:

```text
CONFIG_PARAMETER
CONFIG_PARAMETER_LOCATION
CONFIG_REFRESH_SECONDS
BOOTSTRAP_MODEL
GEMINI_MODEL_LOCATION
GEMINI_ENTERPRISE_AUTHORIZATION_ID   # agents using the delegated token
MCP_SERVER_URL                       # agents using an MCP toolset
```

`dev/common.py` sends these through `RUNTIME_ENV_KEYS`. A new bootstrap variable must be added there or it never reaches the deployed agent.

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

or any other agent in `AGENTS`:

```bash
uv run --group dev python dev/run_local.py --agent auth_reference_agent
uv run --group dev python dev/run_local.py --agent bigquery_mcp_agent
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
Once per project:
  1. configure gcloud + ADC
  2. apply the companion Terraform platform stack (APIs, IAM, observability)
  3. fill dev/.env.dev deployment coordinates
  4. run bootstrap_dev.py: project, APIs, staging bucket, optional BigQuery fixture

Once per agent:
  5. run tests/lint
  6. package the agent
  7. run deploy_dev.py: creates the Agent Engine and the agent's runtime parameter
  8. run register_agent.py: publishes it into a Gemini Enterprise app
```

Terraform comes first because it grants the IAM the dev scripts and the deployed agents rely on. It is applied once and then rarely changes; adding an agent never requires an apply. See [What Terraform owns](#what-terraform-owns).

`release_dev.py --agent <name>` runs steps 6, 7 and 8 in one command.

Deploying an Agent Engine does not make it visible in Gemini Enterprise. Step 8 is what puts it on the Agents page and enables the delegated consent flow.

A delegated-auth agent additionally needs its own OAuth client, which is the one step that cannot be automated. Registration stops and prints exactly what to create; see [OAuth clients for delegated auth](#oauth-clients-for-delegated-auth).

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
| Parameter Manager runtime config | Verify the agent's own parameter | Stop at deploy time and name the missing parameter |
| IAM | Use existing grants | Never self-grant; fix through the appropriate platform/IAM process |

Project creation is disabled by default because it affects organization placement, quota and billing.

## Optional BigQuery developer fixture

The delegated BigQuery tool needs queryable data, which a clean project lacks. The bootstrap can create a small dataset for it.

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

The helper grants no IAM. Two identities need permissions already:

- whoever runs `bootstrap_dev.py`: create and read the fixture resources
- the signed-in Gemini Enterprise user: create query jobs and read the dataset

Fix missing permissions through IAM, never by adding self-grant logic. Terraform does not create this dataset; it is developer test support.

## Deterministic application packaging

Build the deployment artifact:

```bash
uv run --group dev python dev/package_agent.py --agent <agent>
```

Output is `artifacts/<agent>.tar.gz`, gitignored. Timestamps and ownership are normalized and `requirements.txt` is generated, so unchanged source rebuilds to identical bytes.

The archive holds only the selected agent and `gemini_shared`. Other agents are not bundled.

## Developer-owned Agent Engine deployment

Once the agent's runtime parameter exists:

```bash
uv run --group dev python dev/deploy_dev.py --agent <agent>   # create
uv run --group dev python dev/update_dev.py --agent <agent>   # code or bootstrap changes
```

The Reasoning Engine resource is recorded under ignored `dev/.state/`.

Parameter Manager changes need no update. A running agent picks them up after the TTL.

## Gemini Enterprise registration

Deployment and registration are separate. `deploy_dev.py` creates the Agent Engine; the agent only appears in a Gemini Enterprise app after it is registered:

```bash
uv run --group dev python dev/register_agent.py --agent basic_assistant
```

Set `GEMINI_ENTERPRISE_APP_ID` in `dev/.env.dev` to the app (engine) id. This is not the web app client id shown in the console URL.

Registration is idempotent. An agent with the same display name is patched to point at the current Reasoning Engine rather than duplicated.

Each agent's registration metadata — description, invocation description and starter prompts — lives in its `AgentSpec` in `dev/common.py`, so the registered listing stays in the repository rather than being maintained by hand in the console.

Agents with delegated tools additionally need a Gemini Enterprise authorization, which triggers the user consent flow and forwards the resulting token to the agent. `register_agent.py` reuses the authorization when it already exists, and creates it otherwise.

One authorization serves one agent: registering a second agent against an authorization already bound elsewhere fails with `is used by another agent`. Each agent therefore defaults to its own, named `<package-name>-authz`, so adding a delegated-auth agent needs no shared configuration change. `GEMINI_ENTERPRISE_AUTHORIZATION_ID` overrides that default for a single run.

The authorization's OAuth scopes must cover everything that agent's delegated tools call.

## OAuth clients for delegated auth

Every delegated-auth agent needs **its own OAuth client**. Gemini Enterprise caches the user's consent per client, so two agents sharing one share a single grant: the second is handed a token it never consented to, every call fails with `401`, and no amount of re-consenting fixes it.

OAuth clients cannot be created from the CLI or any API. This is the one manual step in the whole flow. Registration stops and prints the exact client name, redirect URIs, scopes and environment variables to use, all derived from the agent, so nothing has to be worked out by hand.

In the console, under **APIs & Services > Credentials**, create a **Web application** client and add **both** redirect URIs:

```text
https://vertexaisearch.cloud.google.com/static/oauth/oauth.html
https://vertexaisearch.cloud.google.com/oauth-redirect
```

Both are required. The authorization resource stores the first, but the live consent flow redirects to the second. A client with only the first is accepted when the authorization is created and then fails with `redirect_uri_mismatch` the moment a user clicks **Authorize**.

Then put the id and secret in `dev/.env.dev` and run registration again:

```text
OAUTH_CLIENTS=<agent>=<client id>,<other agent>=<its client id>
<AGENT>_OAUTH_CLIENT_SECRET=<client secret>
```

`OAUTH_CLIENTS` is keyed by agent name rather than positional, so adding or removing an agent cannot shift another onto the wrong client. The secret is copied into Secret Manager as `<package-name>-oauth-client-secret` on that run and read from there afterwards, so remove it from the file once it has run.

Registration verifies that the secret actually belongs to the client id before writing the authorization. A mismatched pair is otherwise accepted at creation and only surfaces later as an endless consent loop, because the token exchange fails after the user has already approved.

### Two names, only one of which users see

| Name | Scope | Where it appears |
|---|---|---|
| OAuth client **Name** | one per client | the console credentials list |
| OAuth consent screen **App name** | one per **project** | the "Sign in with Google" screen |

Naming a client after its agent keeps the credentials list readable, but users always see the project's single consent screen App name. Google offers no way to vary it per client, so set it to something that makes sense for every agent in the project.

## Identity model

Three identities, never interchangeable:

| Identity | Used by | Granted by |
|---|---|---|
| Developer ADC | `dev/` helpers on the workstation | Terraform: Agent Engine deploy, staging bucket, Parameter Manager read |
| Agent Identity | the deployed runtime | Terraform, on the project principal set |
| Delegated user token | tools and MCP calls acting as the user | Gemini Enterprise OAuth consent |

Developer permissions do not transfer to the Agent Identity. Terraform pre-authorizes the principal set for non-sensitive roles such as Parameter Manager read; keep sensitive data access scoped to the individual agent.

Delegated access stays user-scoped and inherits nothing from the Agent Identity.

Developer helpers never create or modify IAM.

## Authentication reference agent

`auth_reference_agent` shows both patterns, using tools written here against the Google Cloud APIs:

| Tool | Identity | Reaches |
|---|---|---|
| `list_storage_objects` | Agent Identity | Cloud Storage |
| `query_bigquery` | delegated user token | BigQuery |

Reaching BigQuery through a remote MCP server instead is a separate agent, `bigquery_mcp_agent`, so each agent demonstrates one way of obtaining its tools.

The scheme, provider and registration live in `gemini_shared.auth.delegated`, shared by every agent.

A deployed scheme arrives as a base `CustomAuthScheme`. ADK rehydrates it by matching `type_` against `CustomAuthScheme.__subclasses__()`, so the defining module must already be imported when a tool runs. Importing anything from `gemini_shared` does that.

Unimported module:

```text
No auth provider registered for custom auth scheme
```

A new scheme must set a `type_` default; rehydration matches on that value.

## Remote MCP servers

An MCP server supplies tools the agent did not write. `bigquery_mcp_agent` uses Google's managed BigQuery server, so nothing is deployed:

```python
bigquery_mcp_toolset = bigquery_readonly_toolset(
    authorization_id=GEMINI_ENTERPRISE_AUTHORIZATION_ID,
    server_url=MCP_SERVER_URL,      # https://bigquery.googleapis.com/mcp
)
```

Two sub-packages:

- `mcp_auth/` authenticates to any MCP server. Names no server.
- `mcp_google_cloud/` holds Google's URLs, scopes and tool lists. Add a server as `mcp_<name>/`.

`mcp_auth/headers.py` sends `Authorization: Bearer <user token>` on every call, using the same delegated token as the BigQuery tool. The server enforces that user's IAM, so each user sees only their own data. The Agent Identity is not used here.

The agent reaches BigQuery both ways on purpose. Write a tool when the logic is yours; use an MCP server when the tools already exist.

[Google's managed endpoints](https://docs.cloud.google.com/mcp/supported-products) cover BigQuery, Cloud Run, Logging, Monitoring, Storage and Compute. `MCP_SERVER_URL` accepts any Streamable HTTP server. It is bootstrap env, not live config, because the toolset is built at construction.

### tool_filter

A client-side allowlist. ADK fetches the server's full tool list, keeps the names you list and discards the rest, so the model never sees the others:

```python
tool_filter=["list_dataset_ids"]    # 1 tool reaches the model
tool_filter=None                    # all 6 do, including execute_sql
```

It stops the model from calling a tool. It does not revoke anything at the server: the user's IAM and the token's scopes still decide what a call may do.

`bigquery_readonly_toolset` omits `execute_sql`, leaving the five read-only tools.

### Scopes

The delegated token needs the server's scope: `https://www.googleapis.com/auth/bigquery` or `.../auth/cloud-platform` for BigQuery. A missing scope fails at the tool call, not at startup, because `tools/list` is unauthenticated and `tools/call` is not.

### Names

`tool_name_prefix="bq_mcp"` yields `bq_mcp_list_dataset_ids`, keeping MCP tools distinct from local ones in the model's tool list and in traces.

## Adding an agent

Copy `agents/basic_assistant/` and change the names. Every file below is required; the recipe is complete as written.

### 1. Package files

`agents/<agent>/pyproject.toml` — add a dependency only if a tool imports it. `[mcp]` is required for MCP toolsets, `[agent-identity]` for Agent Identity.

```toml
[project]
name = "<agent-name>"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
  "gemini-shared",
  "google-adk[extensions]==2.7.1",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/<agent>"]
```

`src/<agent>/__init__.py`:

```python
from .agent import app, root_agent

__all__ = ["app", "root_agent"]
```

`src/<agent>/config.py` — bootstrap values only, resolved once. Use `require_auth=True` when any tool uses the delegated token.

```python
from gemini_shared import get_bootstrap_settings

BOOTSTRAP = get_bootstrap_settings()
PROJECT_ID = BOOTSTRAP.project_id
```

`src/<agent>/agent.py` — construction only. No tool logic, no prompt text.

```python
root_agent = Agent(
    name="<agent>",                        # unique; keep stable after registration
    model=Gemini(
        model=BOOTSTRAP.bootstrap_model,
        client_kwargs={"location": BOOTSTRAP.model_location},
    ),
    description="<one line, shown in Gemini Enterprise>",
    instruction=runtime_instruction,       # from Parameter Manager, per request
    before_model_callback=apply_runtime_model,
    tools=[...],
)

app = AdkApp(agent=root_agent, enable_tracing=True)   # Agent Runtime serves this
```

### 2. Add a tool

One module per tool under `src/<agent>/tools/`, re-exported from `tools/__init__.py`. ADK builds the model-facing schema from the docstring and type hints. No docstring means no description.

```python
def report_order_status(order_id: str) -> dict[str, object]:
    """Return the current status of one order.

    Args:
        order_id: The order identifier to look up.
    """
```

Return JSON-serializable values. `date`, `Decimal` and `bytes` break the run; convert them first.

To act as the signed-in user, wrap the function so ADK injects the credential:

```python
tool = AuthenticatedFunctionTool(
    func=query_bigquery,                                  # takes credential: AuthCredential
    auth_config=delegated_auth_config(GEMINI_ENTERPRISE_AUTHORIZATION_ID),
)
```

### 3. Add an MCP server

Google's managed servers need nothing deployed:

```python
from gemini_shared.mcp.mcp_google_cloud import bigquery_readonly_toolset

toolset = bigquery_readonly_toolset(authorization_id=GEMINI_ENTERPRISE_AUTHORIZATION_ID)
```

Any other Streamable HTTP server:

```python
from gemini_shared.mcp.mcp_auth import delegated_mcp_toolset

toolset = delegated_mcp_toolset(
    server_url=MCP_SERVER_URL,
    authorization_id=GEMINI_ENTERPRISE_AUTHORIZATION_ID,
    tool_filter=["read_only_tool"],   # allowlist; omit and the model sees every server tool
    tool_name_prefix="ext",
)
```

Add the `mcp` extra to the agent's `pyproject.toml` and to its `requirements` in `dev/common.py`.

Used by more than one agent? Put the URL, scopes and tool list in `packages/gemini_shared/src/gemini_shared/mcp/mcp_<name>/`.

### 4. Choose the identity

| Downstream access | Use | Needs |
|---|---|---|
| Same for all users | Agent Identity | Covered by the platform stack's project-wide roles |
| Varies by user | Delegated token | Authorization id + OAuth scopes covering every call |

Delegated tools and MCP servers share one token, so the authorization's scopes must cover both.

### 5. Register with the dev tooling

Add an `AgentSpec` to `AGENTS` in `dev/common.py`. Without it the dev scripts cannot see the agent.

```python
"<agent>": AgentSpec(
    package_name="<agent-name>",              # matches pyproject [project].name
    module="<agent>.agent",
    display_name="<Shown in Gemini Enterprise>",
    extra_packages=(
        "agents/<agent>/src/<agent>",
        "packages/gemini_shared/src/gemini_shared",
    ),
    requirements=COMMON_REQUIREMENTS,          # + extras this agent imports
    required_remote_bootstrap_env=(),           # (AUTHORIZATION_ID_ENV,) if delegated
    registration_description="...",             # what it does
    invocation_description="...",               # when to call it
    starter_prompts=("...",),
),
```

### 6. Configure and deploy

Live settings (model, instruction, limits) go in the agent's own Parameter Manager parameter, `<package-name>-config`; bootstrap values go in the deployed env map. Never both. A delegated-auth agent likewise gets its own authorization, `<package-name>-authz`. Both names are derived from the spec, so no shared configuration changes and no Terraform apply is needed to add an agent.

```bash
uv run --group dev ruff format . && uv run --group dev ruff check . && uv run --group dev pytest
uv run --group dev python dev/run_local.py --agent <agent>
uv run --group dev python dev/release_dev.py --agent <agent>
```

`release_dev.py` packages, deploys and registers. Deploying alone does not make the agent visible in Gemini Enterprise; registration does.

The runtime parameter is created on the first deployment, so nothing has to exist beforehand. A delegated-auth agent stops at registration until it has its own OAuth client, which is the only manual step; the message names everything to create. See [OAuth clients for delegated auth](#oauth-clients-for-delegated-auth).

### 7. Extend the tests

`tests/test_validation.py` parametrizes over `AGENTS`, so the new agent inherits the checks that every tool has a description and that the instruction resolves from runtime configuration as soon as its spec exists.

Two places still name agents explicitly: add the agent's `src` directory to `pythonpath` in the root `pyproject.toml`, and add an import test to `tests/test_imports.py`.

## Code standards

- Python 3.12, PEP 8, `ruff` clean.
- Constants and repeated config keys at module scope.
- Type hints on shared functions; frozen slotted dataclasses.
- Subprocesses: argument arrays, no shell, resolved executable path.
- Writes only to ignored state/artifact paths or secure temp dirs.
- External input and env values fail fast with actionable errors.
- Shared logic in `gemini_shared` or `dev/common.py`; domain logic in the agent.
- No `assert` in production control flow.
- Never log credentials, secrets or delegated tokens.

## Repository rules

- No IAM mutation from application code.
- No Terraform or shared infrastructure in this branch.
- No committed `.env`, credentials or secrets.
- No long-lived service-account keys.
- No setting duplicated across `.env`, Parameter Manager and Terraform.
- No QA or prod deployment from `dev/` helpers.
- No hardcoded MCP URL in an agent. Use `mcp/mcp_<name>/` or bootstrap env.
- No MCP toolset without `tool_filter`.
- Test fixtures stay optional, bounded and out of shared infrastructure.
