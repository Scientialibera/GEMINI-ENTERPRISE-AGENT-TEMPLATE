"""Construct the SDK client and the deployment payload."""

from __future__ import annotations

import importlib
from collections.abc import Sequence

import vertexai
from config.settings import runtime_env
from registry import AgentSpec
from vertexai.agent_engines import AdkApp

from .dependencies import export_requirements


def build_app(spec: AgentSpec) -> AdkApp:
    """Reuse the entry point's app rather than constructing a second wrapper."""
    return importlib.import_module(spec.module).app


VERTEX_API_VERSION = "v1beta1"

_STAGING_ROOT = "agent_engine"


def build_client(project_id: str, location: str, staging_bucket: str) -> vertexai.Client:
    vertexai.init(project=project_id, location=location, staging_bucket=staging_bucket)
    return vertexai.Client(
        project=project_id,
        location=location,
        http_options={"api_version": VERTEX_API_VERSION},
    )


def staging_prefix(spec: AgentSpec) -> str:
    """Directory under the staging bucket holding this agent's artifacts.

    The SDK defaults every deployment to a single ``agent_engine/`` directory,
    so two agents sharing a staging bucket overwrite each other's pickle and
    the last one deployed is served for both. The package name is unique per
    registry entry, so scoping by it keeps each agent's artifacts separate.
    """
    return f"{_STAGING_ROOT}/{spec.package_name}"


def deployment_config(
    spec: AgentSpec,
    staging_bucket: str,
    extra_packages: Sequence[str],
) -> dict[str, object]:
    return {
        "requirements": list(export_requirements(spec)),
        "extra_packages": list(extra_packages),
        "staging_bucket": staging_bucket,
        "gcs_dir_name": staging_prefix(spec),
        "env_vars": runtime_env(spec),
    }
