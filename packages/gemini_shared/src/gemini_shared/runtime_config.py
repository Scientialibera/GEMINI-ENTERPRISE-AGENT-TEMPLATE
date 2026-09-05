"""Load validated live configuration from Parameter Manager with local fallback."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
import os
import threading
import time

from google.adk.integrations.parameter_manager.parameter_client import ParameterManagerClient
from pydantic import BaseModel, ConfigDict, Field

from .bootstrap import get_bootstrap_settings


LOGGER = logging.getLogger(__name__)


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


def _local_payload() -> dict[str, object]:
    model = os.getenv("GEMINI_MODEL", "").strip()
    instruction = os.getenv("AGENT_INSTRUCTION", "").strip()
    if not model:
        raise RuntimeError("GEMINI_MODEL is required for local execution.")
    if not instruction:
        raise RuntimeError("AGENT_INSTRUCTION is required for local execution.")
    return {
        "config_revision": os.getenv("CONFIG_REVISION", "local").strip() or "local",
        "model": model,
        "instruction": instruction,
        "environment": os.getenv("ENVIRONMENT", "local").strip() or "local",
        "log_level": os.getenv("LOG_LEVEL", "DEBUG").strip() or "DEBUG",
        "agent_identity_bucket_name": os.getenv("AGENT_IDENTITY_BUCKET_NAME", "").strip() or None,
        "storage_object_limit": os.getenv("STORAGE_OBJECT_LIMIT", "10"),
        "bigquery_query_row_limit": os.getenv("BIGQUERY_QUERY_ROW_LIMIT", "100"),
        "mcp_server_url": os.getenv("MCP_SERVER_URL", "").strip() or None,
    }


class RuntimeConfigStore:
    """TTL cache with last-known-good behavior after the first remote load."""

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
        if "/versions/" in parameter:
            return parameter
        if parameter.startswith("projects/"):
            return f"{parameter.rstrip('/')}/versions/latest"
        return (
            f"projects/{bootstrap.project_id}/locations/{bootstrap.parameter_location}/"
            f"parameters/{parameter}/versions/latest"
        )

    def _load_remote(self, resource_name: str) -> RuntimeConfig:
        bootstrap = get_bootstrap_settings()
        payload = ParameterManagerClient(
            location=bootstrap.parameter_location
        ).get_parameter(resource_name)
        return RuntimeConfig.model_validate(json.loads(payload))

    def get(self, *, force_refresh: bool = False) -> RuntimeConfig:
        resource_name = self._version_name()
        if resource_name is None:
            return RuntimeConfig.model_validate(_local_payload())

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
                if self._config is not None:
                    LOGGER.exception(
                        "Parameter Manager refresh failed; continuing with last-known-good configuration."
                    )
                    self._expires_at = now + min(30, bootstrap.refresh_seconds)
                    return self._config
                raise

            self._config = loaded
            self._resource_name = resource_name
            self._loaded_at = datetime.now(timezone.utc)
            self._expires_at = now + bootstrap.refresh_seconds
            return loaded

    def status(self) -> dict[str, object]:
        config = self.get()
        return {
            "source": "local environment" if self._resource_name is None else "Google Cloud Parameter Manager",
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
