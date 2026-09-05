from __future__ import annotations

import importlib
import json
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv
import vertexai
from vertexai.agent_engines import AdkApp


ROOT = Path(__file__).resolve().parents[1]
DEV_DIR = ROOT / "dev"
STATE_DIR = DEV_DIR / ".state"


@dataclass(frozen=True)
class AgentSpec:
    package_name: str
    module: str
    display_name: str
    extra_packages: tuple[str, ...]
    requirements: tuple[str, ...]
    required_remote_bootstrap_env: tuple[str, ...] = ()


COMMON_REQUIREMENTS = (
    "google-cloud-aiplatform[agent_engines,adk]==1.164.0",
    "google-adk[extensions]==2.7.1",
    "google-cloud-parametermanager==0.4.1",
    "cloudpickle==3.1.2",
    "pydantic==2.13.4",
)

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
    ),
    "auth_reference_agent": AgentSpec(
        package_name="auth-reference-agent",
        module="auth_reference_agent.agent",
        display_name="Auth Reference Agent",
        extra_packages=(
            "agents/auth_reference_agent/src/auth_reference_agent",
            "packages/gemini_shared/src/gemini_shared",
        ),
        requirements=COMMON_REQUIREMENTS
        + (
            "google-adk[agent-identity,extensions]==2.7.1",
            "google-cloud-storage==3.13.1",
            "google-cloud-bigquery==3.43.0",
            "google-auth>=2.35.0,<3.0.0",
        ),
        required_remote_bootstrap_env=("GEMINI_ENTERPRISE_AUTHORIZATION_ID",),
    ),
}

RUNTIME_ENV_KEYS = (
    "CONFIG_PARAMETER",
    "CONFIG_PARAMETER_LOCATION",
    "CONFIG_REFRESH_SECONDS",
    "BOOTSTRAP_MODEL",
    "GEMINI_MODEL_LOCATION",
    "GEMINI_ENTERPRISE_AUTHORIZATION_ID",
)


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


def _missing_or_placeholder(name: str) -> bool:
    value = os.getenv(name, "").strip()
    return not value or "REPLACE" in value or value.startswith("<")


def require_dev_environment(*, require_parameter: bool = True) -> tuple[str, str, str]:
    if os.getenv("ENVIRONMENT", "").strip().lower() != "dev":
        raise SystemExit(
            "Refusing remote deployment: ENVIRONMENT must be exactly 'dev'. "
            "Shared QA/prod deployment belongs to Terraform."
        )
    required = ["GOOGLE_CLOUD_PROJECT", "GOOGLE_CLOUD_LOCATION", "DEV_STAGING_BUCKET"]
    if require_parameter:
        required.append("CONFIG_PARAMETER")
    missing = [name for name in required if _missing_or_placeholder(name)]
    if missing:
        raise SystemExit(
            "Missing required dev settings: "
            f"{', '.join(missing)}. Fill them in dev/.env.dev."
        )

    project_id = os.environ["GOOGLE_CLOUD_PROJECT"].strip()
    location = os.environ["GOOGLE_CLOUD_LOCATION"].strip()
    staging_bucket = os.environ["DEV_STAGING_BUCKET"].strip()
    if not staging_bucket.startswith("gs://"):
        raise SystemExit("DEV_STAGING_BUCKET must be a gs:// bucket URI.")
    return project_id, location, staging_bucket


def validate_agent_remote_environment(spec: AgentSpec) -> None:
    missing = [
        name for name in spec.required_remote_bootstrap_env if _missing_or_placeholder(name)
    ]
    if missing:
        raise SystemExit(
            f"{spec.package_name} requires additional bootstrap settings: "
            f"{', '.join(missing)}."
        )


def runtime_env() -> dict[str, str]:
    return {
        key: os.environ[key]
        for key in RUNTIME_ENV_KEYS
        if os.getenv(key, "").strip()
        and "REPLACE" not in os.environ[key]
        and not os.environ[key].startswith("<")
    }


def load_root_agent(spec: AgentSpec):
    module = importlib.import_module(spec.module)
    return module.root_agent


def build_app(spec: AgentSpec) -> AdkApp:
    return AdkApp(agent=load_root_agent(spec), enable_tracing=True)


def build_client(project_id: str, location: str, staging_bucket: str):
    vertexai.init(project=project_id, location=location, staging_bucket=staging_bucket)
    return vertexai.Client(
        project=project_id,
        location=location,
        http_options={"api_version": "v1beta1"},
    )


def deployment_config(spec: AgentSpec, staging_bucket: str) -> dict[str, object]:
    return {
        "requirements": list(spec.requirements),
        "extra_packages": list(spec.extra_packages),
        "staging_bucket": staging_bucket,
        "env_vars": runtime_env(),
    }


def state_path(agent_name: str) -> Path:
    return STATE_DIR / f"{agent_name}.json"


def save_state(agent_name: str, resource_name: str) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    state_path(agent_name).write_text(
        json.dumps({"agent": agent_name, "reasoning_engine": resource_name}, indent=2),
        encoding="utf-8",
    )


def load_resource_name(agent_name: str) -> str:
    explicit = os.getenv("DEV_REASONING_ENGINE", "").strip()
    if explicit:
        return explicit
    path = state_path(agent_name)
    if not path.exists():
        raise SystemExit(
            f"No local dev state found for {agent_name}. Run deploy_dev.py first "
            "or set DEV_REASONING_ENGINE."
        )
    return json.loads(path.read_text(encoding="utf-8"))["reasoning_engine"]
