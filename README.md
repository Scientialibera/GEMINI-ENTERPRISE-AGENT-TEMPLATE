# Gemini Enterprise ADK agents and workflows

This repository contains four Python agents, one workflow and the scripts to run them
locally, deploy them to Agent Engine and register them in Gemini Enterprise.

An **agent** is conversational: it holds tools and decides which to call as the
exchange goes on. A **workflow** is a pipeline: its stages always run in the same
order and each hands its result to the next. Both deploy the same way, to the same
runtime, under the same identity; they differ only in how they are composed. The
recipe card exists in both forms so the two can be compared directly.

| Agent | Purpose |
|---|---|
| basic_assistant | Answer questions and report the active runtime settings. |
| auth_reference_agent | Read Cloud Storage with Agent Identity and query BigQuery with the user's delegated token. |
| bigquery_mcp_agent | Explore BigQuery through Google's managed MCP server using the user's delegated token. |
| monitoring_mcp_agent | Inspect Cloud Monitoring metrics, alerts and dashboards through Google's managed MCP server using the user's delegated token. See its [README](agents/monitoring_mcp_agent/README.md). |
| recipe_card_agent | Write a recipe, generate its photography and publish a PowerPoint recipe card to Cloud Storage. |

| Workflow | Purpose |
|---|---|
| recipe_card_workflow | The same card as a fixed pipeline: write the recipe, generate the images, render the deck. Takes a dish name and returns a link. |

The dev/ scripts target development projects and require ENVIRONMENT=dev for remote
operations. infrastructure/ contains the shared platform setup and baseline IAM, and is
unchanged by adding an agent or a workflow. Deployment
never grants IAM to the caller itself. An optional per-agent IAM helper can apply
explicitly configured roles to the exact Agent Identity after its runtime exists, but
only when the caller already has permission to change IAM.

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

There are two ways to stand a project up, and they differ only in who grants the roles
every Agent Identity needs.

**With the platform stack**, the normal path for anything shared. Apply
`infrastructure/` first: it owns the APIs, the baseline IAM, Secret Manager
and observability, and it grants those roles to a trust-domain principal set covering
every Agent Identity in the project, so an agent added later inherits them with no
infrastructure change. Then use the scripts here for everything per-agent.

**Without it**, for a sandbox, a demo project or a first look at the template. The dev
scripts can do the whole thing: `config/bootstrap_dev.py` creates the project, enables
the APIs, creates the staging bucket and — with `DEV_GRANT_AGENT_IDENTITY_BASELINE=true`
— grants that same baseline itself, to the same principal set. Nothing but this
repository is needed.

~~~bash
uv run --group dev python dev/config/bootstrap_dev.py
uv run --group dev python dev/release_dev.py --agent basic_assistant
~~~

The baseline is what lets an agent read its own model and instruction from Parameter
Manager. Without it a runtime deploys and starts, then fails on its first request. The
flag is off by default and needs project IAM admin: leave it off wherever Terraform is
applied, because granting the same bindings from two places makes it unclear which one
owns them.

