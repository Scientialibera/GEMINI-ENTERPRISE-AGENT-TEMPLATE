from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

# Runnable directly as well as imported by deploy/update helpers.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common import (
    ROOT,
    AgentSpec,
    get_agent_spec,
    load_environment,
    load_resource_name,
    require_dev_environment,
)

GCLOUD = shutil.which("gcloud")

IDENTITY_ID_SUFFIX = "_AGENT_IDENTITY_ID"
PROJECT_ROLES_SUFFIX = "_AGENT_IDENTITY_PROJECT_ROLES"
STORAGE_BUCKET_ROLES_SUFFIX = "_AGENT_IDENTITY_STORAGE_BUCKET_ROLES"

ROLE_PATTERN = re.compile(
    r"^(?:roles/[A-Za-z0-9_.]+|"
    r"projects/[A-Za-z0-9._:-]+/roles/[A-Za-z0-9_.]+|"
    r"organizations/[0-9]+/roles/[A-Za-z0-9_.]+)$"
)
DISALLOWED_BASIC_ROLES = frozenset({"roles/owner", "roles/editor"})
REASONING_ENGINE_PATTERN = re.compile(
    r"(?:^|/)locations/(?P<location>[^/]+)/reasoningEngines/(?P<engine_id>[^/]+)$"
)


def agent_identity_id_env(spec: AgentSpec) -> str:
    """Optional assertion for the exact Agent Identity principal."""
    return f"{spec.env_prefix}{IDENTITY_ID_SUFFIX}"


def agent_identity_project_roles_env(spec: AgentSpec) -> str:
    """Per-agent project-scoped role list."""
    return f"{spec.env_prefix}{PROJECT_ROLES_SUFFIX}"


def agent_identity_storage_bucket_roles_env(spec: AgentSpec) -> str:
    """Per-agent bucket-scoped role bindings."""
    return f"{spec.env_prefix}{STORAGE_BUCKET_ROLES_SUFFIX}"


def _validate_role(role: str) -> str:
    if role in DISALLOWED_BASIC_ROLES:
        raise SystemExit(
            f"Refusing broad basic IAM role '{role}'. Use a least-privilege predefined "
            "or custom role instead."
        )
    if not ROLE_PATTERN.fullmatch(role):
        raise SystemExit(
            f"Invalid IAM role '{role}'. Expected roles/<name> or a fully qualified custom role."
        )
    return role


def _roles_from_csv(raw: str) -> tuple[str, ...]:
    roles = [_validate_role(value.strip()) for value in raw.split(",") if value.strip()]
    return tuple(dict.fromkeys(roles))


def requested_project_roles(spec: AgentSpec) -> tuple[str, ...]:
    """Project roles for this exact Agent Identity.

    The spec is the source, so a fresh clone deploys with the access an agent's
    tools require. The environment variable overrides it for a single run,
    which is how an environment grants something the repository should not
    describe.
    """
    override = os.getenv(agent_identity_project_roles_env(spec), "").strip()
    if override:
        return _roles_from_csv(override)
    return tuple(_validate_role(role) for role in spec.agent_identity_project_roles)


def requested_storage_bucket_roles(spec: AgentSpec) -> dict[str, tuple[str, ...]]:
    """Bucket bindings for this exact Agent Identity.

    Read from the spec unless the environment overrides them. A spec names its
    bucket through a ${VARIABLE} placeholder, so the repository says which
    bucket an agent writes to without committing any project's bucket name; a
    placeholder that resolves to nothing is skipped rather than guessed at.
    """
    raw = os.getenv(agent_identity_storage_bucket_roles_env(spec), "").strip()
    if not raw:
        declared: dict[str, tuple[str, ...]] = {}
        for binding in spec.agent_identity_bucket_roles:
            bucket = binding.resolved_bucket()
            if not bucket:
                continue
            declared[bucket] = tuple(_validate_role(role) for role in binding.roles)
        return declared

    bindings: dict[str, tuple[str, ...]] = {}
    for entry in raw.split(";"):
        item = entry.strip()
        if not item:
            continue
        bucket_uri, separator, roles_raw = item.partition("=")
        bucket_uri = bucket_uri.strip()
        if not separator or not roles_raw.strip():
            raise SystemExit(
                f"{agent_identity_storage_bucket_roles_env(spec)} entry '{item}' must use "
                "gs://bucket=role|role."
            )
        if not bucket_uri.startswith("gs://") or "/" in bucket_uri.removeprefix("gs://"):
            raise SystemExit(
                f"Invalid Cloud Storage bucket '{bucket_uri}'. Use a bucket URI such as "
                "gs://example-bucket with no object path."
            )
        if bucket_uri in bindings:
            raise SystemExit(
                f"{agent_identity_storage_bucket_roles_env(spec)} lists "
                f"'{bucket_uri}' more than once."
            )
        roles = tuple(
            dict.fromkeys(
                _validate_role(value.strip()) for value in roles_raw.split("|") if value.strip()
            )
        )
        if not roles:
            raise SystemExit(f"No IAM roles were supplied for '{bucket_uri}'.")
        bindings[bucket_uri] = roles
    return bindings


