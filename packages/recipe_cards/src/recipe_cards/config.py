"""Environment-specific recipe output settings."""

import os

from gemini_shared import get_bootstrap_settings

PROJECT_ID = get_bootstrap_settings().project_id
OUTPUT_BUCKET_ENV = "RECIPE_CARD_BUCKET"
OUTPUT_BUCKET = os.getenv(OUTPUT_BUCKET_ENV, "").strip()
