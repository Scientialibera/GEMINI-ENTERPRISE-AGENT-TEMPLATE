"""Parse developer environment settings."""

import os

TRUE_VALUES = frozenset({"1", "true", "yes", "on"})
FALSE_VALUES = frozenset({"0", "false", "no", "off"})


def env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    value = raw.strip().lower()
    if value in TRUE_VALUES:
        return True
    if value in FALSE_VALUES:
        return False
    raise SystemExit(f"{name} must be true or false.")


def configured_value(name: str) -> str:
    """Return a stripped value, or an empty string for an unset placeholder."""
    value = os.getenv(name, "").strip()
    return "" if "REPLACE" in value or "<" in value else value
