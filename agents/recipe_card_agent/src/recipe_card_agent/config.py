"""Bootstrap values this agent resolves once at import."""

from __future__ import annotations

import os

from gemini_shared import get_bootstrap_settings

BOOTSTRAP = get_bootstrap_settings()
PROJECT_ID = BOOTSTRAP.project_id

# Where finished cards and their images are published. The bucket is created on
# first use, so a new environment needs no manual step. Named per environment
# rather than hardcoded, which is what lets dev and prod write to their own.
OUTPUT_BUCKET_ENV = "RECIPE_CARD_BUCKET"
OUTPUT_BUCKET = os.getenv(OUTPUT_BUCKET_ENV, "").strip()

# Cloud Storage location for the bucket when this agent creates it.
OUTPUT_BUCKET_LOCATION = os.getenv("RECIPE_CARD_BUCKET_LOCATION", "").strip() or BOOTSTRAP.location
