"""Coordinate image request starts across runtimes sharing a storage bucket."""

import hashlib
import random
import time
from datetime import UTC, datetime

from google.api_core.exceptions import NotFound, PreconditionFailed
from google.cloud import storage


def acquire_slot(project: str, bucket: str, model: str, interval: float = 32.0) -> None:
    """Reserve a request start with a generation precondition; fail closed on timeout."""
    key = hashlib.sha256(f"{project}/{model}".encode()).hexdigest()
    blob = storage.Client(project=project).bucket(bucket).blob(f"_coordination/images/{key}")
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        try:
            blob.reload(timeout=10, retry=None)
            generation = blob.generation
            remaining = interval - (datetime.now(UTC) - blob.updated).total_seconds()
        except NotFound:
            generation, remaining = 0, 0
        if remaining > 0:
            time.sleep(min(remaining, max(0, deadline - time.monotonic())))
            continue
        try:
            blob.upload_from_string(b"", if_generation_match=generation, timeout=10, retry=None)
            return
        except PreconditionFailed:
            time.sleep(random.uniform(0.1, 0.5))  # noqa: S311
    raise TimeoutError("Image quota coordination is busy; retry the remaining images later.")
