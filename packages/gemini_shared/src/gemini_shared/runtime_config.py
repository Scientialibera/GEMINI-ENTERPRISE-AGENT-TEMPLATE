"""Load validated live configuration from Parameter Manager with local fallback."""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from datetime import UTC, datetime

from google.adk.integrations.parameter_manager.parameter_client import ParameterManagerClient
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .bootstrap import DEFAULT_PARAMETER_LOCATION as GLOBAL_PARAMETER_LOCATION
from .bootstrap import get_bootstrap_settings

LOGGER = logging.getLogger(__name__)

GEMINI_MODEL_ENV = "GEMINI_MODEL"
AGENT_INSTRUCTION_ENV = "AGENT_INSTRUCTION"
CONFIG_REVISION_ENV = "CONFIG_REVISION"
ENVIRONMENT_ENV = "ENVIRONMENT"
LOG_LEVEL_ENV = "LOG_LEVEL"
AGENT_IDENTITY_BUCKET_ENV = "AGENT_IDENTITY_BUCKET_NAME"
STORAGE_OBJECT_LIMIT_ENV = "STORAGE_OBJECT_LIMIT"
BIGQUERY_QUERY_ROW_LIMIT_ENV = "BIGQUERY_QUERY_ROW_LIMIT"
MCP_SERVER_URL_ENV = "MCP_SERVER_URL"

LOCAL_REVISION = "local"
LOCAL_ENVIRONMENT = "local"
DEFAULT_LOG_LEVEL = "DEBUG"
DEFAULT_STORAGE_OBJECT_LIMIT = 10
DEFAULT_BIGQUERY_QUERY_ROW_LIMIT = 100
LAST_KNOWN_GOOD_RETRY_SECONDS = 30
PARAMETER_VERSION_SEGMENT = "/versions/"
LATEST_VERSION = "latest"


class RuntimeConfig(BaseModel):
    """Configuration that may change without rebuilding Agent Engine."""

    model_config = ConfigDict(extra="forbid")

    config_revision: str = Field(min_length=1)
    model: str = Field(min_length=1)
    instruction: str = Field(min_length=1)
    environment: str = Field(default="dev", min_length=1)
    log_level: str = Field(default="INFO", min_length=1)
    agent_identity_bucket_name: str | None = None
    storage_object_limit: int = Field(default=10, ge=1, le=100)
    bigquery_query_row_limit: int = Field(default=100, ge=1, le=10_000)
    mcp_server_url: str | None = None

    @field_validator("model", "instruction", "config_revision", "environment")
    @classmethod
    def validate_required_text(cls, value: str) -> str:
        if not value.strip() or "REPLACE" in value or value.startswith("<"):
            raise ValueError("Required runtime settings must contain real, non-empty values.")
        return value

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, value: str) -> str:
        value = value.upper()
        if value not in logging.getLevelNamesMapping():
            raise ValueError("log_level must be a Python logging level name.")
        return value


