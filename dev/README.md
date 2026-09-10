# Developer scripts

Run these scripts from the repository root. Remote commands require ENVIRONMENT=dev
and existing deployment permissions. Follow the root [setup guide](../README.md) for
authentication, OAuth client setup, Agent Identity IAM and runtime configuration.

~~~bash
uv run --group dev python dev/run_local.py --agent basic_assistant
uv run --group dev python dev/release_dev.py --agent basic_assistant
uv run --group dev python dev/release_dev.py --agent recipe_card_workflow
~~~

Every script takes `--agent <name>`, and a workflow is named the same way: the registry
holds agents and workflows together, because they deploy identically. `source_root` on
the spec is the only thing that tells them apart, and only the prompt path and the
delegated-auth source scan consult it.

The local runner reads dev/.env.local; remote commands read dev/.env.dev.
Copy the matching example file and fill in the required values. Shell variables take
precedence. Both files and dev/.state/ are ignored by Git.

## Layout

Scripts are grouped by what they do. release_dev.py runs the normal sequence, so
it and the local runner sit at the top level; the rest are the individual steps
it calls, each also runnable on its own.

~~~text
dev/
  release_dev.py       preflight, package, deploy or update, IAM, then register
  run_local.py         run one agent on the workstation, no deployment
  registry.py          agent and workflow metadata
  paths.py, gcp.py      repository paths and shared gcloud execution
  deploy/              build an archive and create or update a runtime
  iam/                 exact Agent Identity IAM after the runtime exists
  register/            publish a runtime into a Gemini Enterprise app
  config/              environment parsing and project preflight
  fixtures/            optional sample data for a dev sandbox
~~~

| Script | Purpose |
|---|---|
| release_dev.py | Run preflight, package, deploy or update, optional Agent Identity IAM, then register. |
| run_local.py | Run one agent or workflow against real APIs using workstation credentials. |
| deploy/package_agent.py | Build an archive with one entry point and the packages it imports. |
| deploy/deploy_dev.py | Create a new runtime with Agent Identity and save its resource name. |
| deploy/update_dev.py | Update the runtime from saved state or DEV_REASONING_ENGINE. |
| iam/apply_agent_identity_iam.py | Apply explicitly configured roles to the exact deployed Agent Identity. |
| register/register_agent.py | Register the runtime and create a missing delegated authorization. |
| config/bootstrap_dev.py | Check the sandbox and prepare optional BigQuery sample data. |

Deployment creates a missing runtime parameter and publishes changes to prompt.md.
The release script chooses an update when saved state or DEV_REASONING_ENGINE matches
the selected project and region. State lives at
dev/.state/<project-number>/<region>/<agent>.json. Matching legacy state migrates on
read; legacy state from another scope is ignored. Explicit overrides are checked before
preflight; saved state is checked before any runtime update. Use --skip-register to deploy without
publishing into an app.

| Imported module | Purpose |
|---|---|
| registry.py | Agent and workflow metadata, source paths, OAuth scopes and exact identity grants. |
| paths.py, gcp.py | Repository paths and shared gcloud execution/project resolution. |
| deploy/state.py | Project and region validation, state lookup and migration. |
| deploy/sources.py | One validated source manifest for archives and SDK staging. |
| deploy/dependencies.py | Export runtime requirements from uv.lock. |
| deploy/runtime.py | SDK client, existing app and deployment configuration. |
| config/settings.py | Local and remote environment contract. |
| register/http.py, register/oauth.py | Paginated JSON API access and OAuth client configuration. |
| config/environment.py | Boolean and placeholder parsing. |
| config/bootstrap.py | Authentication, project, API, bucket and parameter checks. |
| fixtures/bigquery_fixture.py | Sample dataset creation, schema validation and seeding. |

Adding an entry to AGENTS in registry.py is what makes it visible to every script above,
whether it is an agent or a workflow. Imports resolve against dev/, so a script in a
subfolder puts that directory on sys.path before importing the shared dev modules.

## Order of operations

