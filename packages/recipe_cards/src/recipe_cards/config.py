"""Environment-specific recipe output settings."""

import os
import re

from gemini_shared import get_bootstrap_settings

PROJECT_ID = get_bootstrap_settings().project_id
OUTPUT_BUCKET_ENV = "RECIPE_CARD_BUCKET"
OUTPUT_BUCKET = os.getenv(OUTPUT_BUCKET_ENV, "").strip()

# Cards live under one use-case prefix so a bucket can serve more than this
# agent. Declared in AgentSpec.runtime_env; the default keeps a bare local run
# working. Trailing slashes are stripped so paths join predictably.
USE_CASE_PREFIX_ENV = "RECIPE_CARD_PREFIX"
USE_CASE_PREFIX = os.getenv(USE_CASE_PREFIX_ENV, "").strip().strip("/") or "recipe-cards"


def dish_prefix(slug: str) -> str:
    """Storage prefix holding every run of one dish."""
    return f"{USE_CASE_PREFIX}/{slug}/"


# One path segment: letters, digits, dot, underscore, hyphen. No slash, no "..",
# nothing that could climb out of the use-case root when joined to it.
SAFE_SEGMENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,120}$")


def resolve_relative(path: str) -> str:
    """Turn a caller-supplied relative path into an object name under the root.

    The model only ever names paths a listing tool handed it, and this is what
    makes that guarantee hold: every segment must be an ordinary name, so a
    path cannot traverse upwards or absolutize itself out of the prefix.
    """
    cleaned = path.strip()
    # An absolute path is refused rather than quietly stripped to a relative
    # one: it was meant to point somewhere else, so resolving it under the root
    # would silently substitute a different object for the one asked for.
    if cleaned.startswith("/"):
        raise ValueError(f"Unusable path '{path}'. Asset paths are relative to the card store.")
    cleaned = cleaned.rstrip("/")
    if not cleaned:
        raise ValueError("An empty path cannot be resolved.")
    segments = cleaned.split("/")
    if not all(SAFE_SEGMENT.match(segment) for segment in segments):
        raise ValueError(
            f"Unusable path '{path}'. Use a relative path exactly as a listing tool returned it."
        )
    return f"{USE_CASE_PREFIX}/{'/'.join(segments)}"
