from __future__ import annotations

import hashlib
import json
import os
import shutil
from collections.abc import Sequence
from typing import TYPE_CHECKING
from uuid import uuid4

from gcp import run_gcloud as _run
from gemini_shared.config.bootstrap import DEFAULT_BOOTSTRAP_MODEL, DEFAULT_PARAMETER_LOCATION
from gemini_shared.config.runtime_config import DEFAULT_IMAGE_MODEL, DEFAULT_MAX_REFERENCE_IMAGES

from config.environment import configured_value, env_bool

if TYPE_CHECKING:
    from gemini_shared.config.runtime_config import RuntimeConfig
    from google.cloud.parametermanager_v1 import ParameterManagerClient
    from registry import AgentSpec

GCLOUD = shutil.which("gcloud")

CREATE_PROJECT_ENV = "DEV_CREATE_PROJECT_IF_MISSING"
BILLING_ACCOUNT_ENV = "DEV_BILLING_ACCOUNT_ID"
PROJECT_FOLDER_ENV = "DEV_PROJECT_FOLDER_ID"
PROJECT_ORGANIZATION_ENV = "DEV_PROJECT_ORGANIZATION_ID"
ENABLE_APIS_ENV = "DEV_ENABLE_REQUIRED_APIS"
CREATE_STAGING_BUCKET_ENV = "DEV_CREATE_STAGING_BUCKET_IF_MISSING"
STAGING_BUCKET_LOCATION_ENV = "DEV_STAGING_BUCKET_LOCATION"
CONFIG_PARAMETER_ENV = "CONFIG_PARAMETER"
CONFIG_PARAMETER_LOCATION_ENV = "CONFIG_PARAMETER_LOCATION"


REQUIRED_DEV_SERVICES = (
    "aiplatform.googleapis.com",
    "parametermanager.googleapis.com",
    "serviceusage.googleapis.com",
    "storage.googleapis.com",
)


def _exists(args: Sequence[str]) -> bool:
    return _run(args, check=False).returncode == 0


def _real_env_value(name: str) -> str:
    value = configured_value(name)
    if not value:
        raise SystemExit(f"{name} must contain a real value.")
    return value


def require_gcloud_auth() -> None:
    if GCLOUD is None:
        raise SystemExit("Google Cloud CLI is required and must be available on PATH.")

    active_account = _run(
        ("auth", "list", "--filter=status:ACTIVE", "--format=value(account)"),
        check=False,
    ).stdout.strip()
    if not active_account:
        raise SystemExit("No active gcloud account. Run: gcloud auth login")

    adc = _run(
        ("auth", "application-default", "print-access-token"),
        check=False,
    )
    if adc.returncode != 0:
        raise SystemExit(
            "Application Default Credentials are not configured. Run: "
            "gcloud auth application-default login"
        )


def ensure_project(project_id: str) -> None:
    if _exists(("projects", "describe", project_id, "--format=value(projectId)")):
        return

    if not env_bool(CREATE_PROJECT_ENV, False):
        raise SystemExit(
            f"Project '{project_id}' does not exist or is not visible. "
            f"Create it through foundation IaC or set {CREATE_PROJECT_ENV}=true "
            "for a developer sandbox."
        )

    billing_account = _real_env_value(BILLING_ACCOUNT_ENV)
    folder_id = os.getenv(PROJECT_FOLDER_ENV, "").strip()
    organization_id = os.getenv(PROJECT_ORGANIZATION_ENV, "").strip()
    if folder_id and organization_id:
        raise SystemExit(f"Set at most one of {PROJECT_FOLDER_ENV} or {PROJECT_ORGANIZATION_ENV}.")

    create_args = ["projects", "create", project_id, "--quiet"]
    if folder_id:
        create_args.append(f"--folder={folder_id}")
    elif organization_id:
        create_args.append(f"--organization={organization_id}")
    _run(create_args)

    _run(
        (
            "billing",
            "projects",
            "link",
            project_id,
            f"--billing-account={billing_account}",
            "--quiet",
        )
    )


def ensure_required_services(
    project_id: str,
    additional_services: Sequence[str] = (),
) -> None:
    services = tuple(dict.fromkeys((*REQUIRED_DEV_SERVICES, *additional_services)))
    result = _run(
        (
            "services",
            "list",
            "--enabled",
            f"--project={project_id}",
            "--format=value(config.name)",
        )
    )
    enabled = {line.strip() for line in result.stdout.splitlines() if line.strip()}
    missing = tuple(service for service in services if service not in enabled)
    if not missing:
        return

    if not env_bool(ENABLE_APIS_ENV, True):
        raise SystemExit(
            "Required APIs are disabled: "
            f"{', '.join(missing)}. Enable them or set {ENABLE_APIS_ENV}=true."
        )

    _run(
        (
            "services",
            "enable",
            *missing,
            f"--project={project_id}",
            "--quiet",
        )
    )


def ensure_staging_bucket(project_id: str, location: str, bucket_uri: str) -> None:
    if _exists(
        (
            "storage",
            "buckets",
            "describe",
            bucket_uri,
            f"--project={project_id}",
        )
    ):
        return

    if not env_bool(CREATE_STAGING_BUCKET_ENV, True):
        raise SystemExit(
            f"Staging bucket '{bucket_uri}' is missing. Create it or set "
            f"{CREATE_STAGING_BUCKET_ENV}=true."
        )

    bucket_location = os.getenv(STAGING_BUCKET_LOCATION_ENV, "").strip() or location
    _run(
        (
            "storage",
            "buckets",
            "create",
            bucket_uri,
            f"--project={project_id}",
            f"--location={bucket_location}",
            "--uniform-bucket-level-access",
            "--quiet",
        )
    )