Terraform first, then these scripts. The platform stack grants the roles every
Agent Identity needs, and a runtime deployed before it exists will start but fail
when it reads its own configuration. For a sandbox with no platform stack, the
scripts can grant that baseline themselves; see below.

| # | What | Where | When |
|---|---|---|---|
| 1 | APIs, baseline IAM, Secret Manager, observability | `infrastructure/` | Once per project |
| 2 | Gemini Enterprise app | Console | Once per project; copy its engine ID |
| 3 | OAuth client and consent screen | Console | Once per delegated agent |
| 4 | Project, staging bucket, optional fixture | `config/bootstrap_dev.py` | Once per developer sandbox |
| 5 | Package, deploy, IAM, register | `release_dev.py --agent <name>` | Every release |

Steps 2 and 3 have no API and must be done by hand; `register/register_agent.py`
prints exactly what to create when an OAuth client is missing. Everything else is
automated. Step 4 is optional when the project and bucket already exist, because
`release_dev.py` runs the same preflight itself.

To ship a change to one agent, only step 5 is needed:

~~~bash
uv run --group dev python dev/release_dev.py --agent recipe_card_agent
~~~

### Running without the Terraform stack

These scripts can stand up a sandbox end to end. `config/bootstrap_dev.py` can create
the project, enable the APIs and create the staging bucket, and it can also grant the
roles every Agent Identity in the project needs:

~~~text
DEV_CREATE_PROJECT_IF_MISSING=true
DEV_BILLING_ACCOUNT_ID=<billing-account>
DEV_ENABLE_REQUIRED_APIS=true
DEV_CREATE_STAGING_BUCKET_IF_MISSING=true
DEV_GRANT_AGENT_IDENTITY_BASELINE=true
~~~

~~~bash
uv run --group dev python dev/config/bootstrap_dev.py
uv run --group dev python dev/release_dev.py --agent basic_assistant
~~~

That baseline matters more than it looks. Every agent reads its model and instruction
from Parameter Manager under its own identity, so without it an agent deploys, starts,
and then fails on its first request with no permission to read anything. The roles
granted at project scope are `aiplatform.expressUser`,
`serviceusage.serviceUsageConsumer` and `parametermanager.parameterAccessor`.
`storage.objectViewer` is granted on DEV_STAGING_BUCKET only, so runtimes can read
their source archives. Both Terraform and this helper read those defaults from
infrastructure/runtime_iam_policy.json. The principal set covers future runtimes too.
Business data buckets, including the auth reference agent's sample bucket, require
explicit grants to the exact agent identity.

When upgrading an existing sandbox, grant staging and required business-bucket access
first, then have its IAM administrator remove the former project-wide objectViewer
binding. This helper only adds bindings. Terraform-managed projects remove the old
binding on apply when it is no longer in agent_identity_project_roles; explicit
overrides must also be updated.

`DEV_GRANT_AGENT_IDENTITY_BASELINE` is false by default and the caller needs project
IAM admin to use it. Leave it false wherever the platform stack is applied: IAM there
belongs to Terraform, and granting the same bindings from two places makes it unclear
which one owns them. Use it for a sandbox, a demo project or a first look at the
template, and apply the platform stack for anything shared.

## Sandbox controls

Bootstrap and the deployment preflight use these controls:

~~~text
DEV_CREATE_PROJECT_IF_MISSING=false
DEV_BILLING_ACCOUNT_ID=
DEV_PROJECT_FOLDER_ID=
DEV_PROJECT_ORGANIZATION_ID=
DEV_ENABLE_REQUIRED_APIS=true
DEV_CREATE_STAGING_BUCKET_IF_MISSING=true
DEV_STAGING_BUCKET_LOCATION=
~~~

Project creation is opt-in and requires a billing account. Set at most one of the
folder and organization IDs. API enablement and missing staging-bucket creation are
enabled by default; set their flags to false to require pre-existing resources.
An empty staging location uses GOOGLE_CLOUD_LOCATION.

The CLI account needs permission for enabled setup operations. Python clients use ADC
for Parameter Manager and the fixture. Bootstrap reuses existing resources without
assigning IAM or changing billing on an existing project.

