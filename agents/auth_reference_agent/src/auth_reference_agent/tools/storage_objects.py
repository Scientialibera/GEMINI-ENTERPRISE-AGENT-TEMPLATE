"""List Cloud Storage objects using the runtime's own Agent Identity."""

from __future__ import annotations

from gemini_shared.connectors.cloud_storage import list_bucket_objects

from ..config import PROJECT_ID


def list_storage_objects() -> dict[str, object]:
    """List bucket objects using the agent's own identity, reporting which was used."""
    return list_bucket_objects(PROJECT_ID)
