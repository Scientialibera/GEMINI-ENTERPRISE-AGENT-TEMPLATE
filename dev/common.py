from __future__ import annotations

import importlib
import json
import os
import shutil
import tempfile
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import vertexai
from config.environment import configured_value
from dotenv import load_dotenv
from vertexai.agent_engines import AdkApp

ROOT = Path(__file__).resolve().parents[1]
DEV_DIR = ROOT / "dev"
STATE_DIR = DEV_DIR / ".state"

DEV_ENVIRONMENT = "dev"
ENVIRONMENT_LABEL = "dev"
GCS_URI_PREFIX = "gs://"

VERTEX_API_VERSION = "v1beta1"

PROJECT_ENV = "GOOGLE_CLOUD_PROJECT"
LOCATION_ENV = "GOOGLE_CLOUD_LOCATION"
STAGING_BUCKET_ENV = "DEV_STAGING_BUCKET"
ENVIRONMENT_ENV = "ENVIRONMENT"
CONFIG_PARAMETER_ENV = "CONFIG_PARAMETER"
DEV_REASONING_ENGINE_ENV = "DEV_REASONING_ENGINE"
AUTHORIZATION_ID_ENV = "GEMINI_ENTERPRISE_AUTHORIZATION_ID"
# Map each agent name to its OAuth client ID.
OAUTH_CLIENTS_ENV = "OAUTH_CLIENTS"

# Source marker used to check the spec's delegated-auth declaration.
DELEGATED_AUTH_MARKER = AUTHORIZATION_ID_ENV

# Identity scopes included in each delegated authorization.
IDENTITY_OAUTH_SCOPES = ("openid", "email", "profile")

# Service scopes requested by delegated tools.
BIGQUERY_SCOPE = "https://www.googleapis.com/auth/bigquery"
CLOUD_PLATFORM_SCOPE = "https://www.googleapis.com/auth/cloud-platform"
CLOUD_STORAGE_READONLY_SCOPE = "https://www.googleapis.com/auth/devstorage.read_only"

# IAM roles an agent's own runtime identity can be granted. Named here so a spec
# declares a capability rather than repeating a role string, and so the set an
# agent may ask for stays visible in one place.
STORAGE_OBJECT_VIEWER = "roles/storage.objectViewer"
STORAGE_OBJECT_ADMIN = "roles/storage.objectAdmin"
LOGGING_LOG_WRITER = "roles/logging.logWriter"
BIGQUERY_JOB_USER = "roles/bigquery.jobUser"
BIGQUERY_DATA_VIEWER = "roles/bigquery.dataViewer"

COMMON_REQUIRED_REMOTE_ENV = (
    PROJECT_ENV,
    LOCATION_ENV,
    STAGING_BUCKET_ENV,
)

RUNTIME_ENV_KEYS = (
    CONFIG_PARAMETER_ENV,
    "CONFIG_PARAMETER_LOCATION",
    "CONFIG_REFRESH_SECONDS",
    "BOOTSTRAP_MODEL",
    "GEMINI_MODEL_LOCATION",
    AUTHORIZATION_ID_ENV,
    # The toolset binds this endpoint at construction.
    "MCP_SERVER_URL",
    # Recipe card agent: output bucket and image model.
    "RECIPE_CARD_BUCKET",
    "RECIPE_CARD_BUCKET_LOCATION",
    "IMAGE_MODEL",
    "IMAGE_MODEL_LOCATION",
)

COMMON_REQUIREMENTS = (
    "google-cloud-aiplatform[agent_engines,adk]==1.164.0",
    "google-adk[extensions]==2.7.1",
    "google-cloud-parametermanager==0.4.1",
    "cloudpickle==3.1.2",
    "pydantic==2.13.4",
)

AUTH_REFERENCE_REQUIREMENTS = (
    # The agent-identity extra supplies the runtime's own credentials.
    "google-adk[agent-identity,extensions]==2.7.1",
    "google-cloud-storage==3.13.1",
    "google-cloud-bigquery==3.43.0",
    "google-auth>=2.35.0,<3.0.0",
)

