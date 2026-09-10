"""Environment loading and the development deployment boundary."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from dotenv import load_dotenv
from gemini_shared.config.bootstrap import (
    AUTHORIZATION_ID_ENV,
    CONFIG_PARAMETER_ENV,
    LOCATION_ENV,
    PROJECT_ENV,
)
from paths import DEV_DIR

from .environment import configured_value

if TYPE_CHECKING:
    from registry import AgentSpec

GCS_URI_PREFIX = "gs://"

DEV_ENVIRONMENT = "dev"

STAGING_BUCKET_ENV = "DEV_STAGING_BUCKET"

ENVIRONMENT_ENV = "ENVIRONMENT"

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
    # Recipe card agent: output bucket and image model.
    "RECIPE_CARD_BUCKET",
    "RECIPE_CARD_BUCKET_LOCATION",
    "IMAGE_MODEL",
    "IMAGE_MODEL_LOCATION",
)


def load_environment(filename: str) -> None:
    path = DEV_DIR / filename
    if path.exists():
        load_dotenv(path, override=False)


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


def runtime_env(spec: AgentSpec | None = None) -> dict[str, str]:
    """Environment baked into one runtime: the agent's own settings, then the shell.

    RUNTIME_ENV_KEYS is a shared forwarding list, so a value set for one agent
    reaches whichever agent is released next. A spec's own ``runtime_env`` is
    scoped to that entry. The environment is applied last so a single run can
    still override a declared value.
    """
    # require_dev_environment must resolve per-agent defaults first.
    declared = dict(spec.runtime_env) if spec else {}
    forwarded = {
        key: os.environ[key] for key in RUNTIME_ENV_KEYS if not is_missing_or_placeholder(key)
    }
    return declared | forwarded
