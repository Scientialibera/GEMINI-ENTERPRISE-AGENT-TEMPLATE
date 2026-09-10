"""Agent metadata and declared capabilities, shared by every developer command."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from gemini_shared.config.bootstrap import AUTHORIZATION_ID_ENV
from gemini_shared.mcp.mcp_google_cloud import BIGQUERY, CLOUD_MONITORING
from paths import ROOT

ENVIRONMENT_LABEL = "dev"

GCS_URI_PREFIX = "gs://"

DELEGATED_AUTH_MARKER = AUTHORIZATION_ID_ENV

IDENTITY_OAUTH_SCOPES = ("openid", "email", "profile")

BIGQUERY_SCOPE = "https://www.googleapis.com/auth/bigquery"

CLOUD_PLATFORM_SCOPE = "https://www.googleapis.com/auth/cloud-platform"

CLOUD_STORAGE_READONLY_SCOPE = "https://www.googleapis.com/auth/devstorage.read_only"

# The Cloud Monitoring MCP guide names the read-write "monitoring" scope; the API's
# own scope list defines this read-only one, which covers the selected tools.
CLOUD_MONITORING_READONLY_SCOPE = "https://www.googleapis.com/auth/monitoring.read"

STORAGE_OBJECT_VIEWER = "roles/storage.objectViewer"

STORAGE_OBJECT_ADMIN = "roles/storage.objectAdmin"

LOGGING_LOG_WRITER = "roles/logging.logWriter"

BIGQUERY_JOB_USER = "roles/bigquery.jobUser"

BIGQUERY_DATA_VIEWER = "roles/bigquery.dataViewer"


@dataclass(frozen=True, slots=True)
class BucketRoles:
    """Roles this agent's identity needs on one bucket.

    ``bucket`` may name an environment variable as ``${NAME}``, so a spec can
    say which bucket without committing a project's actual bucket name.
    """

    bucket: str
    roles: tuple[str, ...]

    def resolved_bucket(self) -> str:
        """Return the bucket URI, substituting a ${NAME} placeholder."""
        name = self.bucket
        if name.startswith("${") and name.endswith("}"):
            name = os.getenv(name[2:-1], "").strip()
        if not name:
            return ""
        return name if name.startswith(GCS_URI_PREFIX) else f"{GCS_URI_PREFIX}{name}"


@dataclass(frozen=True, slots=True)
class AgentSpec:
    package_name: str
    module: str
    display_name: str
    extra_packages: tuple[str, ...]
    required_remote_bootstrap_env: tuple[str, ...] = ()
    # Service scopes beyond the identity scopes; exclude Agent Identity tools.
    # These are what the signed-in user consents to, so add a service here only
    # when a tool calls it with the user's own token.
    delegated_oauth_scopes: tuple[str, ...] = ()
    # Roles this agent's own runtime identity needs, beyond the baseline every
    # Agent Identity in the project already has from Terraform. Declared here
    # rather than in the environment so a fresh clone deploys with the access
    # its tools require. The per-agent environment variables still override.
    agent_identity_project_roles: tuple[str, ...] = ()
    agent_identity_bucket_roles: tuple[BucketRoles, ...] = ()
    # Runtime environment this entry needs, beyond the shared forwarding list.
    # Declared here rather than in the environment because RUNTIME_ENV_KEYS is
    # one shared value per key: a flag left in .env.dev for one agent would be
    # baked into whichever agent is released next. These are per-entry and
    # versioned, so a fresh clone deploys with the settings its tools require.
    # The environment still wins, so a single run can override one.
    runtime_env: tuple[tuple[str, str], ...] = ()
    # Gemini Enterprise registration metadata, used by register_agent.py.
    registration_description: str = ""
    invocation_description: str = ""
    starter_prompts: tuple[str, ...] = ()
    # Directory holding this entry's source. A workflow is deployed exactly like
    # an agent — same runtime, same identity, same parameter — so it differs
    # only in where its package lives and in what it composes internally.
    source_root: str = "agents"

    @property
    def config_parameter_id(self) -> str:
        """Default Parameter Manager name for this agent."""
        return f"{self.package_name}-config"

    @property
    def authorization_id(self) -> str:
        """Default Gemini Enterprise authorization name for this agent."""
        return f"{self.package_name}-authz"

    @property
    def uses_delegated_auth(self) -> bool:
        """Whether the spec requires a delegated user token."""
        return AUTHORIZATION_ID_ENV in self.required_remote_bootstrap_env

    @property
    def oauth_client_name(self) -> str:
        """Suggested OAuth client name in the console."""
        return f"{self.display_name} ({ENVIRONMENT_LABEL})"

    @property
    def oauth_client_id_env(self) -> str:
        """Per-agent OAuth client ID override."""
        return f"{self.env_prefix}_OAUTH_CLIENT_ID"

    @property
    def oauth_client_secret_name_env(self) -> str:
        """Environment variable naming the Secret Manager secret for that client."""
        return f"{self.env_prefix}_OAUTH_CLIENT_SECRET_NAME"

    @property
    def oauth_client_secret_env(self) -> str:
        """Environment variable for importing the initial client secret."""
        return f"{self.env_prefix}_OAUTH_CLIENT_SECRET"

    @property
    def default_oauth_secret_name(self) -> str:
        """Secret Manager secret this agent's OAuth client secret belongs in."""
        return f"{self.package_name}-oauth-client-secret"

    @property
    def oauth_scopes(self) -> tuple[str, ...]:
        """Full scope list for this agent's authorization, identity included."""
        return IDENTITY_OAUTH_SCOPES + self.delegated_oauth_scopes

    @property
    def env_prefix(self) -> str:
        """Per-agent prefix for environment variables, derived from the package."""
        return self.package_name.upper().replace("-", "_")

    @property
    def prompt_path(self) -> Path:
        """Source prompt published to Parameter Manager during deployment."""
        return ROOT / self.source_root / self.module.split(".")[0] / "prompt.md"

    def read_prompt(self) -> str:
        """Return the agent's instruction, or empty when it has no prompt file."""
        path = self.prompt_path
        return path.read_text(encoding="utf-8").strip() if path.exists() else ""