RECIPE_CARD_REQUIREMENTS = (
    # Image generation, Cloud Storage publishing and the PowerPoint renderer.
    "google-genai>=2.22.0,<3.0.0",
    "google-cloud-storage==3.13.1",
    "python-pptx>=1.0.2,<2.0.0",
    "pillow>=11.0.0",
    # Resolves the runtime's credentials explicitly for the image model.
    "google-auth>=2.35.0,<3.0.0",
)

BIGQUERY_MCP_REQUIREMENTS = (
    # Install the remote MCP client.
    "google-adk[extensions,mcp]==2.7.1",
)


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
    requirements: tuple[str, ...]
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
        requirements=COMMON_REQUIREMENTS,
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
        requirements=COMMON_REQUIREMENTS + AUTH_REFERENCE_REQUIREMENTS,
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
        # The output bucket must already exist before granting object access.
        agent_identity_bucket_roles=(
            BucketRoles(
                "${RECIPE_CARD_BUCKET}",
                (STORAGE_OBJECT_ADMIN,),
            ),
        ),
        requirements=COMMON_REQUIREMENTS + RECIPE_CARD_REQUIREMENTS,
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
        # The output bucket must already exist before granting object access.
        agent_identity_bucket_roles=(
            BucketRoles(
                "${RECIPE_CARD_BUCKET}",
                (STORAGE_OBJECT_ADMIN,),
            ),
        ),
        requirements=COMMON_REQUIREMENTS + RECIPE_CARD_REQUIREMENTS,
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
        requirements=COMMON_REQUIREMENTS + BIGQUERY_MCP_REQUIREMENTS,
        required_remote_bootstrap_env=(AUTHORIZATION_ID_ENV,),
        # The MCP server authenticates this same token on every tool call.
        delegated_oauth_scopes=(BIGQUERY_SCOPE,),
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
}


def load_environment(filename: str) -> None:
    path = DEV_DIR / filename
    if path.exists():
        load_dotenv(path, override=False)


def oauth_client_id_for(agent_name: str, spec: AgentSpec) -> str:
    """Read the per-agent override, then the OAUTH_CLIENTS map."""
    override = os.getenv(spec.oauth_client_id_env, "").strip()
    if override:
        return override
    return _parse_oauth_clients().get(agent_name, "")


def _parse_oauth_clients() -> dict[str, str]:
    """Parse OAUTH_CLIENTS, a comma-separated list of agent=client_id pairs."""
    raw = os.getenv(OAUTH_CLIENTS_ENV, "").strip()
    if not raw:
        return {}

    clients: dict[str, str] = {}
    for entry in raw.split(","):
        entry = entry.strip()
        if not entry:
            continue
        if "=" not in entry:
            raise SystemExit(f"{OAUTH_CLIENTS_ENV} entry '{entry}' must use agent=client_id.")
        agent, _, client_id = entry.partition("=")
        agent, client_id = agent.strip(), client_id.strip()
        if agent in clients:
            raise SystemExit(f"{OAUTH_CLIENTS_ENV} lists '{agent}' more than once.")
        if agent not in AGENTS:
            raise SystemExit(
                f"{OAUTH_CLIENTS_ENV} names unknown agent '{agent}'. "
                f"Choose one of: {', '.join(sorted(AGENTS))}."
            )
        clients[agent] = client_id
    return clients


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


def is_missing_or_placeholder(name: str) -> bool:
    return not configured_value(name)


