"""Bootstrap values this workflow resolves once at import.

The workflow publishes to the same bucket as the conversational agent and uses
the same tools, so it reads that agent's configuration rather than defining a
second copy of it.
"""

from __future__ import annotations

from gemini_shared import get_bootstrap_settings
from recipe_card_agent.config import (
    OUTPUT_BUCKET,
    OUTPUT_BUCKET_ENV,
    OUTPUT_BUCKET_LOCATION,
    PROJECT_ID,
)

BOOTSTRAP = get_bootstrap_settings()

__all__ = [
    "BOOTSTRAP",
    "OUTPUT_BUCKET",
    "OUTPUT_BUCKET_ENV",
    "OUTPUT_BUCKET_LOCATION",
    "PROJECT_ID",
]
