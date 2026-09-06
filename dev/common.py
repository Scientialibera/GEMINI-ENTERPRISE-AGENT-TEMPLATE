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
from dotenv import load_dotenv
from vertexai.agent_engines import AdkApp

ROOT = Path(__file__).resolve().parents[1]
DEV_DIR = ROOT / "dev"
STATE_DIR = DEV_DIR / ".state"

DEV_ENVIRONMENT = "dev"
GCS_URI_PREFIX = "gs://"
PLACEHOLDER_TOKENS = ("REPLACE", "<")
VERTEX_API_VERSION = "v1beta1"

PROJECT_ENV = "GOOGLE_CLOUD_PROJECT"
LOCATION_ENV = "GOOGLE_CLOUD_LOCATION"
STAGING_BUCKET_ENV = "DEV_STAGING_BUCKET"
ENVIRONMENT_ENV = "ENVIRONMENT"
CONFIG_PARAMETER_ENV = "CONFIG_PARAMETER"
DEV_REASONING_ENGINE_ENV = "DEV_REASONING_ENGINE"
AUTHORIZATION_ID_ENV = "GEMINI_ENTERPRISE_AUTHORIZATION_ID"

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
    # Bound at construction, so it is bootstrap rather than live configuration.
    "MCP_SERVER_URL",
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

BIGQUERY_MCP_REQUIREMENTS = (
    # The mcp extra pulls the client used to reach remote MCP servers. No
    # BigQuery client library: the server owns the calls, not this agent.
    "google-adk[extensions,mcp]==2.7.1",
)


@dataclass(frozen=True, slots=True)
class AgentSpec:
    package_name: str
    module: str
    display_name: str
    extra_packages: tuple[str, ...]
    requirements: tuple[str, ...]
    required_remote_bootstrap_env: tuple[str, ...] = ()
    # Gemini Enterprise registration metadata, used by register_agent.py.
    registration_description: str = ""
    invocation_description: str = ""
    starter_prompts: tuple[str, ...] = ()

    @property
    def config_parameter_id(self) -> str:
        """Parameter Manager parameter holding this agent's live configuration.

        Each agent reads its own parameter, so adding an agent to AGENTS does
        not require editing shared configuration. CONFIG_PARAMETER in the
        environment still wins when set, which keeps a one-off override
        available without changing code.
        """
        return f"{self.package_name}-config"

    @property
    def authorization_id(self) -> str:
        """Gemini Enterprise authorization supplying this agent's delegated token.

        Gemini Enterprise rejects an authorization that another agent already
        uses, so agents cannot share one. Deriving the name per agent is what
        allows a second delegated-auth agent to be registered without editing
        shared configuration. GEMINI_ENTERPRISE_AUTHORIZATION_ID in the
        environment still wins when set.
        """
        return f"{self.package_name}-authz"


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
            "Minimal pro-code ADK agent. Reads its model and instruction from Parameter "
            "Manager at request time, so live configuration changes take effect without "
            "redeploying the runtime."
        ),
        invocation_description=(
            "Use this agent to check the active runtime configuration of the pro-code "
            "template, such as the published config revision or the model in use."
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
        registration_description=(
            "Reference pro-code ADK agent for the two supported authentication patterns. "
            "Agent Identity is used for agent-scoped access to Cloud Storage, while a "
            "Gemini Enterprise delegated user token is used to query BigQuery under the "
            "signed-in user's own permissions. Both tools are written in this repository "
            "against the Google Cloud APIs."
        ),
        invocation_description=(
            "Use this agent to demonstrate agent authentication: report which identity the "
            "runtime is using, read Cloud Storage as the agent itself, or query BigQuery as "
            "the signed-in user."
        ),
        starter_prompts=(
            "Which identity is this agent running as?",
            "List the BigQuery datasets and tables I can access.",
            "Show total revenue by region from the sample orders table.",
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
        registration_description=(
            "Pro-code ADK agent whose data tools come from Google's managed BigQuery MCP "
            "server rather than from this repository. Nothing is deployed to obtain them, "
            "the tool list is filtered to read-only operations, and each call carries the "
            "signed-in user's delegated token."
        ),
        invocation_description=(
            "Use this agent to explore BigQuery through a remote MCP server: list datasets "
            "and tables, inspect their schemas, or run a read-only query as the signed-in "
            "user."
        ),
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


def get_agent_spec(agent_name: str) -> AgentSpec:
    try:
        return AGENTS[agent_name]
    except KeyError as exc:
        allowed = ", ".join(sorted(AGENTS))
        raise SystemExit(f"Unknown agent '{agent_name}'. Choose one of: {allowed}") from exc


def is_missing_or_placeholder(name: str) -> bool:
    value = os.getenv(name, "").strip()
    return not value or any(token in value for token in PLACEHOLDER_TOKENS)


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

    # An agent defaults to its own parameter and its own authorization.
    # Resolving them into the environment here keeps every later reader — the
    # deployed env_vars, the prerequisite check, the registration call and
    # gemini_shared itself — on the same values.
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
    # require_dev_environment resolves the agent's parameter into the
    # environment before this runs.
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
    """Yield flattened extra_package paths for upload.

    The SDK preserves each path in the uploaded tar and the runtime extracts it
    at the container root, so a src-layout package must be staged flat to be
    importable by name.
    """
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
            f"No local dev state found for {agent_name}. Run deploy_dev.py first "
            f"or set {DEV_REASONING_ENGINE_ENV}."
        )
    payload = json.loads(path.read_text(encoding="utf-8"))
    resource_name = payload.get("reasoning_engine")
    if not isinstance(resource_name, str) or not resource_name.strip():
        raise SystemExit(f"Invalid developer state file: {path}")
    return resource_name
