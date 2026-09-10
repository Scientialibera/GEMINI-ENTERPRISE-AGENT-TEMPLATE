"""Environment-specific recipe output settings."""

import os

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