Use the platform stack in infrastructure/ for shared platform resources and baseline IAM.
Review its grants before deploying an agent with new resource-access requirements.

## Agent Identity IAM

Every remote Agent Engine is created with `identity_type=AGENT_IDENTITY`, so every
deployed agent receives its own Google-managed Agent Identity even when no additional
IAM is configured.

Agent-specific IAM is optional and parameterized from the agent package name:

~~~text
<AGENT>_AGENT_IDENTITY_ID=
<AGENT>_AGENT_IDENTITY_PROJECT_ROLES=
<AGENT>_AGENT_IDENTITY_STORAGE_BUCKET_ROLES=
~~~

For `auth_reference_agent` these become:

~~~text
AUTH_REFERENCE_AGENT_AGENT_IDENTITY_ID=
AUTH_REFERENCE_AGENT_AGENT_IDENTITY_PROJECT_ROLES=
AUTH_REFERENCE_AGENT_AGENT_IDENTITY_STORAGE_BUCKET_ROLES=
~~~

`*_AGENT_IDENTITY_ID` is an optional assertion, not the source of identity. Normally
leave it empty. The helper derives the exact principal from the deployed Reasoning
Engine. If a value is supplied and does not match, the command stops before changing
IAM.

Project roles are comma-separated. Use them only when project scope is actually
required:

~~~text
AUTH_REFERENCE_AGENT_AGENT_IDENTITY_PROJECT_ROLES=roles/logging.logWriter
~~~

Cloud Storage bindings are resource-scoped and use
`gs://bucket=role|role;gs://other=role`:

~~~text
AUTH_REFERENCE_AGENT_AGENT_IDENTITY_STORAGE_BUCKET_ROLES=gs://agent-test-bucket=roles/storage.objectViewer
~~~

`deploy_dev.py` and `update_dev.py` invoke the IAM helper automatically after the
runtime exists. You can also rerun only IAM after changing these settings:

~~~bash
uv run --group dev python dev/iam/apply_agent_identity_iam.py --agent auth_reference_agent
~~~

If none of the per-agent IAM variables is set, the helper makes no IAM calls. The
Agent Identity still exists and receives only the common principal-set roles from the
Terraform platform stack.

The identity running this helper must already be allowed to change IAM on the target
project or bucket. The helper does not grant permissions to itself and rejects
`roles/owner` and `roles/editor`. Prefer resource-scoped bindings for data access.

## BigQuery fixture

Only config/bootstrap_dev.py prepares the fixture; the release preflight does not.

~~~text
DEV_PREPARE_BIGQUERY_FIXTURE=true
DEV_CREATE_BIGQUERY_FIXTURE_IF_MISSING=true
DEV_BIGQUERY_DATASET_ID=gemini_agent_template_dev
DEV_BIGQUERY_TABLE_ID=sample_orders
DEV_BIGQUERY_LOCATION=
~~~

An empty location uses GOOGLE_CLOUD_LOCATION. Bootstrap checks the BigQuery API and
reuses or creates the dataset and table. It validates an existing table's schema and
inserts five sample rows only when the table is empty. Non-empty tables are left
unchanged; a schema mismatch stops the command.

The developer needs permissions to create and inspect the fixture. The Gemini
Enterprise test user separately needs permission to create query jobs and read it.
The helper grants neither. Disable DEV_PREPARE_BIGQUERY_FIXTURE when using other data.
The agents discover datasets rather than hardcoding the sample table.

## Runtime parameter checks

Deployment defaults to the selected agent's `<package-name>-config` parameter. Leave
CONFIG_PARAMETER empty unless overriding it for a run. Delegated agents also default
to their own `<package-name>-authz` authorization.

config/bootstrap_dev.py checks a runtime parameter only when CONFIG_PARAMETER is set.
Deployment supplies the agent spec, so it can seed and synchronize the source prompt.
Other live settings remain unchanged when a prompt is published.

To change model settings or limits without updating code, publish a Parameter Manager
version and wait for the cache interval.
See [configuration management](../README.md#manage-configuration).