def require_dev_environment(
    *,
    require_parameter: bool = True,
    spec: AgentSpec | None = None,
) -> tuple[str, str, str]:
    environment = os.getenv(ENVIRONMENT_ENV, "").strip().lower()
    if environment != DEV_ENVIRONMENT:
        raise SystemExit(
            f"Refusing remote deployment: {ENVIRONMENT_ENV} must be exactly "
            f"'{DEV_ENVIRONMENT}'. Shared QA/prod deployment belongs to Terraform."
        )

    # Resolve per-agent defaults before building the runtime environment.
    if spec is not None:
        if require_parameter and is_missing_or_placeholder(CONFIG_PARAMETER_ENV):
            os.environ[CONFIG_PARAMETER_ENV] = spec.config_parameter_id
        if AUTHORIZATION_ID_ENV in spec.required_remote_bootstrap_env and (
            is_missing_or_placeholder(AUTHORIZATION_ID_ENV)
        ):
            os.environ[AUTHORIZATION_ID_ENV] = spec.authorization_id

    required = list(COMMON_REQUIRED_REMOTE_ENV)
    if require_parameter:
        required.append(CONFIG_PARAMETER_ENV)
    missing = [name for name in required if is_missing_or_placeholder(name)]
    if missing:
        raise SystemExit(
            f"Missing required dev settings: {', '.join(missing)}. Fill them in dev/.env.dev."
        )

    project_id = os.environ[PROJECT_ENV].strip()
    location = os.environ[LOCATION_ENV].strip()
    staging_bucket = os.environ[STAGING_BUCKET_ENV].strip()
    if not staging_bucket.startswith(GCS_URI_PREFIX):
        raise SystemExit(f"{STAGING_BUCKET_ENV} must be a {GCS_URI_PREFIX} bucket URI.")
    return project_id, location, staging_bucket


def validate_agent_remote_environment(spec: AgentSpec) -> None:
    missing = [
        name for name in spec.required_remote_bootstrap_env if is_missing_or_placeholder(name)
    ]
    if missing:
        raise SystemExit(
            f"{spec.package_name} requires additional bootstrap settings: {', '.join(missing)}."
        )


def runtime_env() -> dict[str, str]:
    # require_dev_environment must resolve per-agent defaults first.
    return {key: os.environ[key] for key in RUNTIME_ENV_KEYS if not is_missing_or_placeholder(key)}


def load_root_agent(spec: AgentSpec) -> Any:
    module = importlib.import_module(spec.module)
    return module.root_agent


def build_app(spec: AgentSpec) -> AdkApp:
    return AdkApp(agent=load_root_agent(spec), enable_tracing=True)


def build_client(project_id: str, location: str, staging_bucket: str) -> vertexai.Client:
    vertexai.init(project=project_id, location=location, staging_bucket=staging_bucket)
    return vertexai.Client(
        project=project_id,
        location=location,
        http_options={"api_version": VERTEX_API_VERSION},
    )


@contextmanager
def staged_extra_packages(spec: AgentSpec) -> Iterator[list[str]]:
    """Stage packages under flat names and restore the working directory on exit."""
    with tempfile.TemporaryDirectory(prefix="agent-deploy-") as temp_dir:
        staged_root = Path(temp_dir)
        staged: list[str] = []
        for package_path in spec.extra_packages:
            source = ROOT / package_path
            if not source.exists():
                raise FileNotFoundError(source)
            destination = staged_root / source.name
            shutil.copytree(source, destination, ignore=shutil.ignore_patterns("__pycache__"))
            staged.append(str(destination))
        previous_cwd = Path.cwd()
        os.chdir(staged_root)
        try:
            # Relative names keep the uploaded tar entries flat.
            yield [Path(path).name for path in staged]
        finally:
            os.chdir(previous_cwd)


def deployment_config(
    spec: AgentSpec,
    staging_bucket: str,
    extra_packages: Sequence[str],
) -> dict[str, object]:
    return {
        "requirements": list(spec.requirements),
        "extra_packages": list(extra_packages),
        "staging_bucket": staging_bucket,
        "env_vars": runtime_env(),
    }


def state_path(agent_name: str) -> Path:
    return STATE_DIR / f"{agent_name}.json"


def save_state(agent_name: str, resource_name: str) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    payload = {"agent": agent_name, "reasoning_engine": resource_name}
    state_path(agent_name).write_text(
        json.dumps(payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def load_resource_name(agent_name: str) -> str:
    explicit = os.getenv(DEV_REASONING_ENGINE_ENV, "").strip()
    if explicit:
        return explicit

    path = state_path(agent_name)
    if not path.exists():
        raise SystemExit(
            f"No local dev state found for {agent_name}. Run deploy/deploy_dev.py "
            f"first or set {DEV_REASONING_ENGINE_ENV}."
        )
    payload = json.loads(path.read_text(encoding="utf-8"))
    resource_name = payload.get("reasoning_engine")
    if not isinstance(resource_name, str) or not resource_name.strip():
        raise SystemExit(f"Invalid developer state file: {path}")
    return resource_name
