"""Resolve the small set of values needed to locate managed configuration.

The deployed runtime receives these values as non-secret environment variables.
Local scripts fall back to the gitignored config/config.py file.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Any


def _local_value(name: str) -> Any | None:
    try:
        import config
    except ImportError:
        return None
    return getattr(config, name, None)


def _value(environment_name: str, config_name: str, default: str | None = None) -> str:
    value = os.getenv(environment_name) or _local_value(config_name) or default
    if value is None or not str(value).strip():
        raise RuntimeError(
            f"Set {environment_name} in Agent Engine or {config_name} in config/config.py."
        )
    return str(value)


@dataclass(frozen=True)
class BootstrapSettings:
    project_id: str
    location: str
    parameter_id: str
    parameter_version: str
    cache_seconds: int
    gemini_enterprise_authorization_id: str


def get_bootstrap_settings() -> BootstrapSettings:
    cache_seconds = int(
        _value("AGENT_CONFIG_CACHE_SECONDS", "RUNTIME_CONFIG_CACHE_SECONDS", "300")
    )
    if cache_seconds < 0:
        raise ValueError("AGENT_CONFIG_CACHE_SECONDS cannot be negative.")
    return BootstrapSettings(
        project_id=_value("AGENT_PROJECT_ID", "PROJECT_ID"),
        location=_value("AGENT_LOCATION", "LOCATION"),
        parameter_id=_value("AGENT_CONFIG_PARAMETER", "RUNTIME_CONFIG_PARAMETER_ID"),
        parameter_version=_value(
            "AGENT_CONFIG_VERSION", "RUNTIME_CONFIG_PARAMETER_VERSION", "latest"
        ),
        cache_seconds=cache_seconds,
        gemini_enterprise_authorization_id=_value(
            "AGENT_GEMINI_AUTHORIZATION", "GEMINI_ENTERPRISE_AUTHORIZATION_ID"
        ),
    )

