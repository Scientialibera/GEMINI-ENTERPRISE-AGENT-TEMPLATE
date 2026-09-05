"""Project-specific configuration for the template pro-code agent.

Copy this file to config.py and fill in your own values. config.py is
gitignored — it is where your project, resource names and test identities
live, and it must never be committed.
"""

# Google Cloud project and region the agent deploys to.
PROJECT_ID = "<PROJECT_ID>"
PROJECT_NUMBER = "<PROJECT_NUMBER>"
LOCATION = "us-central1"

# Cloud Storage bucket used by 01_deploy.py and 02_update.py as the Agent Runtime staging
# bucket, and read by template_agent_identity_tool as a worked example.
AGENT_IDENTITY_BUCKET_NAME = "<PROJECT_ID>-agent-runtime-staging"

# Parameter Manager is the source of truth for mutable runtime behavior.
# Keep the version as "latest" for TTL-based updates without redeployment, or
# pin a named version when production change control requires explicit rollout.
RUNTIME_CONFIG_PARAMETER_ID = "pro-code-agent-config"
RUNTIME_CONFIG_PARAMETER_VERSION = "latest"
RUNTIME_CONFIG_CACHE_SECONDS = 300

# Gemini Enterprise delegated auth: the discoveryengine `authorizations`
# resource ID referenced by the registered agent's authorizationConfig and
# read by the template_bigquery_* tools through session state.
GEMINI_ENTERPRISE_AUTHORIZATION_ID = "template-pro-code-agent-authz"

# Gemini Enterprise app and registered agent, once you have created them.
DISCOVERY_ENGINE_APP_ID = "<DISCOVERY_ENGINE_APP_ID>"
REGISTERED_AGENT_ID = "<REGISTERED_AGENT_ID>"

# Copy this from deployment_result.json after the first 01_deploy.py run.
# It is used by 02_update.py.
REASONING_ENGINE_ID = "<REASONING_ENGINE_ID>"
