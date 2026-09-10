"""Read and write Cloud Storage using the runtime's credentials."""

from __future__ import annotations

import os

from google.api_core import exceptions
from google.cloud import storage

from ..config.runtime_config import get_runtime_config

RUNTIME_ENGINE_ID_ENV = "GOOGLE_CLOUD_AGENT_ENGINE_ID"
AUTHENTICATION_MODE_AGENT_IDENTITY = "Agent Identity"
AUTHENTICATION_MODE_LOCAL_ADC = "local ADC"
EXECUTION_ENVIRONMENT_RUNTIME = "Agent Runtime"
EXECUTION_ENVIRONMENT_LOCAL = "local development"
LOCAL_ENGINE_ID = "not available locally"
GS_URI_PREFIX = "gs://"


def list_bucket_objects(project_id: str) -> dict[str, object]:
    """List a bounded number of objects, reporting which identity served it."""
    runtime = get_runtime_config()
    bucket_name = runtime.agent_identity_bucket_name
    if not bucket_name:
        raise RuntimeError(
            "agent_identity_bucket_name is required to use the Agent Identity storage example."
        )

    client = storage.Client(project=project_id)
    object_names = [
        blob.name
        for blob in client.list_blobs(bucket_name, max_results=runtime.storage_object_limit)
    ]

    runtime_engine_id = os.getenv(RUNTIME_ENGINE_ID_ENV)
    running_on_runtime = bool(runtime_engine_id)
    return {
        "authentication_mode": (
            AUTHENTICATION_MODE_AGENT_IDENTITY
            if running_on_runtime
            else AUTHENTICATION_MODE_LOCAL_ADC
        ),
        "execution_environment": (
            EXECUTION_ENVIRONMENT_RUNTIME if running_on_runtime else EXECUTION_ENVIRONMENT_LOCAL
        ),
        "reasoning_engine_id": runtime_engine_id or LOCAL_ENGINE_ID,
        "bucket": bucket_name,
        "object_count_returned": len(object_names),
        "objects": object_names,
    }


def ensure_bucket(project_id: str, bucket_name: str, location: str) -> bool:
    """Create the bucket when it is missing, tolerating a writer-only identity.

    An output bucket is the agent's own working store rather than shared
    infrastructure, so creating it on first use keeps a new deployment from
    needing a manual step.

    A least-privilege runtime is granted object access on one bucket and
    nothing at the project level, so it can write objects while lacking both
    storage.buckets.get and storage.buckets.create. Existence is therefore
    treated as unknown rather than false when the check is refused: the bucket
    is almost certainly there, and the upload that follows is the real test.

    Returns:
        True when this call created the bucket.
    """
    client = storage.Client(project=project_id)
    bucket = client.bucket(bucket_name)
    try:
        if bucket.exists():
            return False
    except exceptions.Forbidden:
        # Cannot inspect it, so assume it exists and let the upload decide.
        return False

    # Uniform access keeps object ACLs from drifting away from the bucket
    # policy, which is what the platform's IAM assumes.
    bucket.iam_configuration.uniform_bucket_level_access_enabled = True
    try:
        client.create_bucket(bucket, location=location)
    except exceptions.Conflict:
        # Created concurrently, or owned by someone this identity cannot see.
        return False
    return True


def upload_bytes(
    project_id: str,
    bucket_name: str,
    object_name: str,
    data: bytes,
    content_type: str,
    *,
    create_only: bool = False,
) -> str:
    """Upload one object and return its gs:// URI."""
    client = storage.Client(project=project_id)
    blob = client.bucket(bucket_name).blob(object_name)
    blob.upload_from_string(
        data, content_type=content_type, if_generation_match=0 if create_only else None
    )
    return f"gs://{bucket_name}/{object_name}"


def download_bytes(project_id: str, uri: str, *, max_bytes: int | None = None) -> bytes:
    """Download an object, optionally limiting bytes transferred and retained."""
    bucket_name, object_name = parse_gs_uri(uri)
    client = storage.Client(project=project_id)
    blob = client.bucket(bucket_name).blob(object_name)
    if max_bytes is None:
        return blob.download_as_bytes()
    if max_bytes < 1:
        raise ValueError("max_bytes must be positive.")
    data = blob.download_as_bytes(start=0, end=max_bytes, raw_download=True)
    if len(data) > max_bytes:
        raise ValueError("Cloud Storage object exceeds the download limit.")
    return data


def list_objects(
    project_id: str,
    bucket_name: str,
    prefix: str,
    *,
    limit: int,
    delimiter: str | None = None,
) -> tuple[list[str], list[str], bool]:
    """List object names under a prefix, and the sub-prefixes beneath it.

    A delimiter makes this one cheap metadata call per level rather than a walk
    of every object: Cloud Storage returns the immediate children as prefixes
    instead of expanding them.

    Returns:
        The object names, the child prefixes, and whether the limit truncated
        the result. Truncation is reported rather than hidden, so a caller can
        say the list is partial instead of implying it is complete.
    """
    if limit < 1:
        raise ValueError("limit must be positive.")
    client = storage.Client(project=project_id)
    # One past the limit distinguishes "exactly full" from "there is more".
    iterator = client.list_blobs(
        bucket_name, prefix=prefix, delimiter=delimiter, max_results=limit + 1
    )
    names = [blob.name for blob in iterator]
    truncated = len(names) > limit
    return names[:limit], sorted(iterator.prefixes), truncated


def parse_gs_uri(uri: str) -> tuple[str, str]:
    """Split a gs://bucket/object URI into its two parts."""
    if not uri.startswith(GS_URI_PREFIX):
        raise ValueError(f"Not a Cloud Storage URI: {uri}")
    bucket_name, _, object_name = uri.removeprefix(GS_URI_PREFIX).partition("/")
    if not bucket_name or not object_name:
        raise ValueError(f"Cloud Storage URI must name a bucket and an object: {uri}")
    return bucket_name, object_name
