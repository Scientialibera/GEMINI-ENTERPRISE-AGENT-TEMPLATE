"""Tools for inspecting runtime settings."""

from .runtime_config import get_runtime_config_status


def report_runtime_config() -> dict[str, object]:
    """Return non-sensitive metadata about the active runtime configuration."""
    return get_runtime_config_status()
