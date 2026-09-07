"""Endpoints and toolsets for Google's managed MCP servers."""

from .servers import (
    BIGQUERY,
    BIGQUERY_READONLY_TOOLS,
    BIGQUERY_SCOPE,
    CLOUD_LOGGING,
    CLOUD_MONITORING,
    CLOUD_PLATFORM_SCOPE,
    CLOUD_RUN,
    CLOUD_STORAGE,
    COMPUTE_ENGINE,
)
from .toolsets import bigquery_readonly_toolset

__all__ = [
    "BIGQUERY",
    "BIGQUERY_READONLY_TOOLS",
    "BIGQUERY_SCOPE",
    "CLOUD_LOGGING",
    "CLOUD_MONITORING",
    "CLOUD_PLATFORM_SCOPE",
    "CLOUD_RUN",
    "CLOUD_STORAGE",
    "COMPUTE_ENGINE",
    "bigquery_readonly_toolset",
]
