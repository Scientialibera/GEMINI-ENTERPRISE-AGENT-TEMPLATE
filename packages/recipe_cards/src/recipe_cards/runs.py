"""Session-owned recipe runs and their generated assets."""

from __future__ import annotations

import re
import secrets
import time
from typing import Any

from google.adk.tools import ToolContext

RUNS_KEY = "recipe_card_runs"
MAX_SESSION_RUNS = 8
UNSAFE_NAME = re.compile(r"[^a-z0-9]+")


def safe_slug(value: str, fallback: str = "recipe") -> str:
    """Return a bounded storage path segment."""
    return UNSAFE_NAME.sub("-", value.strip().lower()).strip("-")[:100].rstrip("-") or fallback


def new_run_id() -> str:
    """Readable timestamp with a 128-bit random suffix."""
    return f"{time.strftime('%Y%m%d-%H%M%S')}-{secrets.token_hex(16)}"


def get_run(tool_context: ToolContext, run_id: str) -> dict[str, Any]:
    runs = tool_context.state.get(RUNS_KEY, {})
    if run_id not in runs:
        raise ValueError("Unknown recipe run. Start image generation without a run_id.")
    return dict(runs[run_id])


def save_run(tool_context: ToolContext, run_id: str, run: dict[str, Any]) -> None:
    runs = dict(tool_context.state.get(RUNS_KEY, {}))
    runs[run_id] = run
    while len(runs) > MAX_SESSION_RUNS:
        del runs[next(iter(runs))]
    tool_context.state[RUNS_KEY] = runs
