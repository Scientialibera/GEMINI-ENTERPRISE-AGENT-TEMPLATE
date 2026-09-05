"""Resolve the small bootstrap contract used by local and deployed agents."""

from __future__ import annotations

from dataclasses import dataclass
import os


def _value(name: str, default: str | None = None, *, required: bool = True) -> str | None:
    raw = os.getenv(name)
    value = raw.strip() if raw is not None else (default.strip() if default else None)
    if required and not value:
        raise RuntimeError(f"{name} is required.")
    return value


def _int_value(name: str, default: int) -> int:
    raw = _value(name, str(default))
    assert raw is not None
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer.") from exc
    if value < 5:
        raise RuntimeError(f"{name} must be at least 5 seconds.")
    return value


@dataclass(frozen=True)
class BootstrapSettings:
    project_id: str
    location: str
    config_parameter: str | None
    parameter_location: str
    refresh_seconds: int
    bootstrap_model: str
    model_location: str
    gemini_enterprise_authorization_id: str | None


def get_bootstrap_settings(*, require_auth: bool = False) -> BootstrapSettings:
    authorization_id = _value(
        "GEMINI_ENTERPRISE_AUTHORIZATION_ID",
        required=require_auth,
    )
    return BootstrapSettings(
        project_id=str(_value("GOOGLE_CLOUD_PROJECT")),
        location=str(_value("GOOGLE_CLOUD_LOCATION", "us-central1")),
        config_parameter=_value("CONFIG_PARAMETER", required=False),
        parameter_location=str(_value("CONFIG_PARAMETER_LOCATION", "global")),
        refresh_seconds=_int_value("CONFIG_REFRESH_SECONDS", 30),
        bootstrap_model=str(_value("BOOTSTRAP_MODEL", "gemini-3.7-flash")),
        model_location=str(_value("GEMINI_MODEL_LOCATION", "global")),
        gemini_enterprise_authorization_id=authorization_id,
    )
