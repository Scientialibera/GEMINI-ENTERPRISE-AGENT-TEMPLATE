"""Wiring that resolves an agent's instruction and model per request.

Both are read from runtime configuration rather than fixed at construction, so
a published configuration change takes effect after the cache TTL without
redeploying the agent.
"""

from __future__ import annotations

from google.adk.agents.callback_context import CallbackContext
from google.adk.agents.readonly_context import ReadonlyContext
from google.adk.models.llm_request import LlmRequest

from .runtime_config import get_runtime_config


def runtime_instruction(readonly_context: ReadonlyContext) -> str:
    """Return the instruction from the current runtime configuration."""
    del readonly_context
    return get_runtime_config().instruction


def apply_runtime_model(
    callback_context: CallbackContext,
    llm_request: LlmRequest,
) -> None:
    """Set the model on each request from the current runtime configuration."""
    del callback_context
    llm_request.model = get_runtime_config().model