Either way, the OAuth client, its consent screen and the Gemini Enterprise app are
created by hand, because no API exists for them. See
[order of operations](dev/README.md#order-of-operations) for the full sequence.

Create or select a Gemini Enterprise app and copy dev/.env.dev.example to
dev/.env.dev. Set:

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
applies any explicitly configured Agent Identity IAM and then registers the runtime in
the app. It chooses an update when saved state or DEV_REASONING_ENGINE identifies a
runtime in the selected project and region. State is stored under
dev/.state/<project-number>/<region>/<agent>.json. Matching older agent-only state files
are migrated automatically. A mismatched explicit runtime is rejected before preflight.
Keep this ignored state directory between releases.

Use --skip-register to stop after deployment. Registration is also skipped when the
app ID is empty. For a delegated agent, registration prints OAuth setup details if its
authorization is missing. Complete the setup below, then rerun register_agent.py.
You do not need to redeploy code just to register a runtime.

Splitting a first release into those two steps is worth doing for a delegated agent:
deployment touches no OAuth resource, so the consent screen can be finished between
them. **A deployed runtime does not appear in Gemini Enterprise until it is
registered** — registration creates the app listing, and without it the agent exists in
Vertex AI but is invisible in the UI.

~~~bash
uv run --group dev python dev/release_dev.py --agent <name> --skip-register
# finish the consent screen, then register. This runs register_agent.py as a
# module: executing the file directly puts dev/register/ first on sys.path,
# where its own http.py shadows the standard library's http package.
uv run --group dev python -c "import sys; sys.path.insert(0,'dev'); \
from register.register_agent import main; \
sys.argv=['register_agent.py','--agent','<name>']; main()"
~~~

| Script in dev/ | Effect |
|---|---|
| config/bootstrap_dev.py | Check the sandbox and optionally prepare BigQuery sample data. |
| `deploy/package_agent.py --agent <name>` | Build an archive containing one agent and gemini_shared. |
| `deploy/deploy_dev.py --agent <name>` | Create a new Agent Engine with Agent Identity and save its resource name. |
| `deploy/update_dev.py --agent <name>` | Update the saved runtime, or the DEV_REASONING_ENGINE override. |
| `iam/apply_agent_identity_iam.py --agent <name>` | Apply configured IAM roles to the exact deployed Agent Identity. |
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
| Access to the target GCP project | Developer / deployment identity | Cloud or platform admin | IAM, normally through the platform stack in infrastructure/ | No |
| Create/update Agent Engine resources | Developer / deployment identity | Cloud or platform admin | IAM grant; `dev/deploy/deploy_dev.py` and `dev/deploy/update_dev.py` consume it | No |
| Create the Agent Identity for a runtime | Agent Engine deployment | Google Agent Engine | `identity_type=AGENT_IDENTITY` in `dev/deploy/deploy_dev.py`; Google provisions the identity | No |
| Baseline IAM shared by every Agent Identity | All deployed runtimes | Cloud/platform admin | Terraform principal-set bindings in the companion platform branch | No |
| Extra project-scoped IAM for one Agent Identity | One deployed runtime | IAM admin or authorized automation identity | `<AGENT>_AGENT_IDENTITY_PROJECT_ROLES` consumed by `dev/iam/apply_agent_identity_iam.py` | No |
| Cloud Storage access for one Agent Identity | One deployed runtime | Storage/IAM admin or authorized automation identity | `<AGENT>_AGENT_IDENTITY_STORAGE_BUCKET_ROLES` consumed by `dev/iam/apply_agent_identity_iam.py`; bucket scope preferred | No |
| Read/create the agent runtime parameter and publish versions | Developer deployment flow; runtime reads it | Cloud or platform admin grants access; dev tooling creates agent-owned parameters | IAM plus `dev/config/bootstrap.py` / deployment preflight. The deploying identity **creates** parameters and publishes versions, so it needs write access such as `roles/parametermanager.parameterAdmin`; the baseline grants runtimes only `roles/parametermanager.parameterAccessor`, which reads. A first deployment fails at preflight without that grant. | No |
| Enable required Google Cloud APIs | Project | Cloud or platform admin, or developer with Service Usage permission | Terraform or `dev/config/bootstrap_dev.py` when enabled | No |
| Create/use the developer staging bucket | Developer deployment flow | Cloud or platform admin, or developer with Storage permission | Terraform/existing bucket or `dev/config/bootstrap_dev.py` when enabled | No |
| Create the optional BigQuery fixture dataset/table | Developer | Data/cloud admin, or developer with BigQuery create permissions | `dev/config/bootstrap_dev.py`; unnecessary when suitable test data already exists | No |
| Query BigQuery through delegated auth | Signed-in Gemini Enterprise user | Data/IAM admin | User IAM on the target BigQuery project/dataset/table; the agent cannot elevate it | No |
| Gemini Enterprise application | Registration flow | Gemini Enterprise administrator | Create/select the app in the Gemini Enterprise admin UI; copy its engine ID to `.env.dev` | Yes for initial app creation |
| OAuth consent screen / test-user configuration | Delegated-auth agents | Google Cloud / Google Auth Platform administrator | Google Auth Platform console | Yes |
| Dedicated OAuth client ID and client secret for each delegated agent | Registration flow | Google Cloud / Google Auth Platform administrator | Create a Web application client in Google Auth Platform with both documented redirect URIs | Yes |
| Store the OAuth client secret in Secret Manager | Registration flow | Registration script using existing Secret Manager access | `dev/register/register_agent.py` imports the initial secret when no stored version exists | No |
| Gemini Enterprise authorization resource | Delegated-auth agent | Registration flow using its caller permissions | `dev/register/register_agent.py` creates/reuses the per-agent authorization | No |
| Gemini Enterprise agent listing / registration | End users | Registration flow using its caller permissions | `dev/register/register_agent.py` creates/updates the app listing | No |

The deployment helpers never grant IAM to the developer or otherwise self-elevate. The
Agent Identity IAM helper only grants the roles explicitly configured for the selected
runtime. Its caller must already have permission to update the target project's or
bucket's IAM policy. If that permission is missing, have an administrator run the IAM
helper or grant through the approved platform process. The helper rejects roles/owner
and roles/editor.

### Per-agent Agent Identity IAM

Every remote runtime is created with Agent Identity, including agents with no additional
resource permissions. The identity is therefore independent of the optional IAM config.

An agent declares the access its own tools need, in its AgentSpec, beside the OAuth
scopes it asks the user for:

~~~python
"recipe_card_agent": AgentSpec(
    delegated_oauth_scopes=(),            # nothing runs as the signed-in user
    agent_identity_project_roles=(),      # nothing project-wide
    agent_identity_bucket_roles=(         # writes to its own output bucket
        BucketRoles("${RECIPE_CARD_BUCKET}", (STORAGE_OBJECT_ADMIN, STORAGE_BUCKET_READER)),
    ),
    runtime_env=(),                       # no runtime settings of its own
)
~~~

Both lists are versioned, so adding or removing a permission is a reviewable one-line
change and a fresh clone deploys with the access its tools require. A bucket is named
through a `${VARIABLE}` placeholder, so the repository says which bucket an agent writes
to without committing any project's bucket name; a placeholder that resolves to nothing
is skipped rather than guessed at.

These lists only add roles. Removing an entry does not revoke an existing grant;
an IAM administrator must review and remove it separately. The helper verifies the
runtime's reported effective identity before granting access and rejects basic
Owner/Editor roles and unsupported legacy bucket roles.

Environment variable names are derived from the agent package name:

~~~text
<AGENT>_AGENT_IDENTITY_ID=
<AGENT>_AGENT_IDENTITY_PROJECT_ROLES=
<AGENT>_AGENT_IDENTITY_STORAGE_BUCKET_ROLES=
~~~

For `auth_reference_agent` the prefix is `AUTH_REFERENCE_AGENT`.
`*_AGENT_IDENTITY_ID` is optional and acts only as an assertion. Normally leave it
empty; the IAM helper derives the exact principal from the deployed Reasoning Engine.
If supplied and it does not match the runtime's actual Agent Identity, the helper fails
before changing IAM.

Project roles are comma-separated:

~~~text
AUTH_REFERENCE_AGENT_AGENT_IDENTITY_PROJECT_ROLES=roles/logging.logWriter
~~~

Cloud Storage grants should normally be bucket-scoped:

~~~text
AUTH_REFERENCE_AGENT_AGENT_IDENTITY_STORAGE_BUCKET_ROLES=gs://agent-test-bucket=roles/storage.objectViewer
~~~

Multiple bucket bindings use semicolons between buckets and `|` between roles on the
same bucket. `deploy_dev.py` and `update_dev.py` invoke the helper automatically after
the runtime exists. To change only IAM later:

~~~bash
uv run --group dev python dev/iam/apply_agent_identity_iam.py --agent auth_reference_agent
~~~

If no per-agent IAM settings are present, this helper makes no IAM calls. The runtime
still has its unique Agent Identity and receives only the common project principal-set
roles from Terraform.

## Configure delegated OAuth

Use a separate OAuth client and authorization for each delegated agent in this template.
The defaults are `<package-name>-authz` for the authorization and
`<package-name>-oauth-client-secret` for its secret.

Configure the project's OAuth consent screen, including the test users and scopes
needed for your test. In Google Auth Platform, create a **Web application** client with
the name printed by register_agent.py. Add both callbacks used by this integration:

> **The consent screen is console-only, per-project and easy to miss.** No API edits
> its scope list, so `register_agent.py` prints the required scopes rather than
> applying them. Add them under **Google Auth Platform → Data Access → Add or remove
> scopes**, then **Update** and **Save**. The list is shared by every agent in the
> project, so a second agent asking for a scope already there needs no console change —
> which is why adding the first agent for a service feels like extra work and later
> ones do not. See [service scopes may need an
> administrator](#service-scopes-may-need-an-administrator).

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
uv run --group dev python -c "import sys; sys.path.insert(0,'dev'); \
from register.register_agent import main; \
sys.argv=['register_agent.py','--agent','auth_reference_agent']; main()"
~~~

When the stored secret is missing, registration imports the initial secret into Secret
Manager. Remove its raw value from .env.dev after a successful import. Existing stored
secrets take precedence over environment values; rotate them in Secret Manager.

Registration checks for a mismatched client ID and secret before creating an
authorization. Existing authorizations are reused; rerunning registration does not
change their OAuth settings. If the client or scopes change, review the authorization
as a separate change and retest consent.

Because an existing authorization is never reconciled, finish the consent screen
**before** the first registration. An authorization created against a consent screen
that is missing a scope is not repaired by fixing the screen afterwards: delete that
authorization and register again.

Verify what was created rather than assuming, since the authorization records the
scopes at creation time:

~~~bash
TOKEN=$(gcloud auth print-access-token)
curl -s -H "Authorization: Bearer $TOKEN" \
  -H "X-Goog-User-Project: <project-id>" \
  "https://discoveryengine.googleapis.com/v1alpha/projects/<project-number>/locations/global/authorizations/<package-name>-authz"
~~~

The `authorizationUri` in the response carries the `scope` parameter the user will be
asked to approve.

Each agent declares delegated service scopes in AgentSpec.delegated_oauth_scopes.
The BigQuery examples request the BigQuery scope plus the shared identity scopes.
Agent Identity tools do not add delegated scopes.

### Service scopes may need an administrator

The Data Access scope picker only lists scopes for APIs already **enabled on the
project**. Enable the service's API first and the scope becomes selectable; skip that
and it appears only under **Manually add scopes** at the bottom of the panel, where it
must be pasted verbatim. Enabling the API first is the shorter path.

Some scopes need more than the project owner:

- **Sensitive and restricted scopes** are flagged on the Data Access page. An app in
  *Testing* works for listed test users, but publishing may require Google verification.
- In a **Workspace or Cloud Identity organisation**, an admin can pre-authorize the
  client ID and its scopes under Admin console → Security → API controls, which
  suppresses the per-user prompt for internal users. Some organisations block user
  consent entirely, and then an administrator must allow the client before any user can
  authorize. This is an org-level change and is outside this repository.
- A managed MCP service may document a **broader scope than its read-only tools need**.
  Record the divergence in the agent README and request the narrower scope; do not widen
  it silently. See [monitoring_mcp_agent](agents/monitoring_mcp_agent/README.md).

An agent in *Testing* also needs its users listed under **Audience → Test users**, or
consent fails with `access_denied` no matter which scopes are configured.

The OAuth client's name identifies it in the console. The consent screen's app name
is what users see during sign-in.

## Test the deployed agents

Open an agent in Gemini Enterprise and send one of its starter prompts. For delegated
tools, complete **Authorize** and confirm BigQuery returns data the signed-in user can
access. Test another user with different permissions to check access boundaries.
Signing in alone does not prove delegated API access works.

For Cloud Storage, set agent_identity_bucket_name in the runtime parameter and configure
a bucket-scoped binding for the exact runtime identity, for example:

~~~text
AUTH_REFERENCE_AGENT_AGENT_IDENTITY_STORAGE_BUCKET_ROLES=gs://agent-test-bucket=roles/storage.objectViewer
~~~

Rerun the release or only `dev/iam/apply_agent_identity_iam.py`, then call
list_storage_objects and check its reported identity and returned objects.

basic_assistant exposes report_runtime_config, which returns the active parameter,
revision and model as configuration metadata, excluding secrets and prompt text. Only
that agent carries it: elsewhere it is a tool offered to the model on every request
that has nothing to do with the job the agent was deployed for. Add it to another agent
from `gemini_shared.config.tools` when diagnosing its configuration.

The optional BigQuery fixture provides five sample orders. Run config/bootstrap_dev.py to
prepare it, or use a dataset the test user can already query.
See [fixture settings](dev/README.md#bigquery-fixture).

## Produce a recipe card

Both recipe entry points build the same artefact from the same tools: a two- or
three-page PowerPoint deck published to Cloud Storage, returned as a link that opens
in a browser for anyone the bucket's IAM already allows.

~~~bash
uv run --group dev python dev/release_dev.py --agent recipe_card_agent
uv run --group dev python dev/release_dev.py --agent recipe_card_workflow
~~~

Both need a bucket to publish into and write access to it:

New cards express alternatives in `customizations`: each has a name, `replaces`
(exact core ingredient names), full replacement `ingredients` with quantities and
image paths, and `steps` containing a one-based step number and an `instructions`
list. A half-pork/half-shrimp option replacing 1 lb pork lists both 8 oz pork and
8 oz shrimp. The ingredient rail groups base and alternative quantities; affected
steps point to named Customized Steps checklists, which continue on extra pages.
Legacy `variations` and `variation_ingredients` remain readable. The first-page
banner uses editable freeforms extracted from the user-edited potsticker deck.

Image generation normally uses three calls: ingredient cutouts, a linked hero/step
photography batch, then a separate sketch. The sketch uses `mode="parallel"` and
`use_reference_images=false`, which sends no reference images. Larger batches may
be split within the tool's limits. The agent uses `retrieve` to check stored files
between batches and before rendering; this is agent-directed, not a fixed execution
gate. Missing-image placeholders are reserved for explicitly requested drafts.

~~~text
RECIPE_CARD_BUCKET=<project>-recipe-cards
RECIPE_CARD_BUCKET_LOCATION=
IMAGE_MODEL=
IMAGE_MODEL_LOCATION=global
RECIPE_CARD_AGENT_AGENT_IDENTITY_STORAGE_BUCKET_ROLES=gs://<bucket>=roles/storage.objectAdmin
RECIPE_CARD_WORKFLOW_AGENT_IDENTITY_STORAGE_BUCKET_ROLES=gs://<bucket>=roles/storage.objectAdmin
~~~

Create the output bucket with uniform bucket-level access before deploying. Grant
object access on that bucket; do not grant legacy bucket roles to Agent Identity.
Bucket creation belongs to the deploying administrator, not the runtime. A runtime
without bucket metadata access can still upload and download permitted objects.

The image models are served from the `global` location, not the region the runtime is
deployed to, which is why `IMAGE_MODEL_LOCATION` defaults to `global` and is forwarded
separately from `GOOGLE_CLOUD_LOCATION`.

### Card production is quota-bound

A full card needs roughly sixteen images and the default project quota is **two image
requests a minute** (`Generate content with image generation requests quota`,
1/min/project/model). One card therefore takes eight to ten minutes and only one can
run at a time. `gemini_shared.media` paces requests to that limit across the whole
process and retries throttling, empty responses and transient auth failures with
exponential backoff. Concurrency cannot beat a per-minute cap, so the pool is
deliberately small. Request a quota increase before demonstrating this live.

### How the card is laid out

`packages/recipe_cards` owns recipe validation, image publishing and presentation.
Its renderer separates request-scoped assets, drawing primitives and page layouts.
Both entry points call the same shared tools.

Image generation records its output URIs in session state. Pass the returned `run_id`
to subsequent image calls and to the render tool in the same session. The renderer
rejects local paths and images that are absent from that run's manifest, even if the
runtime could read them. A session retains its eight most recent runs.

Inputs are limited to three recipes per deck, 24 steps per recipe and 128 KiB of JSON.
Image batches allow 24 images with up to 48 per run. Downloads are limited to 12 MiB
and 4,194,304 pixels per image, with 64 MiB of image bytes per render. Repeated image
names are rejected; uploads use creation preconditions to avoid overwriting objects.
If cooking instructions do not fit, rendering fails with a request to split the step.
It never truncates those instructions. A failed render does not publish a deck.

Steps paginate in fours. Four or fewer steps give a two-page deck whose second page
carries the steps and the closing panels. Five to eight steps give three pages, where
the middle page is steps only and the closing panels move to the last. `cooking_tip`
accepts a list, one tip per step page, each about the steps on its own page; a page
without a tip closes the gap rather than drawing an empty banner.

Type sizes are fixed so every card reads the same. What varies is space: step blocks
are measured from their own text, then scaled together to use the page, and each
photograph is a share of its block. A page of four already fills the height, so a lone
trailing step gets a much larger image rather than leaving white beneath it. The
ingredient panel is drawn to the length of its list, and `variation_ingredients` are
listed under their own heading in the secondary colour so an optional item is never
mistaken for a required one.

### Iterate on the layout without spending quota

A card needs about sixteen images and the project admits two a minute, so generating
one to check a layout change is slow and wasteful. Render instead from images a
previous run already published: point `render_deck` at a recipe payload whose image
fields are the relative asset paths of an earlier run, convert the .pptx with LibreOffice and
look at the pages. Nothing is generated, and the whole loop takes seconds.

## Manage configuration

| Setting | Location | How a change takes effect |
|---|---|---|
| Model, instructions, log level, tool-call logging and tool limits | Parameter Manager | After the runtime cache expires. |
| Parameter address, model location and authorization ID | Runtime environment | Update the deployed runtime. |
| MCP endpoint and other per-agent runtime settings | AgentSpec.runtime_env | Update the deployed runtime. |
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
  "bigquery_query_row_limit": 100,
  "max_attempts": 3,
  "max_model_calls_per_request": 100,
  "context_compaction_threshold_tokens": 100000,
  "tool_call_logging": "off"
}
~~~

Replace the model placeholder before publishing. Storage limits allow 1–100 objects;
BigQuery row limits allow 1–10,000 rows. These limits apply to the custom tools.
The remote MCP server controls its own tool behavior.

Settings are cached for CONFIG_REFRESH_SECONDS. After a successful load, a failed
refresh retains the last valid settings for that same parameter and retries within
30 seconds or the configured refresh interval, whichever is shorter. The first failed
load raises an error. Switching parameters requires a successful read of the new one.

### Tool-call logging

ADK logs nothing that names a called tool, so which tools ran, and in what order, is
invisible by default. `tool_call_logging` turns that on through the shared limits
plugin, so it covers every agent and needs no per-agent change:

| Value | Recorded | Contains user data |
|---|---|---|
| `off` (default) | nothing | — |
| `names` | tool name, completion, error type | No |
| `argument_keys` | also which parameters were supplied | No — names only |
| `full` | also argument values, results and error messages | **Yes** |

A tool's arguments are whatever the signed-in user asked for: BigQuery SQL, monitoring
filters, storage paths. `full` writes those to Cloud Logging, so treat it as a
deliberate debugging step on one agent rather than a setting to leave on. The lower
levels answer "which tools ran" without disclosing what was asked.

Because each agent reads its own `<package-name>-config`, this can be raised for one
agent while the others stay quiet, and it takes effect after the cache interval with no
redeployment. An invalid value fails at config load rather than logging nothing
silently. The local equivalent is `TOOL_CALL_LOGGING`.

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

dev/config/settings.py forwards these environment keys to the runtime:

~~~text
CONFIG_PARAMETER
CONFIG_PARAMETER_LOCATION
CONFIG_REFRESH_SECONDS
BOOTSTRAP_MODEL
GEMINI_MODEL_LOCATION
GEMINI_ENTERPRISE_AUTHORIZATION_ID
RECIPE_CARD_BUCKET
RECIPE_CARD_BUCKET_LOCATION
IMAGE_MODEL
IMAGE_MODEL_LOCATION
~~~

The platform supplies the deployed project and runtime location; keep reserved runtime
variables out of the forwarded map.

This list is one shared value per key: whatever is set when a release runs is baked
into that runtime, whichever agent it is. A setting that belongs to one agent goes in
its spec instead.

### Per-agent runtime settings

`AgentSpec.runtime_env` declares the runtime environment one entry needs, versioned
beside its scopes and IAM, so a fresh clone deploys with it and no other agent's value
can override it:

~~~python
"monitoring_mcp_agent": AgentSpec(
    runtime_env=(
        ("MCP_SERVER_URL", CLOUD_MONITORING),
        ("ADK_DISABLE_JSON_SCHEMA_FOR_FUNC_DECL", "true"),
    ),
)
~~~

`runtime_env(spec)` merges these under the forwarded keys above. A name that is also in
RUNTIME_ENV_KEYS can still be overridden from the environment for a single run; a name
that is not — as `MCP_SERVER_URL` and `ADK_DISABLE_JSON_SCHEMA_FOR_FUNC_DECL` are not —
is never forwarded, so the spec's value always reaches the runtime. That is why each MCP
agent declares its own endpoint instead of sharing one variable: no leftover shell value
can retarget it. Those variables still affect local runs, which read them directly.

Add a key to RUNTIME_ENV_KEYS only when every agent should share its value.

Agent Identity IAM variables are deployment-time controls only. They are intentionally
not forwarded into the runtime environment.

## Repository layout

~~~text
agents/<agent>/
  prompt.md                  version-controlled instruction
  pyproject.toml             agent dependencies and wheel settings
  src/<agent>/
    agent.py                 construct the Agent and AdkApp
    config.py                resolve bootstrap settings
    tools/                   tool implementations and shared-tool exports
workflows/<workflow>/
  pyproject.toml             workflow dependencies and wheel settings
  src/<workflow>/
    workflow.py              compose the stages into a SequentialAgent and AdkApp
    config.py                resolve bootstrap settings
    stages/                  one module per stage, each with its own instruction
packages/gemini_shared/src/gemini_shared/
  auth/                      delegated credential provider and token readers
  config/                    bootstrap settings, live cache, callbacks and status tool
  connectors/                shared Google Cloud clients
  limits/                    request, retry and compaction plugin
  media/                     batched image generation with pacing and retries
  runtime/                   shared model and application factories
  mcp/mcp_auth/              authenticated Streamable HTTP toolsets
  mcp/mcp_google_cloud/      managed endpoints and BigQuery tool allowlist
packages/recipe_cards/src/recipe_cards/
  schema.py                  bounded recipe models
  runs.py                    session-owned runs and asset manifests
  images.py, publish.py       shared ADK tools
  rendering/                 asset handling, drawing primitives and page layouts
  style/                     bundled reference images
dev/                         local, packaging, deployment, IAM and registration scripts
tests/                       import, validation and behavior tests
~~~

Each archive includes one entry point and the packages it imports. Recipe agents and
workflows share tools through recipe_cards. Packaging excludes caches and bytecode,
rejects symlinks and normalizes timestamps and ownership. Unchanged inputs produce
identical archive bytes. Archive creation and SDK staging use the same source manifest
from dev/deploy/sources.py. Requirements are exported from uv.lock for the selected
workspace package, including its transitive dependencies; there is no second dependency
list in the registry. Outputs go under ignored artifacts/; deployment state goes
under ignored dev/.state/.

The recipe renderer separates theme, drawing, ingredients, overview, steps and deck
assembly. Lists longer than the first ingredient panel continue on additional pages,
including optional variation ingredients. Quantities and ingredient names are never
silently shortened: text that cannot fit returns a correction request. Reuse its run_id
when correcting a card; each new run has its own retry budget.
After `max_attempts` failed render attempts, the tool returns `status: failed` with no deck
URL. The model can explain the problem without the request ending in an unhandled
layout exception. Further calls for that run return the same failure without rendering.

### Request and retry limits

`max_attempts` includes the initial attempt: the default of 3 permits two retries.
It controls Gemini transport retries, transient image-generation retries and recipe
layout correction attempts. Image generation disables SDK-internal retries to avoid
multiplying its outer retry budget. Non-retryable errors are not retried.

`max_model_calls_per_request` defaults to 100 and caps ADK model calls across the entire
user request, including all workflow stages. The shared application factory installs
the limit plugin. Callers may request a lower limit but cannot raise the server's cap.
Exceeding it stops the request with ADK's `LlmCallsLimitExceededError`, not another model
call. This counts orchestration calls, not individual image requests inside a tool;
image batch and per-run limits still apply separately. It is not a dollar or token cap.

Publish these fields in the existing Parameter Manager JSON. Old versions without
them use the defaults. A request snapshots the model-call ceiling when it starts;
later requests see refreshed settings after the cache expires. Attempt limits are
read when each operation starts. basic_assistant's `report_runtime_config` includes
both settings.
Local equivalents are `MAX_ATTEMPTS` and `MAX_MODEL_CALLS_PER_REQUEST`.

Deploy this code once before expecting live parameter edits to enforce the new limits.
`context_compaction_threshold_tokens` defaults to 100000. At request startup the
plugin enables ADK token-based compaction using that threshold, retaining the six
most recent events (and any extra events needed to preserve tool-call/response pairs).
ADK summarizes older history before preparing a subsequent model call when the last
reported prompt-token usage reaches the threshold (or uses ADK's estimate when usage
metadata is unavailable). This is not a strict token ceiling:
a large new input can cross the threshold before usage is reported, and recent content
may remain larger than it. Summaries can lose detail, so original documents and recipe
assets remain the source of truth. Compaction does not reset the request's call budget.
Summarizer calls are additional model usage outside ADK's orchestration-call counter.
The local equivalent is `CONTEXT_COMPACTION_THRESHOLD_TOKENS`.
Existing Parameter Manager versions that explicitly set a 20-call ceiling retain it;
publish 100 there to raise that value. No live parameters are changed by a code push.

## Add an agent

For a Google-managed MCP using the signed-in user's OAuth token, follow the
[delegated MCP contributor guide](docs/adding-delegated-mcp-agent.md). Start from
`bigquery_mcp_agent` for that case; the steps below describe the general scaffold.

1. Copy agents/basic_assistant/. Rename the package directory, project name in
   pyproject.toml and wheel path. Set a stable agent name in agent.py.
2. Write prompt.md. Keep instructions specific to the task and available tools.
3. Add tools under tools/ and export them from tools/__init__.py. Keep tool logic
   separate from agent construction. Share reusable behavior in gemini_shared.
4. Add an AgentSpec to AGENTS in dev/registry.py. Supply the package name, import module,
   display name, source paths and registration text.
   For delegated tools, declare AUTHORIZATION_ID_ENV and the required service scopes.
   Leave source_root at its default; only a workflow overrides it.
5. Add dependencies to the agent's pyproject.toml and update uv.lock with uv sync.
   gemini-shared provides the shared SDK and Agent Identity dependencies; use
   gemini-shared[mcp] for the MCP extra. Deployment requirements come from the lock.
6. Add the source directory to pytest's pythonpath in the root pyproject.toml, add an
   import test and test the new tools. Registry-based tests include the agent automatically.
7. Run uv sync --all-packages --group dev, lint and tests. Try the local runner, then
   release the agent and test it in Gemini Enterprise.

Keep runtime_instruction, apply_runtime_model and the shared create_model/create_app factories from the copied
agent. Tool functions need type hints and short docstrings: ADK uses them to describe
the tools to the model. Document arguments the model must supply and return
JSON-compatible values. The BigQuery example converts dates, decimals and byte strings.

The unit suite uses dummy settings and anonymous credentials through tests/conftest.py.
Run it with `uv run --group dev pytest`; no gcloud login or live project is required.

### Choose tool authentication

| Access needed | Implementation |
|---|---|
| A shared capability available through the agent | Use runtime credentials. Every remote runtime already has Agent Identity; configure exact-agent IAM only for the resources that agent needs. |
| Access limited to the signed-in user's permissions | Use a delegated session token. Configure the authorization and scopes for that service. |

Developer ADC, deployed Agent Identity and delegated user tokens are separate
credentials. Grant each only the access needed. The deployment scripts never grant IAM
to the developer. Per-agent IAM is applied only when explicitly configured and only by
a caller that already has permission to change the target IAM policy.

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

Declare the endpoint in the spec's `runtime_env` as `MCP_SERVER_URL` rather than relying
on the shared variable, so no other agent's value can retarget where the user's bearer
token is sent.

Check what the server's tools cost in tokens before deploying. ADK sends each tool's
`outputSchema` to the model as `response_json_schema`, and a server publishing large
response schemas can exceed the model's input limit before any tool runs, failing every
request with `400 INVALID_ARGUMENT`. Cloud Monitoring's nine tools carry ~79k tokens of
response schemas against ~7.7k for their inputs. Declare
`ADK_DISABLE_JSON_SCHEMA_FOR_FUNC_DECL=true` in that agent's `runtime_env` to send input
schemas only, keeping every tool. Read the sizes from the server's `tools/list` response
rather than assuming.

Always supply an explicit allowlist for application toolsets. tool_filter=None exposes
all tools returned by the server, including future additions. The BigQuery allowlist
contains five read-only tools and excludes execute_sql. Filtering limits tools shown
to the model; server-side permissions still control access.

Headers use the current session token for each request. Tool descriptions are cached
for five minutes by default. Keep shared endpoints, scopes and tool lists under
gemini_shared/mcp/ when multiple agents use them.

## Add a workflow

A workflow is deployed exactly like an agent: the same runtime, the same Agent
Identity, the same Parameter Manager entry and the same registration. Only two things
differ, so most of this repository does not distinguish them.

1. It lives under `workflows/` rather than `agents/`, and its `AgentSpec` sets
   `source_root="workflows"`. That field is the only registry change a workflow needs.
2. Its root object is a composition — `SequentialAgent`, `ParallelAgent` or
   `LoopAgent` — rather than a single `Agent` holding tools.

Build it from stages. Each stage is an `LlmAgent` with an `output_key`, which publishes
its result into session state, and the next stage reads it by name from its own
instruction:

~~~python
recipe_writer = LlmAgent(..., output_key="recipe")  # writes state["recipe"]
image_director = LlmAgent(..., instruction="...{recipe}...")  # reads it back

root_agent = SequentialAgent(
    name="recipe_card_workflow",
    sub_agents=[recipe_writer, image_director, card_renderer],
)
app = AdkApp(agent=root_agent, enable_tracing=True)
~~~

Put reusable tools in a shared package and depend on it from both entry points.
Declare that package in `[tool.uv.sources]` and include its source path in each spec's
`extra_packages`. The recipe workflow depends on `recipe-cards`, not on the
conversational agent. Packaging tests check that its tools and style images ship
without the agent package.

The recipe workflow uses stage instructions and the bootstrap model from code and
environment settings; changing its Parameter Manager entry does not change those
stages. Update the deployment to change them. A validation callback checks the writer's
recipe before image generation. Shared tool validation and deployment checks cover
both entry points.

Use a workflow when stage order is fixed. Model outputs still vary and a stage can
fail, so validate the data passed between stages. Use a conversational agent when
the user's request should determine which tool runs next.

## Code conventions

Use Python 3.12-compatible code with type hints on shared functions. Ruff checks import
order, PEP 8 rules and common correctness and security issues, with a 100-character
line limit. Comments should explain constraints or decisions that the code does not.

Keep domain logic with its agent and reusable logic in the shared package. Pass
subprocess arguments as a list without a shell. Validate external input before cloud
operations. Never log tokens or secrets, commit credentials or .env files, or add IAM
self-grants to application code. The dev/ workflow is limited to development projects.