AGENTS: dict[str, AgentSpec] = {
    "basic_assistant": AgentSpec(
        package_name="basic-assistant",
        module="basic_assistant.agent",
        display_name="Basic Assistant",
        extra_packages=(
            "agents/basic_assistant/src/basic_assistant",
            "packages/gemini_shared/src/gemini_shared",
        ),
        registration_description=(
            "Basic ADK assistant with model settings and instructions managed in Parameter Manager."
        ),
        invocation_description=(
            "Check the active configuration revision, parameter resource and model."
        ),
        starter_prompts=(
            "Report the active config revision and model.",
            "Which Parameter Manager resource is this agent reading?",
        ),
    ),
    "auth_reference_agent": AgentSpec(
        package_name="auth-reference-agent",
        module="auth_reference_agent.agent",
        display_name="Auth Reference Agent",
        extra_packages=(
            "agents/auth_reference_agent/src/auth_reference_agent",
            "packages/gemini_shared/src/gemini_shared",
        ),
        required_remote_bootstrap_env=(AUTHORIZATION_ID_ENV,),
        # Storage uses Agent Identity and needs no delegated scope.
        delegated_oauth_scopes=(BIGQUERY_SCOPE,),
        registration_description=(
            "Read Cloud Storage with Agent Identity and query BigQuery with the signed-in "
            "user's delegated credentials."
        ),
        invocation_description=(
            "Inspect Cloud Storage objects or query BigQuery and check the identity used."
        ),
        starter_prompts=(
            "Which identity is this agent running as?",
            "List the BigQuery datasets and tables I can access.",
            "Show total revenue by region from the sample orders table.",
        ),
    ),
    "recipe_card_agent": AgentSpec(
        package_name="recipe-card-agent",
        module="recipe_card_agent.agent",
        required_remote_bootstrap_env=("RECIPE_CARD_BUCKET",),
        display_name="Recipe Card Agent",
        extra_packages=(
            "agents/recipe_card_agent/src/recipe_card_agent",
            "packages/recipe_cards/src/recipe_cards",
            "packages/gemini_shared/src/gemini_shared",
        ),
        # Cards live under one use-case prefix, so the bucket can serve more
        # than this agent and a dish's versions are discoverable together.
        runtime_env=(("RECIPE_CARD_PREFIX", "recipe-cards"),),
        # The output bucket must already exist before granting object access.
        agent_identity_bucket_roles=(
            BucketRoles(
                "${RECIPE_CARD_BUCKET}",
                (STORAGE_OBJECT_ADMIN,),
            ),
        ),
        registration_description=(
            "Produces print-ready recipe cards for a pantry business. Writes the recipe, "
            "generates consistent unbranded food photography in batches, and publishes an "
            "editable PowerPoint deck to Cloud Storage under its own Agent Identity."
        ),
        invocation_description=(
            "Use this agent to create a recipe card for a dish: it writes the recipe, "
            "generates the photography and returns a link to the finished deck."
        ),
        starter_prompts=(
            "Create a recipe card for chicken tikka masala.",
            "Make a card for a vegetarian lentil soup, 6 servings.",
            "Build a recipe card for classic beef chili.",
        ),
    ),
    "recipe_card_workflow": AgentSpec(
        package_name="recipe-card-workflow",
        module="recipe_card_workflow.workflow",
        required_remote_bootstrap_env=("RECIPE_CARD_BUCKET",),
        display_name="Recipe Card Workflow",
        source_root="workflows",
        extra_packages=(
            "workflows/recipe_card_workflow/src/recipe_card_workflow",
            "packages/recipe_cards/src/recipe_cards",
            "packages/gemini_shared/src/gemini_shared",
        ),
        # Writes to the same prefix as the agent. It has no discovery tools:
        # a fixed pipeline cannot ask whether to reuse an existing card.
        runtime_env=(("RECIPE_CARD_PREFIX", "recipe-cards"),),
        # The output bucket must already exist before granting object access.
        agent_identity_bucket_roles=(
            BucketRoles(
                "${RECIPE_CARD_BUCKET}",
                (STORAGE_OBJECT_ADMIN,),
            ),
        ),
        registration_description=(
            "Produces a recipe card deck as a fixed pipeline: writes the recipe, "
            "generates the photography, then renders and publishes the card. The same "
            "job as the Recipe Card Agent, with the order fixed rather than chosen."
        ),
        invocation_description=(
            "Use this when a recipe card is wanted end to end from a dish name, with no "
            "conversation: it returns a link to the finished deck."
        ),
        starter_prompts=(
            "Spanish Iberico croquetas",
            "Chicken tikka masala",
            "Classic beef chili",
        ),
    ),
    "bigquery_mcp_agent": AgentSpec(
        package_name="bigquery-mcp-agent",
        module="bigquery_mcp_agent.agent",
        display_name="BigQuery MCP Agent",
        extra_packages=(
            "agents/bigquery_mcp_agent/src/bigquery_mcp_agent",
            "packages/gemini_shared/src/gemini_shared",
        ),
        required_remote_bootstrap_env=(AUTHORIZATION_ID_ENV,),
        # The MCP server authenticates this same token on every tool call.
        delegated_oauth_scopes=(BIGQUERY_SCOPE,),
        # The endpoint this agent's token is sent to, declared per entry so no
        # other agent's value can retarget it.
        runtime_env=(("MCP_SERVER_URL", BIGQUERY),),
        registration_description=(
            "Explore BigQuery with read-only tools from Google's managed MCP server, "
            "using the signed-in user's delegated credentials."
        ),
        invocation_description="Discover BigQuery schemas and run read-only queries through MCP.",
        starter_prompts=(
            "List my BigQuery datasets using the MCP tools.",
            "Describe the schema of the sample orders table.",
            "Which MCP tools are available to you?",
        ),
    ),
    "monitoring_mcp_agent": AgentSpec(
        package_name="monitoring-mcp-agent",
        module="monitoring_mcp_agent.agent",
        display_name="Monitoring MCP Agent",
        extra_packages=(
            "agents/monitoring_mcp_agent/src/monitoring_mcp_agent",
            "packages/gemini_shared/src/gemini_shared",
        ),
        required_remote_bootstrap_env=(AUTHORIZATION_ID_ENV,),
        # The MCP server authenticates this same token on every tool call. The
        # selected tools only read, so the authorization asks for the read scope
        # rather than the read-write one the MCP guide shows.
        delegated_oauth_scopes=(CLOUD_MONITORING_READONLY_SCOPE,),
        runtime_env=(
            # The endpoint this agent's token is sent to, declared per entry so
            # no other agent's value can retarget it.
            ("MCP_SERVER_URL", CLOUD_MONITORING),
            # This server's nine tools publish ~79k tokens of response schemas.
            # ADK sends those to the model as response_json_schema, which
            # exceeds its input limit before any tool runs. Inputs only.
            ("ADK_DISABLE_JSON_SCHEMA_FOR_FUNC_DECL", "true"),
        ),
        registration_description=(
            "Inspect Cloud Monitoring metrics, alerts and dashboards with read-only tools "
            "from Google's managed MCP server, using the signed-in user's delegated "
            "credentials."
        ),
        invocation_description=(
            "Read metric time series, alerting policies and dashboards through MCP."
        ),
        starter_prompts=(
            "Which metric types does my project report?",
            "Are there any alert violations right now? List the last five incidents.",
            "Show CPU utilization for my VM instances over the last two hours.",
        ),
    ),
}


def detect_delegated_auth(spec: AgentSpec) -> bool:
    """Check source for the authorization marker without importing the agent."""
    return any(
        DELEGATED_AUTH_MARKER in path.read_text(encoding="utf-8")
        for path in ROOT.glob(f"{spec.source_root}/{_package_dir(spec)}/**/*.py")
    )


def _package_dir(spec: AgentSpec) -> str:
    """Directory under agents/ holding this agent, derived from its module."""
    return spec.module.split(".")[0]


def get_agent_spec(agent_name: str) -> AgentSpec:
    try:
        return AGENTS[agent_name]
    except KeyError as exc:
        allowed = ", ".join(sorted(AGENTS))
        raise SystemExit(f"Unknown agent '{agent_name}'. Choose one of: {allowed}") from exc
