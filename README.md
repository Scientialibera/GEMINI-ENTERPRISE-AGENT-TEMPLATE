# Gemini Enterprise ADK agents

This repository contains three Python agents and scripts to run them locally,
deploy them to Agent Engine and register them in Gemini Enterprise.

| Agent | Purpose |
|---|---|
| basic_assistant | Answer questions and report the active runtime settings. |
| auth_reference_agent | Read Cloud Storage with Agent Identity and query BigQuery with the user's delegated token. |
| bigquery_mcp_agent | Explore BigQuery through Google's managed MCP server using the user's delegated token. |

The dev/ scripts target development projects and require ENVIRONMENT=dev for remote
operations. They do not change IAM. The companion template/terraform-iac-only branch
contains the platform setup; review and apply its grants before deploying.

## Set up the workstation

Install Python 3.12 or later, uv and the Google Cloud CLI. From this repository, run:

~~~bash
uv sync --all-packages --group dev
gcloud auth login
gcloud auth application-default login
~~~

The CLI uses the first login. Python clients use Application Default Credentials (ADC)
from the second. Local execution needs ADC; the deployment preflight checks both.

Run the checks before deploying:

~~~bash
uv run --group dev ruff format --check .
uv run --group dev ruff check .
uv run --group dev pytest
~~~

These tests use mocks for cloud calls. They do not replace testing the deployed agent
and its consent flow in Gemini Enterprise.

## Run an agent locally

Copy dev/.env.local.example to dev/.env.local. Set the project and model, then write
the local instructions in AGENT_INSTRUCTION.

~~~bash
uv run --group dev python dev/run_local.py --agent basic_assistant
~~~

Replace basic_assistant with another registered agent to run it. The local runner calls
real model and service APIs, so usage can incur charges.

Leave CONFIG_PARAMETER unset to read settings from the local environment. Both
delegated agents need an authorization ID to construct their tools, but user
authentication must be tested through Gemini Enterprise, which supplies the session
token. Local ADC does not reproduce that flow. Cloud Storage calls made locally use
your workstation credentials.

## Deploy and register

Prepare the project with the companion platform stack. Create or select a Gemini
Enterprise app and copy dev/.env.dev.example to dev/.env.dev. Set:

~~~text
GOOGLE_CLOUD_PROJECT=<project-id>
GOOGLE_CLOUD_LOCATION=us-central1
DEV_STAGING_BUCKET=gs://<staging-bucket>
ENVIRONMENT=dev
GEMINI_ENTERPRISE_APP_ID=<engine-id>
~~~

Use the app's engine ID for GEMINI_ENTERPRISE_APP_ID. The scripts load .env files
without overriding variables already set in the shell.

~~~bash
uv run --group dev python dev/release_dev.py --agent basic_assistant
~~~

The release checks prerequisites, builds an archive, deploys or updates the runtime,
then registers it in the app. It chooses an update when dev/.state/ contains a saved
resource for that agent. Keep this ignored state directory between releases.

Use --skip-register to stop after deployment. Registration is also skipped when the
app ID is empty. For a delegated agent, registration prints OAuth setup details if its
authorization is missing. Complete the setup below, then rerun register_agent.py.
You do not need to redeploy code just to register a runtime.

| Script in dev/ | Effect |
|---|---|
| config/bootstrap_dev.py | Check the sandbox and optionally prepare BigQuery sample data. |
| `deploy/package_agent.py --agent <name>` | Build an archive containing one agent and gemini_shared. |
| `deploy/deploy_dev.py --agent <name>` | Create a new Agent Engine and save its resource name. |
| `deploy/update_dev.py --agent <name>` | Update the saved runtime, or the DEV_REASONING_ENGINE override. |
| `register/register_agent.py --agent <name>` | Create or update the app listing for the deployed runtime. |

Run each with `uv run --group dev python dev/<script>`. deploy_dev.py creates a new
runtime on every run; use update_dev.py for an existing runtime. Registration matches
listings by display name, so keep that name stable when updating an existing listing.

