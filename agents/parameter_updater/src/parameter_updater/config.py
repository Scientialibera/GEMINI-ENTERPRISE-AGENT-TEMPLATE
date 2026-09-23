"""Bootstrap values this agent resolves once at import."""

from __future__ import annotations

from gemini_shared import get_bootstrap_settings

BOOTSTRAP = get_bootstrap_settings()
PROJECT_ID = BOOTSTRAP.project_id
