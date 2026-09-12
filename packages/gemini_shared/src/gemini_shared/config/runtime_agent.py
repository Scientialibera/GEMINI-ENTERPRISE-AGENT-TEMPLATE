"""Resolve instructions and model names from cached runtime settings."""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import Any

from google.adk.agents.callback_context import CallbackContext
from google.adk.agents.readonly_context import ReadonlyContext
from google.adk.models.llm_request import LlmRequest
from google.adk.utils.instructions_utils import inject_session_state

from .runtime_config import get_runtime_config


def runtime_instruction(readonly_context: ReadonlyContext) -> str:
    """Return the instruction from the current runtime configuration."""
    del readonly_context
    return get_runtime_config().instruction


def stage_instruction(
    stage: str, fallback: str
) -> Callable[[ReadonlyContext], Coroutine[Any, Any, str]]:
    """Resolve one workflow stage's instruction, published or compiled in.

    A workflow has no single instruction: ``SequentialAgent`` takes none and
    each stage carries its own, so they are published as a mapping keyed by
    stage name. An absent or blank entry falls back to the text in the module,
    which is what makes publishing nothing safe and a bad edit recoverable by
    deleting the key rather than redeploying.

    ADK reports a callable instruction as bypassing state injection, so the
    ``{recipe}`` and ``{images}`` placeholders a stage reads from session state
    are substituted here. Returning the string alone would hand the model the
    literal braces and silently break the hand-off between stages.
    """

    async def resolve(readonly_context: ReadonlyContext) -> str:
        # Deliberately broad: an unreadable parameter must not stop a stage
        # that the compiled-in instruction can still run.
        try:
            published = get_runtime_config().stage_instructions.get(stage, "")
        except Exception:
            published = ""
        return await inject_session_state(published.strip() or fallback, readonly_context)

    return resolve


def apply_runtime_model(
    callback_context: CallbackContext,
    llm_request: LlmRequest,
) -> None:
    """Set the model on each request from the current runtime configuration."""
    del callback_context
    llm_request.model = get_runtime_config().model
