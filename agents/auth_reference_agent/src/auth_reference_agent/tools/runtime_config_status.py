"""Report the active runtime configuration."""

from __future__ import annotations

from gemini_shared import get_runtime_config_status


def report_runtime_config() -> dict[str, object]:
    """Return non-sensitive metadata about the active runtime configuration."""
    return get_runtime_config_status()
