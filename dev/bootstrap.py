from __future__ import annotations

import os
import shutil
import subprocess


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
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    raise SystemExit(f"{name} must be true or false.")


def _run(args: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(args, check=False, capture_output=True, text=True)
    if check and result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise SystemExit(
            f"Command failed: {' '.join(args)}\n{detail or 'No error details returned.'}"
        )
    return result


def _exists(args: list[str]) -> bool:
    return _run(args, check=False).returncode == 0


def require_gcloud_auth() -> None:
    if shutil.which("gcloud") is None:
        raise SystemExit("Google Cloud CLI is required.")
    active = _run(
        ["gcloud", "auth", "list", "--filter=status:ACTIVE", "--format=value(account)"],
        check=False,
    ).stdout.strip()
    if not active:
        raise SystemExit("No active gcloud account. Run: gcloud auth login")
    adc = _run(
        ["gcloud", "auth", "application-default", "print-access-token"],
        check=False,
    )
    if adc.returncode != 0:
        raise SystemExit(
            "Application Default Credentials are not configured. Run: "
            "gcloud auth application-default login"
        )


def ensure_project(project_id: str) -> None:
    if _exists(["gcloud", "projects", "describe", project_id, "--format=value(projectId)"]):
        return
    if not _env_bool("DEV_CREATE_PROJECT_IF_MISSING", False):
        raise SystemExit(
            f"Project '{project_id}' does not exist or is not visible. "
            "Create it through foundation IaC, or set DEV_CREATE_PROJECT_IF_MISSING=true "
            "for a developer sandbox."
        )

    billing = os.getenv("DEV_BILLING_ACCOUNT_ID", "").strip()
    if not billing or "REPLACE" in billing:
        raise SystemExit(
            "DEV_BILLING_ACCOUNT_ID is required when DEV_CREATE_PROJECT_IF_MISSING=true."
        )
    folder = os.getenv("DEV_PROJECT_FOLDER_ID", "").strip()
    organization = os.getenv("DEV_PROJECT_ORGANIZATION_ID", "").strip()
    if folder and organization:
        raise SystemExit("Set at most one of DEV_PROJECT_FOLDER_ID or DEV_PROJECT_ORGANIZATION_ID.")

    command = ["gcloud", "projects", "create", project_id, "--quiet"]
    if folder:
        command.append(f"--folder={folder}")
    elif organization:
        command.append(f"--organization={organization}")
    _run(command)
    _run(
        [
            "gcloud",
            "billing",
            "projects",
            "link",
            project_id,
            f"--billing-account={billing}",
            "--quiet",
        ]
    )


def ensure_required_services(project_id: str) -> None:
    result = _run(
        [
            "gcloud",
            "services",
            "list",
            "--enabled",
            f"--project={project_id}",
            "--format=value(config.name)",
        ]
    )
    enabled = {line.strip() for line in result.stdout.splitlines() if line.strip()}
    missing = [service for service in REQUIRED_DEV_SERVICES if service not in enabled]
    if not missing:
        return
    if not _env_bool("DEV_ENABLE_REQUIRED_APIS", True):
        raise SystemExit(
            "Required APIs are disabled: "
            f"{', '.join(missing)}. Enable them or set DEV_ENABLE_REQUIRED_APIS=true."
        )
    _run(
        [
            "gcloud",
            "services",
            "enable",
            *missing,
            f"--project={project_id}",
            "--quiet",
        ]
    )


def ensure_staging_bucket(project_id: str, location: str, bucket_uri: str) -> None:
    if _exists(
        ["gcloud", "storage", "buckets", "describe", bucket_uri, f"--project={project_id}"]
    ):
        return
    if not _env_bool("DEV_CREATE_STAGING_BUCKET_IF_MISSING", True):
        raise SystemExit(
            f"Staging bucket '{bucket_uri}' is missing. Create it or enable "
            "DEV_CREATE_STAGING_BUCKET_IF_MISSING."
        )
    bucket_location = os.getenv("DEV_STAGING_BUCKET_LOCATION", "").strip() or location
    _run(
        [
            "gcloud",
            "storage",
            "buckets",
            "create",
            bucket_uri,
            f"--project={project_id}",
            f"--location={bucket_location}",
            "--uniform-bucket-level-access",
            "--quiet",
        ]
    )


def ensure_runtime_parameter(project_id: str) -> None:
    parameter = os.getenv("CONFIG_PARAMETER", "").strip()
    if not parameter or "REPLACE" in parameter or parameter.startswith("<"):
        raise SystemExit(
            "CONFIG_PARAMETER must contain the Terraform runtime_config_parameter output."
        )
    location = os.getenv("CONFIG_PARAMETER_LOCATION", "global").strip() or "global"
    if parameter.startswith("projects/"):
        command = [
            "gcloud",
            "parametermanager",
            "parameters",
            "describe",
            parameter,
            "--format=value(name)",
        ]
    else:
        command = [
            "gcloud",
            "parametermanager",
            "parameters",
            "describe",
            parameter,
            f"--project={project_id}",
            f"--location={location}",
            "--format=value(name)",
        ]
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
