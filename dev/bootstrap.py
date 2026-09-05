from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Sequence


GCLOUD = shutil.which("gcloud")

TRUE_VALUES = frozenset({"1", "true", "yes", "on"})
FALSE_VALUES = frozenset({"0", "false", "no", "off"})
PLACEHOLDER_TOKEN = "REPLACE"

CREATE_PROJECT_ENV = "DEV_CREATE_PROJECT_IF_MISSING"
BILLING_ACCOUNT_ENV = "DEV_BILLING_ACCOUNT_ID"
PROJECT_FOLDER_ENV = "DEV_PROJECT_FOLDER_ID"
PROJECT_ORGANIZATION_ENV = "DEV_PROJECT_ORGANIZATION_ID"
ENABLE_APIS_ENV = "DEV_ENABLE_REQUIRED_APIS"
CREATE_STAGING_BUCKET_ENV = "DEV_CREATE_STAGING_BUCKET_IF_MISSING"
STAGING_BUCKET_LOCATION_ENV = "DEV_STAGING_BUCKET_LOCATION"
CONFIG_PARAMETER_ENV = "CONFIG_PARAMETER"
CONFIG_PARAMETER_LOCATION_ENV = "CONFIG_PARAMETER_LOCATION"

DEFAULT_PARAMETER_LOCATION = "global"

REQUIRED_DEV_SERVICES = (
    "aiplatform.googleapis.com",
    "parametermanager.googleapis.com",
    "serviceusage.googleapis.com",
    "storage.googleapis.com",
)


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    value = raw.strip().lower()
    if value in TRUE_VALUES:
        return True
    if value in FALSE_VALUES:
        return False
    raise SystemExit(f"{name} must be true or false.")


def _run(args: Sequence[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    if GCLOUD is None:
        raise SystemExit("Google Cloud CLI is required and must be available on PATH.")
    command = [GCLOUD, *args]
    result = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
    )
    if check and result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise SystemExit(
            f"Command failed: {' '.join(command)}\n"
            f"{detail or 'No error details returned.'}"
        )
    return result


def _exists(args: Sequence[str]) -> bool:
    return _run(args, check=False).returncode == 0


def _real_env_value(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value or PLACEHOLDER_TOKEN in value or value.startswith("<"):
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

    if not _env_bool(CREATE_PROJECT_ENV, False):
        raise SystemExit(
            f"Project '{project_id}' does not exist or is not visible. "
            f"Create it through foundation IaC or set {CREATE_PROJECT_ENV}=true "
            "for a developer sandbox."
        )

    billing_account = _real_env_value(BILLING_ACCOUNT_ENV)
    folder_id = os.getenv(PROJECT_FOLDER_ENV, "").strip()
    organization_id = os.getenv(PROJECT_ORGANIZATION_ENV, "").strip()
    if folder_id and organization_id:
        raise SystemExit(
            f"Set at most one of {PROJECT_FOLDER_ENV} or {PROJECT_ORGANIZATION_ENV}."
        )

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


def ensure_required_services(project_id: str) -> None:
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
    missing = tuple(service for service in REQUIRED_DEV_SERVICES if service not in enabled)
    if not missing:
        return

    if not _env_bool(ENABLE_APIS_ENV, True):
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

    if not _env_bool(CREATE_STAGING_BUCKET_ENV, True):
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


def ensure_runtime_parameter(project_id: str) -> None:
    parameter = _real_env_value(CONFIG_PARAMETER_ENV)
    location = (
        os.getenv(CONFIG_PARAMETER_LOCATION_ENV, DEFAULT_PARAMETER_LOCATION).strip()
        or DEFAULT_PARAMETER_LOCATION
    )

    if parameter.startswith("projects/"):
        command = (
            "parametermanager",
            "parameters",
            "describe",
            parameter,
            "--format=value(name)",
        )
    else:
        command = (
            "parametermanager",
            "parameters",
            "describe",
            parameter,
            f"--project={project_id}",
            f"--location={location}",
            "--format=value(name)",
        )

    if not _exists(command):
        raise SystemExit(
            f"Parameter Manager resource '{parameter}' was not found or is not readable. "
            "Apply the companion Terraform stack or correct CONFIG_PARAMETER."
        )


def prepare_dev_platform(project_id: str, location: str, staging_bucket: str) -> None:
    require_gcloud_auth()
    ensure_project(project_id)
    ensure_required_services(project_id)
    ensure_staging_bucket(project_id, location, staging_bucket)


def ensure_dev_prerequisites(project_id: str, location: str, staging_bucket: str) -> None:
    prepare_dev_platform(project_id, location, staging_bucket)
    ensure_runtime_parameter(project_id)
