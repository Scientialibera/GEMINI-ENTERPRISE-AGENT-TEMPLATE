"""List Cloud Storage objects using the runtime's own Agent Identity."""

from __future__ import annotations

from gemini_shared.agent_identity import list_bucket_objects

from ..config import PROJECT_ID


def list_storage_objects() -> dict[str, object]:
    """List objects in the configured bucket using the agent's own identity.

    Reports the identity and environment that served the request, so a caller
    can confirm whether Agent Identity or local developer credentials were used.
    """
    return list_bucket_objects(PROJECT_ID)
