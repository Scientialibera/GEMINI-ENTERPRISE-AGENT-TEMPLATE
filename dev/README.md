# Developer scripts

Run these scripts from the repository root. Remote commands require ENVIRONMENT=dev
and existing IAM grants. Follow the root [setup guide](../README.md) for authentication,
OAuth client setup and runtime configuration.

~~~bash
uv run --group dev python dev/run_local.py --agent basic_assistant
uv run --group dev python dev/release_dev.py --agent basic_assistant
~~~

The local runner reads dev/.env.local; remote commands read dev/.env.dev.
Copy the matching example file and fill in the required values. Shell variables take
precedence. Both files and dev/.state/ are ignored by Git.

## Layout

Scripts are grouped by what they do. release_dev.py runs the whole sequence, so
it and the local runner sit at the top level; the rest are the individual steps
it calls, each also runnable on its own.

~~~text
dev/
  release_dev.py       preflight, package, deploy or update, then register
  run_local.py         run one agent on the workstation, no deployment
  common.py            agent registry, deployment settings, package paths, state
  deploy/              build an archive and create or update a runtime
  register/            publish a runtime into a Gemini Enterprise app
  config/              environment parsing and project preflight
  fixtures/            optional sample data for a dev sandbox
~~~

| Script | Purpose |
|---|---|
| release_dev.py | Run preflight, package, deploy or update, then register. |
| run_local.py | Run one agent against real APIs using workstation credentials. |
| deploy/package_agent.py | Build an archive with one agent and the shared package. |
| deploy/deploy_dev.py | Create a new runtime and save its resource name. |
| deploy/update_dev.py | Update the runtime from saved state or DEV_REASONING_ENGINE. |
| register/register_agent.py | Register the runtime and create a missing delegated authorization. |
| config/bootstrap_dev.py | Check the sandbox and prepare optional BigQuery sample data. |

Deployment creates a missing runtime parameter and publishes changes to prompt.md.
The release script chooses an update when saved agent state exists. Use --skip-register
to deploy without publishing into an app.

| Imported module | Purpose |
|---|---|
| common.py | Agent registry, deployment settings, package paths and state. |
| config/environment.py | Boolean and placeholder parsing. |
| config/bootstrap.py | Authentication, project, API, bucket and parameter checks. |
| fixtures/bigquery_fixture.py | Sample dataset creation, schema validation and seeding. |

Adding an agent to AGENTS in common.py is what makes it visible to every script
above. Imports resolve against dev/, so a script in a subfolder puts that
directory on sys.path before importing common.

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
for Parameter Manager and the fixture. The scripts reuse existing resources without
assigning IAM or changing billing on an existing project.

Use the companion Terraform stack for shared platform resources and IAM. Review its
grants before deploying an agent with new resource-access requirements.

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