def _run_gcloud(args: Sequence[str]) -> subprocess.CompletedProcess[str]:
    if GCLOUD is None:
        raise SystemExit("Google Cloud CLI is required and must be available on PATH.")

    command = [GCLOUD, *args]
    result = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise SystemExit(
            f"Command failed: {' '.join(command)}\n{detail or 'No error details returned.'}"
        )
    return result


def _project_number(project_id: str) -> str:
    project_number = _run_gcloud(
        ("projects", "describe", project_id, "--format=value(projectNumber)")
    ).stdout.strip()
    if not project_number.isdigit():
        raise SystemExit(f"Could not resolve the numeric project number for '{project_id}'.")
    return project_number


def _organization_id(project_id: str) -> str | None:
    result = _run_gcloud(
        (
            "projects",
            "get-ancestors",
            project_id,
            "--format=csv[no-heading](type,id)",
        )
    )
    for line in result.stdout.splitlines():
        resource_type, separator, resource_id = line.partition(",")
        if separator and resource_type.strip() == "organization":
            organization_id = resource_id.strip()
            if organization_id.isdigit():
                return organization_id
    return None


def _runtime_coordinates(resource_name: str) -> tuple[str, str]:
    match = REASONING_ENGINE_PATTERN.search(resource_name.strip())
    if not match:
        raise SystemExit(
            "Reasoning Engine resource name must end in "
            "locations/<location>/reasoningEngines/<engine-id>."
        )
    return match.group("location"), match.group("engine_id")


def agent_identity_principal(project_id: str, resource_name: str) -> str:
    """Construct the exact Google-managed Agent Identity principal."""
    project_number = _project_number(project_id)
    organization_id = _organization_id(project_id)
    location, engine_id = _runtime_coordinates(resource_name)

    # Orgless trust domains use "proj-". Documentation shows "project-", which
    # IAM rejects as an unknown member type. Terraform's principal set for the
    # same project uses the same prefix, so the two must stay in step.
    trust_domain = (
        f"agents.global.org-{organization_id}.system.id.goog"
        if organization_id
        else f"agents.global.proj-{project_number}.system.id.goog"
    )
    return (
        f"principal://{trust_domain}/resources/aiplatform/projects/{project_number}"
        f"/locations/{location}/reasoningEngines/{engine_id}"
    )


def apply_agent_identity_iam(
    agent_name: str,
    project_id: str,
    resource_name: str,
    spec: AgentSpec,
) -> str | None:
    """Apply explicitly configured IAM bindings to one deployed Agent Identity."""
    project_roles = requested_project_roles(spec)
    bucket_bindings = requested_storage_bucket_roles(spec)
    configured_identity = os.getenv(agent_identity_id_env(spec), "").strip()

    if not project_roles and not bucket_bindings and not configured_identity:
        print(
            f"AGENT_IDENTITY_IAM={agent_name}: no agent-specific bindings configured; "
            "the runtime keeps only platform baseline grants."
        )
        return None

    principal = agent_identity_principal(project_id, resource_name)
    if configured_identity and configured_identity != principal:
        raise SystemExit(
            f"{agent_identity_id_env(spec)} does not match the Agent Identity created for "
            f"{resource_name}. Expected: {principal}"
        )

    print(f"{agent_identity_id_env(spec)}={principal}")

    for role in project_roles:
        _run_gcloud(
            (
                "projects",
                "add-iam-policy-binding",
                project_id,
                f"--member={principal}",
                f"--role={role}",
                "--condition=None",
                "--quiet",
            )
        )
        print(f"AGENT_IDENTITY_PROJECT_ROLE={role}")

    for bucket_uri, roles in bucket_bindings.items():
        for role in roles:
            _run_gcloud(
                (
                    "storage",
                    "buckets",
                    "add-iam-policy-binding",
                    bucket_uri,
                    f"--member={principal}",
                    f"--role={role}",
                    "--condition=None",
                    f"--project={project_id}",
                    "--quiet",
                )
            )
            print(f"AGENT_IDENTITY_STORAGE_BINDING={bucket_uri}:{role}")

    return principal


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Apply configured IAM bindings to one deployed dev Agent Identity."
    )
    parser.add_argument("--agent", required=True)
    args = parser.parse_args()

    os.chdir(ROOT)
    load_environment(".env.dev")
    spec = get_agent_spec(args.agent)
    project_id, _, _ = require_dev_environment(spec=spec)
    resource_name = load_resource_name(args.agent)
    apply_agent_identity_iam(args.agent, project_id, resource_name, spec)


if __name__ == "__main__":
    main()