The preflight creates a missing runtime parameter and publishes changes to prompt.md.
It can also enable missing APIs and create a staging bucket; both controls default to
enabled. Project creation is disabled by default. Check the
[developer controls](dev/README.md#sandbox-controls) before using a shared project.

### Permissions and setup ownership

This table separates **who is responsible for granting or creating something** from
**whether it is technically automatable**. An administrator-owned IAM change can still
be performed by Terraform or code when the executing identity already has permission.
UI-only means the current Google/Gemini Enterprise workflow requires a console action.

| Requirement / permission | Needed by | Owner / grantor | How it is supplied | UI-only? |
|---|---|---|---|---|
| Access to the target GCP project | Developer / deployment identity | Cloud or platform admin | IAM, normally through the companion Terraform platform stack | No |
| Create/update Agent Engine resources | Developer / deployment identity | Cloud or platform admin | IAM grant; `dev/deploy/deploy_dev.py` and `dev/deploy/update_dev.py` consume it | No |
| Read/create the agent runtime parameter and publish versions | Developer deployment flow; runtime reads it | Cloud or platform admin grants access; dev tooling creates agent-owned parameters | IAM plus `dev/config/bootstrap.py` / deployment preflight | No |
| Enable required Google Cloud APIs | Project | Cloud or platform admin, or developer with Service Usage permission | Terraform or `dev/config/bootstrap_dev.py` when enabled | No |
| Create/use the developer staging bucket | Developer deployment flow | Cloud or platform admin, or developer with Storage permission | Terraform/existing bucket or `dev/config/bootstrap_dev.py` when enabled | No |
| Create the optional BigQuery fixture dataset/table | Developer | Data/cloud admin, or developer with BigQuery create permissions | `dev/config/bootstrap_dev.py`; unnecessary when suitable test data already exists | No |
| Query BigQuery through delegated auth | Signed-in Gemini Enterprise user | Data/IAM admin | User IAM on the target BigQuery project/dataset/table; the agent cannot elevate it | No |
| Read a Cloud Storage bucket with Agent Identity | Deployed Agent Identity | Data/IAM admin | IAM grant on the specific bucket/resource; deployment scripts do not self-grant it | No |
| Gemini Enterprise application | Registration flow | Gemini Enterprise administrator | Create/select the app in the Gemini Enterprise admin UI; copy its engine ID to `.env.dev` | Yes for initial app creation |
| OAuth consent screen / test-user configuration | Delegated-auth agents | Google Cloud / Google Auth Platform administrator | Google Auth Platform console | Yes |
| Dedicated OAuth client ID and client secret for each delegated agent | Registration flow | Google Cloud / Google Auth Platform administrator | Create a Web application client in Google Auth Platform with both documented redirect URIs | Yes |
| Store the OAuth client secret in Secret Manager | Registration flow | Registration script using existing Secret Manager access | `dev/register/register_agent.py` imports the initial secret when no stored version exists | No |
| Gemini Enterprise authorization resource | Delegated-auth agent | Registration flow using its caller permissions | `dev/register/register_agent.py` creates/reuses the per-agent authorization | No |
| Gemini Enterprise agent listing / registration | End users | Registration flow using its caller permissions | `dev/register/register_agent.py` creates/updates the app listing | No |

The dev scripts consume existing IAM; they never grant themselves new IAM. If a
programmable step fails for lack of permission, fix the grant through the approved
platform/IAM path rather than adding privilege-escalation logic to the application
scripts.

## Configure delegated OAuth

Use a separate OAuth client and authorization for each delegated agent in this template.
The defaults are `<package-name>-authz` for the authorization and
`<package-name>-oauth-client-secret` for its secret.

Configure the project's OAuth consent screen, including the test users and scopes
needed for your test. In Google Auth Platform, create a **Web application** client with
the name printed by register_agent.py. Add both callbacks used by this integration:

~~~text
https://vertexaisearch.cloud.google.com/static/oauth/oauth.html
https://vertexaisearch.cloud.google.com/oauth-redirect
~~~

The authorization resource uses the first URI and the consent flow uses the second.
A missing callback can cause redirect_uri_mismatch when the user authorizes the agent.

Add the client IDs to dev/.env.dev, keyed by agent name:

~~~text
OAUTH_CLIENTS=auth_reference_agent=<client-id>,bigquery_mcp_agent=<other-client-id>
AUTH_REFERENCE_AGENT_OAUTH_CLIENT_SECRET=<initial-secret>
BIGQUERY_MCP_AGENT_OAUTH_CLIENT_SECRET=<initial-secret>
~~~

`<AGENT>_OAUTH_CLIENT_ID` overrides that agent's map entry. Variable prefixes use the
package name in uppercase with hyphens replaced by underscores.

~~~bash
uv run --group dev python dev/register/register_agent.py --agent auth_reference_agent
uv run --group dev python dev/register/register_agent.py --agent bigquery_mcp_agent
~~~

When the stored secret is missing, registration imports the initial secret into Secret
Manager. Remove its raw value from .env.dev after a successful import. Existing stored
secrets take precedence over environment values; rotate them in Secret Manager.

Registration checks for a mismatched client ID and secret before creating an
authorization. Existing authorizations are reused; rerunning registration does not
change their OAuth settings. If the client or scopes change, review the authorization
as a separate change and retest consent.

Each agent declares delegated service scopes in AgentSpec.delegated_oauth_scopes.
The BigQuery examples request the BigQuery scope plus the shared identity scopes.
Agent Identity tools do not add delegated scopes.

The OAuth client's name identifies it in the console. The consent screen's app name
is what users see during sign-in.

## Test the deployed agents

Open an agent in Gemini Enterprise and send one of its starter prompts. For delegated
tools, complete **Authorize** and confirm BigQuery returns data the signed-in user can
access. Test another user with different permissions to check access boundaries.
Signing in alone does not prove delegated API access works.

For Cloud Storage, set agent_identity_bucket_name in the runtime parameter and grant
the deployed Agent Identity access to that bucket through the approved IAM process.
Call list_storage_objects and check its reported identity and returned objects.

Use report_runtime_config to check the active parameter, revision and model. It returns
configuration metadata and excludes secrets and prompt text.

The optional BigQuery fixture provides five sample orders. Run config/bootstrap_dev.py to
prepare it, or use a dataset the test user can already query.
See [fixture settings](dev/README.md#bigquery-fixture).

## Manage configuration

| Setting | Location | How a change takes effect |
|---|---|---|
| Model, instructions, log level and tool limits | Parameter Manager | After the runtime cache expires. |
| Parameter address, model location, authorization ID and MCP endpoint | Runtime environment | Update the deployed runtime. |
| OAuth client secret | Secret Manager | Update the stored version and review any existing authorization that uses it. |
| Workstation settings | Ignored dev/.env.local and dev/.env.dev | Reload the process; shell variables take precedence. |

### Runtime settings

Each agent defaults to `<package-name>-config`. CONFIG_PARAMETER can override the name
or select a full parameter/version resource. Unversioned addresses resolve to
versions/latest. RuntimeConfig rejects unknown fields and invalid values.

~~~json
{
  "config_revision": "example-v1",
  "model": "<approved-model-id>",
  "instruction": "Answer using the available tools. Ask when the request is unclear.",
  "environment": "dev",
  "log_level": "INFO",
  "agent_identity_bucket_name": null,
  "storage_object_limit": 10,
  "bigquery_query_row_limit": 100
}
~~~

Replace the model placeholder before publishing. Storage limits allow 1–100 objects;
BigQuery row limits allow 1–10,000 rows. These limits apply to the custom tools.
The remote MCP server controls its own tool behavior.

Settings are cached for CONFIG_REFRESH_SECONDS. After a successful load, a failed
refresh retains the last valid settings for that same parameter and retries within
30 seconds or the configured refresh interval, whichever is shorter. The first failed
load raises an error. Switching parameters requires a successful read of the new one.

The instruction and model callbacks use this cache for each request. Publish a new
parameter version to change live settings without redeploying code.

### Prompt source

Edit `agents/<agent>/prompt.md` to maintain the prompt in version control. Deployment
compares it with the live instruction and publishes a version if they differ, retaining
the other settings. Prompt files are outside src/ and excluded from the runtime archive.

For a live-only edit, publish the instruction directly in Parameter Manager. Also update
prompt.md if you want to keep that edit: the next deployment publishes the repository
prompt again. Local runs use AGENT_INSTRUCTION rather than loading prompt.md.

### Bootstrap settings

dev/common.py forwards these environment keys to the runtime:

~~~text
CONFIG_PARAMETER
CONFIG_PARAMETER_LOCATION
CONFIG_REFRESH_SECONDS
BOOTSTRAP_MODEL
GEMINI_MODEL_LOCATION
GEMINI_ENTERPRISE_AUTHORIZATION_ID
MCP_SERVER_URL
~~~

Add new bootstrap keys to RUNTIME_ENV_KEYS if they must reach the deployed agent.
The platform supplies the deployed project and runtime location; keep reserved runtime
variables out of the forwarded map. The MCP URL is resolved when constructing the
toolset, so changing it requires a runtime update.

## Repository layout

~~~text
agents/<agent>/
  prompt.md                  version-controlled instruction
  pyproject.toml             agent dependencies and wheel settings
  src/<agent>/
    agent.py                 construct the Agent and AdkApp
    config.py                resolve bootstrap settings
    tools/                   tool implementations and shared-tool exports
packages/gemini_shared/src/gemini_shared/
  auth/                      delegated credential provider and token readers
  config/                    bootstrap settings, live cache, callbacks and status tool
  connectors/                shared Google Cloud clients
  mcp/mcp_auth/              authenticated Streamable HTTP toolsets
  mcp/mcp_google_cloud/      managed endpoints and BigQuery tool allowlist
dev/                         local, packaging, deployment and registration scripts
tests/                       import, validation and behavior tests
~~~

Each archive includes one agent and the shared package. Packaging excludes caches and
bytecode, rejects symlinks and normalizes timestamps and ownership. Unchanged inputs
produce identical archive bytes. Outputs go under ignored artifacts/; deployment state
goes under ignored dev/.state/.

## Add an agent

1. Copy agents/basic_assistant/. Rename the package directory, project name in
   pyproject.toml and wheel path. Set a stable agent name in agent.py.
2. Write prompt.md. Keep instructions specific to the task and available tools.
3. Add tools under tools/ and export them from tools/__init__.py. Keep tool logic
   separate from agent construction. Share reusable behavior in gemini_shared.
4. Add an AgentSpec to AGENTS in dev/common.py. Supply the package name, import module,
   display name, source paths, deployment requirements and registration text.
   For delegated tools, declare AUTHORIZATION_ID_ENV and the required service scopes.
5. Add dependencies to the agent's pyproject.toml and deployment requirements.
   Use the existing agents as examples for the agent-identity and mcp extras.
6. Add the source directory to pytest's pythonpath in the root pyproject.toml, add an
   import test and test the new tools. Registry-based tests include the agent automatically.
7. Run uv sync --all-packages --group dev, lint and tests. Try the local runner, then
   release the agent and test it in Gemini Enterprise.

Keep runtime_instruction, apply_runtime_model and the AdkApp wrapper from the copied
agent. Tool functions need type hints and short docstrings: ADK uses them to describe
the tools to the model. Document arguments the model must supply and return
JSON-compatible values. The BigQuery example converts dates, decimals and byte strings.

### Choose tool authentication

| Access needed | Implementation |
|---|---|
| A shared capability available through the agent | Use runtime credentials and grant Agent Identity access to the specific resource. |
| Access limited to the signed-in user's permissions | Use a delegated session token. Configure the authorization and scopes for that service. |

Developer ADC, deployed Agent Identity and delegated user tokens are separate
credentials. Grant each only the access needed. Deployment scripts do not grant IAM.

For custom delegated tools, use AuthenticatedFunctionTool with
delegated_auth_config(authorization_id). See auth_reference_agent for the credential
argument and BigQuery client construction. Importing gemini_shared registers the
provider needed to rehydrate the auth scheme after deployment; preserve this import
when reorganizing the package.

### Connect an MCP toolset

Use bigquery_readonly_toolset for the existing BigQuery example. To connect another
Streamable HTTP server that accepts the configured delegated token:

~~~python
from gemini_shared.mcp.mcp_auth import delegated_mcp_toolset

toolset = delegated_mcp_toolset(
    server_url=MCP_SERVER_URL,
    authorization_id=GEMINI_ENTERPRISE_AUTHORIZATION_ID,
    tool_filter=["read_only_tool"],
    tool_name_prefix="ext",
)
~~~

Use the server's actual tool names and required OAuth scopes. Configure a compatible
authorization provider for that service; a Google token is not valid for every MCP server.

Always supply an explicit allowlist for application toolsets. tool_filter=None exposes
all tools returned by the server, including future additions. The BigQuery allowlist
contains five read-only tools and excludes execute_sql. Filtering limits tools shown
to the model; server-side permissions still control access.

Headers use the current session token for each request. Tool descriptions are cached
for five minutes by default. Keep shared endpoints, scopes and tool lists under
gemini_shared/mcp/ when multiple agents use them.

## Code conventions

Use Python 3.12-compatible code with type hints on shared functions. Ruff checks import
order, PEP 8 rules and common correctness and security issues, with a 100-character
line limit. Comments should explain constraints or decisions that the code does not.

Keep domain logic with its agent and reusable logic in the shared package. Pass
subprocess arguments as a list without a shell. Validate external input before cloud
operations. Never log tokens or secrets, commit credentials or .env files, or add IAM
self-grants to application code. The dev/ workflow is limited to development projects.
