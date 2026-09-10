from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

import vertexai

# Runnable directly as well as imported by deploy/update helpers.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config.environment import env_bool
from config.settings import load_environment, require_dev_environment
from deploy.state import RuntimeResource, load_resource_name
from gcp import project_number as _project_number
from gcp import run_gcloud as _run_gcloud
from paths import ROOT
from registry import AgentSpec, get_agent_spec

IDENTITY_ID_SUFFIX = "_AGENT_IDENTITY_ID"
PROJECT_ROLES_SUFFIX = "_AGENT_IDENTITY_PROJECT_ROLES"
STORAGE_BUCKET_ROLES_SUFFIX = "_AGENT_IDENTITY_STORAGE_BUCKET_ROLES"

ROLE_PATTERN = re.compile(
    r"^(?:roles/[A-Za-z0-9_.]+|"
    r"projects/[A-Za-z0-9._:-]+/roles/[A-Za-z0-9_.]+|"
    r"organizations/[0-9]+/roles/[A-Za-z0-9_.]+)$"
)
DISALLOWED_BASIC_ROLES = frozenset({"roles/owner", "roles/editor"})
PRINCIPAL_SCHEME = "principal://"
UNSUPPORTED_BUCKET_ROLES = frozenset(
    f"roles/storage.legacyBucket{suffix}" for suffix in ("Reader", "Writer", "Owner")
)

# Terraform and the sandbox helper consume the same runtime policy.
_RUNTIME_POLICY = json.loads((ROOT / "infrastructure/runtime_iam_policy.json").read_text())
BASELINE_AGENT_IDENTITY_ROLES = tuple(_RUNTIME_POLICY["baseline_project_roles"])
STAGING_BUCKET_READER_ROLE = _RUNTIME_POLICY["staging_bucket_reader_role"]
BASELINE_ROLES_ENV = "DEV_GRANT_AGENT_IDENTITY_BASELINE"


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
    if role in UNSUPPORTED_BUCKET_ROLES:
        raise SystemExit(f"Agent Identity does not support legacy bucket role '{role}'.")
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


def _trust_domain(project_id: str, project_number: str) -> str:
    """Trust domain the project's Agent Identities belong to.

    Orgless trust domains use "proj-". Documentation shows "project-", which
    IAM rejects as an unknown member type. Terraform's principal set for the
    same project uses the same prefix, so the two must stay in step.
    """
    organization_id = _organization_id(project_id)
    if organization_id:
        return f"agents.global.org-{organization_id}.system.id.goog"
    return f"agents.global.proj-{project_number}.system.id.goog"


def agent_identity_principal(project_id: str, resource_name: str) -> str:
    """Read the deployed identity and verify its project and runtime resource."""
    project_number = _project_number(project_id)
    resource = RuntimeResource.parse(resource_name)
    location, engine_id = resource.location, resource.engine
    if resource.project not in (project_id, project_number):
        raise SystemExit("The runtime belongs to a different project; no IAM grants were made.")
    client = vertexai.Client(
        project=project_id, location=location, http_options={"api_version": "v1beta1"}
    )
    remote = client.agent_engines.get(name=resource_name)
    spec = remote.api_resource.spec
    identity_type = getattr(spec.identity_type, "value", spec.identity_type)
    # The API reports effective_identity without the scheme, as
    # "agents.global.<domain>/resources/...", while IAM --member= requires the
    # "principal://" form. Normalise on read so the check below and the grants
    # that consume this value agree on one representation.
    principal = spec.effective_identity or ""
    if principal and not principal.startswith(PRINCIPAL_SCHEME):
        principal = f"{PRINCIPAL_SCHEME}{principal}"
    expected_path = (
        f"/resources/aiplatform/projects/{project_number}/locations/{location}"
        f"/reasoningEngines/{engine_id}"
    )
    if (
        identity_type != "AGENT_IDENTITY"
        or not principal.startswith(f"{PRINCIPAL_SCHEME}agents.global.")
        or not principal.endswith(expected_path)
    ):
        raise SystemExit("The runtime has no matching Agent Identity; no IAM grants were made.")
    return principal


def agent_identity_principal_set(project_id: str) -> str:
    """Principal set covering every Agent Identity in the project.

    Roles granted here reach runtimes that do not exist yet, which is what lets
    an agent be deployed without an infrastructure change.
    """
    project_number = _project_number(project_id)
    return (
        f"principalSet://{_trust_domain(project_id, project_number)}"
        f"/attribute.platformContainer/aiplatform/projects/{project_number}"
    )


def ensure_baseline_roles(project_id: str, staging_bucket: str | None = None) -> tuple[str, ...]:
    """Grant every Agent Identity in the project the roles a runtime needs.

    Terraform owns this in a managed environment. A sandbox with no platform
    stack would otherwise deploy an agent that starts and then fails on its
    first request, because it reads its own configuration under an identity
    permitted to read nothing. Granting is idempotent, so running it where
    Terraform already applied the same bindings changes nothing.

    Returns the roles granted, empty when the caller opted out.
    """
    if not env_bool(BASELINE_ROLES_ENV, False):
        return ()

    bucket = (
        (staging_bucket or os.getenv("DEV_STAGING_BUCKET", "")).removeprefix("gs://").strip("/")
    )
    if not bucket or "/" in bucket:
        raise SystemExit("A staging bucket is required before granting baseline runtime access.")
    principal_set = agent_identity_principal_set(project_id)
    for role in BASELINE_AGENT_IDENTITY_ROLES:
        _run_gcloud(
            (
                "projects",
                "add-iam-policy-binding",
                project_id,
                f"--member={principal_set}",
                f"--role={role}",
                "--condition=None",
                "--quiet",
            )
        )
        print(f"BASELINE_AGENT_IDENTITY_ROLE={role}")
    _run_gcloud(
        (
            "storage",
            "buckets",
            "add-iam-policy-binding",
            f"gs://{bucket}",
            f"--member={principal_set}",
            f"--role={STAGING_BUCKET_READER_ROLE}",
            "--condition=None",
            "--quiet",
        )
    )
    return BASELINE_AGENT_IDENTITY_ROLES


def apply_agent_identity_iam(
    agent_name: str,
    project_id: str,
    resource_name: str,
    spec: AgentSpec,
) -> str | None:
    """Add configured bindings. Existing grants are never revoked by this helper."""
    project_roles = requested_project_roles(spec)
    bucket_bindings = requested_storage_bucket_roles(spec)
    configured_identity = os.getenv(agent_identity_id_env(spec), "").strip()

    if not project_roles and not bucket_bindings and not configured_identity:
        print(
            f"AGENT_IDENTITY_IAM={agent_name}: no agent-specific bindings configured; "
            "existing grants are unchanged. This helper only adds permissions."
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
    project_id, location, _ = require_dev_environment(spec=spec)
    resource_name = load_resource_name(args.agent, project_id, location)
    apply_agent_identity_iam(args.agent, project_id, resource_name, spec)


if __name__ == "__main__":
    main()
