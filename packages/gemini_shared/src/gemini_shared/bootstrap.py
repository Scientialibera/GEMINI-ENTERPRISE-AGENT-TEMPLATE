"""Resolve the small bootstrap contract used by local and deployed agents."""

from __future__ import annotations

import os
from dataclasses import dataclass

PROJECT_ENV = "GOOGLE_CLOUD_PROJECT"
LOCATION_ENV = "GOOGLE_CLOUD_LOCATION"
CONFIG_PARAMETER_ENV = "CONFIG_PARAMETER"
CONFIG_PARAMETER_LOCATION_ENV = "CONFIG_PARAMETER_LOCATION"
CONFIG_REFRESH_SECONDS_ENV = "CONFIG_REFRESH_SECONDS"
BOOTSTRAP_MODEL_ENV = "BOOTSTRAP_MODEL"
MODEL_LOCATION_ENV = "GEMINI_MODEL_LOCATION"
AUTHORIZATION_ID_ENV = "GEMINI_ENTERPRISE_AUTHORIZATION_ID"

DEFAULT_LOCATION = "us-central1"
DEFAULT_PARAMETER_LOCATION = "global"
DEFAULT_REFRESH_SECONDS = 30
MIN_REFRESH_SECONDS = 5
DEFAULT_BOOTSTRAP_MODEL = "gemini-3.7-flash"
DEFAULT_MODEL_LOCATION = "global"


def _value(name: str, default: str | None = None, *, required: bool = True) -> str | None:
    raw = os.getenv(name)
    value = raw.strip() if raw is not None else (default.strip() if default else None)
    if value and ("REPLACE" in value or value.startswith("<")):
        if not required:
            return None
        raise RuntimeError(f"{name} must contain a real value, not a placeholder.")
    if required and not value:
        raise RuntimeError(f"{name} is required.")
    return value


def _required_value(name: str, default: str | None = None) -> str:
    value = _value(name, default)
    if value is None:
        raise RuntimeError(f"{name} is required.")
    return value


def _int_value(name: str, default: int) -> int:
    raw = _required_value(name, str(default))
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer.") from exc
    if value < MIN_REFRESH_SECONDS:
        raise RuntimeError(f"{name} must be at least {MIN_REFRESH_SECONDS} seconds.")
    return value


@dataclass(frozen=True, slots=True)
class BootstrapSettings:
    project_id: str
    location: str
    config_parameter: str | None
    parameter_location: str
    refresh_seconds: int
    bootstrap_model: str
    model_location: str
    gemini_enterprise_authorization_id: str | None


def _resolve_project_id() -> str:
    """Resolve the project id from the environment, else from ADC.

    Agent Runtime injects GOOGLE_CLOUD_PROJECT and refuses it as a caller-set
    deployment variable, so it cannot be supplied by Terraform. Falling back to
    Application Default Credentials keeps import from failing when the platform
    has not populated the variable, which otherwise crashes the process before
    logging is initialised and yields no diagnosable runtime output.
    """
    # A placeholder must fail loudly rather than fall through to ADC, so it is
    # validated with required=True. Only a genuinely absent value falls back.
    if os.getenv(PROJECT_ENV):
        return _required_value(PROJECT_ENV)

    try:
        import google.auth

        _, adc_project = google.auth.default()
    except Exception as exc:
        raise RuntimeError(
            f"{PROJECT_ENV} is not set and Application Default Credentials could not be "
            f"resolved to determine the project: {exc}"
        ) from exc

    if not adc_project:
        raise RuntimeError(
            f"{PROJECT_ENV} is not set and Application Default Credentials did not supply a "
            "project. Set GOOGLE_CLOUD_PROJECT locally, or verify the Agent Runtime "
            "environment."
        )
    return adc_project


def get_bootstrap_settings(*, require_auth: bool = False) -> BootstrapSettings:
    return BootstrapSettings(
        project_id=_resolve_project_id(),
        location=_required_value(LOCATION_ENV, DEFAULT_LOCATION),
        config_parameter=_value(CONFIG_PARAMETER_ENV, required=False),
        parameter_location=_required_value(
            CONFIG_PARAMETER_LOCATION_ENV,
            DEFAULT_PARAMETER_LOCATION,
        ),
        refresh_seconds=_int_value(CONFIG_REFRESH_SECONDS_ENV, DEFAULT_REFRESH_SECONDS),
        bootstrap_model=_required_value(BOOTSTRAP_MODEL_ENV, DEFAULT_BOOTSTRAP_MODEL),
        model_location=_required_value(MODEL_LOCATION_ENV, DEFAULT_MODEL_LOCATION),
        gemini_enterprise_authorization_id=_value(
            AUTHORIZATION_ID_ENV,
            required=require_auth,
        ),
    )
