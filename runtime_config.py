"""Load and validate versioned runtime settings from Parameter Manager."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
import threading
import time

from google.adk.integrations.parameter_manager.parameter_client import (
    ParameterManagerClient,
)
from pydantic import BaseModel, ConfigDict, Field

from bootstrap import get_bootstrap_settings


LOGGER = logging.getLogger(__name__)


class RuntimeConfig(BaseModel):
    """Configuration that can change without rebuilding the Agent Engine."""

    model_config = ConfigDict(extra="forbid")

    config_revision: str = Field(min_length=1)
    model: str = Field(min_length=1)
    instruction: str = Field(min_length=1)
    agent_identity_bucket_name: str = Field(min_length=3)
    storage_object_limit: int = Field(default=10, ge=1, le=100)
    bigquery_query_row_limit: int = Field(default=100, ge=1, le=10_000)


class RuntimeConfigStore:
    """TTL cache with last-known-good behavior after the first successful load."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._config: RuntimeConfig | None = None
        self._expires_at = 0.0
        self._loaded_at: datetime | None = None
        self._resource_name: str | None = None

    def get(self, *, force_refresh: bool = False) -> RuntimeConfig:
        now = time.monotonic()
        if not force_refresh and self._config is not None and now < self._expires_at:
            return self._config

        with self._lock:
            now = time.monotonic()
            if not force_refresh and self._config is not None and now < self._expires_at:
                return self._config

            bootstrap = get_bootstrap_settings()
            resource_name = (
                f"projects/{bootstrap.project_id}/locations/{bootstrap.location}/"
                f"parameters/{bootstrap.parameter_id}/versions/"
                f"{bootstrap.parameter_version}"
            )
            try:
                payload = ParameterManagerClient(
                    location=bootstrap.location
                ).get_parameter(resource_name)
                loaded = RuntimeConfig.model_validate(json.loads(payload))
            except Exception:
                if self._config is not None:
                    LOGGER.exception(
                        "Parameter Manager refresh failed; continuing with the last known good configuration."
                    )
                    self._expires_at = now + min(30, bootstrap.cache_seconds)
                    return self._config
                raise

            self._config = loaded
            self._resource_name = resource_name
            self._loaded_at = datetime.now(timezone.utc)
            self._expires_at = now + bootstrap.cache_seconds
            return loaded

    def status(self) -> dict[str, object]:
        config = self.get()
        return {
            "source": "Google Cloud Parameter Manager",
            "resource": self._resource_name,
            "config_revision": config.config_revision,
            "loaded_at": self._loaded_at.isoformat() if self._loaded_at else None,
            "cache_seconds": get_bootstrap_settings().cache_seconds,
            "model": config.model,
        }


runtime_config_store = RuntimeConfigStore()


def get_runtime_config(*, force_refresh: bool = False) -> RuntimeConfig:
    return runtime_config_store.get(force_refresh=force_refresh)


def get_runtime_config_status() -> dict[str, object]:
    return runtime_config_store.status()