def _parameter_client(location: str) -> ParameterManagerClient:
    """Create an ADC client for the parameter's location."""
    from google.cloud import parametermanager_v1

    return parametermanager_v1.ParameterManagerClient(
        client_options={"api_endpoint": _parameter_endpoint(location)}
    )


def _add_parameter_version(
    project_id: str, parameter: str, location: str, version_id: str, payload: str
) -> None:
    from google.cloud import parametermanager_v1

    _parameter_client(location).create_parameter_version(
        parent=f"projects/{project_id}/locations/{location}/parameters/{parameter}",
        parameter_version_id=version_id,
        parameter_version=parametermanager_v1.ParameterVersion(
            payload=parametermanager_v1.ParameterVersionPayload(data=payload.encode("utf-8"))
        ),
    )


def _publish_instruction(
    project_id: str, parameter: str, location: str, current: RuntimeConfig, prompt: str
) -> None:
    """Publish a new version carrying an edited prompt, keeping other settings."""
    config = current.model_dump()
    config["instruction"] = prompt
    snapshot = {key: value for key, value in config.items() if key != "config_revision"}
    digest = hashlib.sha256(json.dumps(snapshot, sort_keys=True).encode("utf-8")).hexdigest()[:12]
    revision = f"prompt-{digest}-{uuid4().hex}"
    config["config_revision"] = revision
    _add_parameter_version(project_id, parameter, location, revision, json.dumps(config))
    print(f"INSTRUCTION_PUBLISHED={revision}")


def _create_runtime_parameter(project_id: str, parameter: str, location: str, prompt: str) -> None:
    """Create the runtime parameter with initial settings and the agent's prompt."""
    payload = json.dumps(
        {
            "config_revision": "bootstrap-v1",
            "model": os.getenv("BOOTSTRAP_MODEL", "").strip() or DEFAULT_BOOTSTRAP_MODEL,
            "image_model": os.getenv("IMAGE_MODEL", "").strip() or DEFAULT_IMAGE_MODEL,
            "max_reference_images": DEFAULT_MAX_REFERENCE_IMAGES,
            "instruction": (
                prompt
                or os.getenv("AGENT_INSTRUCTION", "").strip()
                or "You are a helpful enterprise assistant. Answer concisely."
            ),
            "environment": os.getenv("ENVIRONMENT", "dev").strip() or "dev",
            "log_level": "INFO",
        }
    )

    from google.cloud import parametermanager_v1

    _parameter_client(location).create_parameter(
        parent=f"projects/{project_id}/locations/{location}",
        parameter_id=parameter,
        parameter=parametermanager_v1.Parameter(format_=parametermanager_v1.ParameterFormat.JSON),
    )
    _add_parameter_version(project_id, parameter, location, "bootstrap-v1", payload)
    print(f"RUNTIME_PARAMETER_CREATED={parameter}")


def _parameter_endpoint(location: str) -> str:
    """Regional Parameter Manager endpoint; global uses the default host."""
    if location == DEFAULT_PARAMETER_LOCATION:
        return "parametermanager.googleapis.com"
    return f"parametermanager.{location}.rep.googleapis.com"


def ensure_runtime_parameter(project_id: str, spec: AgentSpec | None = None) -> None:
    """Create or validate runtime settings, then publish any prompt change."""
    parameter = _real_env_value(CONFIG_PARAMETER_ENV)
    location = os.getenv(CONFIG_PARAMETER_LOCATION_ENV, "").strip() or DEFAULT_PARAMETER_LOCATION
    prompt = spec.read_prompt() if spec is not None else ""

    from gemini_shared import get_runtime_config

    try:
        current = get_runtime_config(force_refresh=True)
    except Exception as exc:
        if "RESOURCE_NOT_FOUND" not in str(exc) and "does not exist" not in str(exc):
            raise SystemExit(
                f"Parameter Manager resource '{parameter}' was not readable with Application "
                f"Default Credentials: {exc}. Correct {CONFIG_PARAMETER_ENV}, or re-run "
                "`gcloud auth application-default login`."
            ) from exc
        _create_runtime_parameter(project_id, parameter, location, prompt)
        try:
            get_runtime_config(force_refresh=True)
        except Exception as exc:
            raise SystemExit(f"Created '{parameter}' but it is still not readable: {exc}.") from exc
        return

    # Keep the other live settings when publishing a prompt change.
    if prompt and prompt != current.instruction:
        _publish_instruction(project_id, parameter, location, current, prompt)


def prepare_dev_platform(
    project_id: str,
    location: str,
    staging_bucket: str,
    *,
    additional_services: Sequence[str] = (),
) -> None:
    require_gcloud_auth()
    ensure_project(project_id)
    ensure_required_services(project_id, additional_services)
    ensure_staging_bucket(project_id, location, staging_bucket)


def ensure_dev_prerequisites(
    project_id: str, location: str, staging_bucket: str, spec: AgentSpec | None = None
) -> None:
    prepare_dev_platform(project_id, location, staging_bucket)
    ensure_runtime_parameter(project_id, spec)
