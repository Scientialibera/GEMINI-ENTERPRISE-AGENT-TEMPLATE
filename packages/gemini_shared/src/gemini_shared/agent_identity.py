"""Cloud Storage access under the runtime's own Agent Identity.

Deployed, Application Default Credentials resolve to the Agent Engine's Agent
Identity; locally they resolve to the developer. The same code therefore runs in
both places, and the returned payload reports which identity was used.

This module has no delegated-auth dependency, so an agent can use it without a
Gemini Enterprise authorization.
"""

from __future__ import annotations

import os

from google.cloud import storage

from .runtime_config import get_runtime_config

RUNTIME_ENGINE_ID_ENV = "GOOGLE_CLOUD_AGENT_ENGINE_ID"
AUTHENTICATION_MODE_AGENT_IDENTITY = "Agent Identity"
AUTHENTICATION_MODE_LOCAL_ADC = "local ADC"
EXECUTION_ENVIRONMENT_RUNTIME = "Agent Runtime"
EXECUTION_ENVIRONMENT_LOCAL = "local development"
LOCAL_ENGINE_ID = "not available locally"


def list_bucket_objects(project_id: str) -> dict[str, object]:
    """List a bounded number of objects using Agent Identity or local ADC.

    Returns the object names plus the identity and environment that served the
    request, so a caller can confirm which credentials were used.
    """
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