def _required_local_value(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is required for local execution.")
    return value


def _local_payload() -> dict[str, object]:
    return {
        "config_revision": os.getenv(CONFIG_REVISION_ENV, LOCAL_REVISION).strip() or LOCAL_REVISION,
        "model": _required_local_value(GEMINI_MODEL_ENV),
        "instruction": _required_local_value(AGENT_INSTRUCTION_ENV),
        "environment": os.getenv(ENVIRONMENT_ENV, LOCAL_ENVIRONMENT).strip() or LOCAL_ENVIRONMENT,
        "log_level": os.getenv(LOG_LEVEL_ENV, DEFAULT_LOG_LEVEL).strip() or DEFAULT_LOG_LEVEL,
        "agent_identity_bucket_name": os.getenv(AGENT_IDENTITY_BUCKET_ENV, "").strip() or None,
        "storage_object_limit": os.getenv(
            STORAGE_OBJECT_LIMIT_ENV,
            str(DEFAULT_STORAGE_OBJECT_LIMIT),
        ),
        "bigquery_query_row_limit": os.getenv(
            BIGQUERY_QUERY_ROW_LIMIT_ENV,
            str(DEFAULT_BIGQUERY_QUERY_ROW_LIMIT),
        ),
        "mcp_server_url": os.getenv(MCP_SERVER_URL_ENV, "").strip() or None,
    }


class RuntimeConfigStore:
    """Thread-safe TTL cache with last-known-good behavior after first remote load."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._config: RuntimeConfig | None = None
        self._expires_at = 0.0
        self._loaded_at: datetime | None = None
        self._resource_name: str | None = None

    @staticmethod
    def _version_name() -> str | None:
        bootstrap = get_bootstrap_settings()
        parameter = bootstrap.config_parameter
        if not parameter:
            return None
        if PARAMETER_VERSION_SEGMENT in parameter:
            return parameter
        if parameter.startswith("projects/"):
            return f"{parameter.rstrip('/')}{PARAMETER_VERSION_SEGMENT}{LATEST_VERSION}"
        return (
            f"projects/{bootstrap.project_id}/locations/{bootstrap.parameter_location}/"
            f"parameters/{parameter}/versions/{LATEST_VERSION}"
        )

    @staticmethod
    def _load_remote(resource_name: str) -> RuntimeConfig:
        bootstrap = get_bootstrap_settings()
        # Passing location="global" builds a nonexistent regional endpoint. The
        # global endpoint is the client default, selected by omitting location.
        location = bootstrap.parameter_location
        client = (
            ParameterManagerClient()
            if location == GLOBAL_PARAMETER_LOCATION
            else ParameterManagerClient(location=location)
        )
        payload = client.get_parameter(resource_name)
        return RuntimeConfig.model_validate(json.loads(payload))

    def get(self, *, force_refresh: bool = False) -> RuntimeConfig:
        resource_name = self._version_name()
        if resource_name is None:
            config = RuntimeConfig.model_validate(_local_payload())
            logging.getLogger().setLevel(config.log_level)
            return config

        bootstrap = get_bootstrap_settings()
        now = time.monotonic()
        if not force_refresh and self._config is not None and now < self._expires_at:
            return self._config

        with self._lock:
            now = time.monotonic()
            if not force_refresh and self._config is not None and now < self._expires_at:
                return self._config
            try:
                loaded = self._load_remote(resource_name)
            except Exception:
                if self._config is None:
                    raise
                LOGGER.warning(
                    "Parameter Manager refresh failed; using last-known-good configuration."
                )
                self._expires_at = now + min(
                    LAST_KNOWN_GOOD_RETRY_SECONDS,
                    bootstrap.refresh_seconds,
                )
                return self._config

            self._config = loaded
            logging.getLogger().setLevel(loaded.log_level)
            self._resource_name = resource_name
            self._loaded_at = datetime.now(UTC)
            self._expires_at = now + bootstrap.refresh_seconds
            return loaded

    def status(self) -> dict[str, object]:
        config = self.get()
        source = (
            "local environment" if self._resource_name is None else "Google Cloud Parameter Manager"
        )
        return {
            "source": source,
            "resource": self._resource_name,
            "config_revision": config.config_revision,
            "loaded_at": self._loaded_at.isoformat() if self._loaded_at else None,
            "cache_seconds": get_bootstrap_settings().refresh_seconds,
            "model": config.model,
            "environment": config.environment,
        }

    def reset(self) -> None:
        with self._lock:
            self._config = None
            self._expires_at = 0.0
            self._loaded_at = None
            self._resource_name = None


runtime_config_store = RuntimeConfigStore()


def get_runtime_config(*, force_refresh: bool = False) -> RuntimeConfig:
    return runtime_config_store.get(force_refresh=force_refresh)


def get_runtime_config_status() -> dict[str, object]:
    return runtime_config_store.status()


def reset_runtime_config_for_tests() -> None:
    runtime_config_store.reset()
