"""Server-controlled request and transport attempt limits, and tool-call logging."""

import logging
from typing import Any

from google.adk.agents.callback_context import CallbackContext
from google.adk.agents.invocation_context import InvocationContext
from google.adk.agents.run_config import RunConfig
from google.adk.apps.app import EventsCompactionConfig
from google.adk.apps.llm_event_summarizer import LlmEventSummarizer
from google.adk.models import Gemini
from google.adk.models.llm_request import LlmRequest
from google.adk.plugins.base_plugin import BasePlugin
from google.adk.tools.base_tool import BaseTool
from google.adk.tools.tool_context import ToolContext
from google.genai import types

from ..config.bootstrap import get_bootstrap_settings
from ..config.runtime_config import (
    TOOL_LOGGING_ARGUMENT_KEYS,
    TOOL_LOGGING_FULL,
    TOOL_LOGGING_OFF,
    get_runtime_config,
)

LOGGER = logging.getLogger(__name__)


def _tool_logging() -> str:
    """Read the level per call, so a published parameter takes effect live."""
    # Deliberately broad: an unreadable parameter must not fail a tool call
    # that would otherwise have succeeded.
    try:
        return get_runtime_config().tool_call_logging
    except Exception:
        return TOOL_LOGGING_OFF


def _argument_detail(level: str, tool_args: dict[str, Any]) -> str:
    """Describe arguments at the configured level, never above it.

    Only ``full`` records values. Tool arguments are whatever the signed-in
    user's request produced — SQL, monitoring filters, storage paths — so the
    lower levels name the parameters without disclosing what was asked for.
    """
    if not tool_args:
        return ""
    if level == TOOL_LOGGING_ARGUMENT_KEYS:
        return f" args={sorted(tool_args)}"
    if level == TOOL_LOGGING_FULL:
        return f" args={tool_args!r}"
    return ""


class RuntimeLimitsPlugin(BasePlugin):
    def __init__(self) -> None:
        super().__init__(name="runtime_limits")

    async def before_tool_callback(
        self, *, tool: BaseTool, tool_args: dict[str, Any], tool_context: ToolContext
    ) -> None:
        """Record which tool ran. ADK itself logs nothing that names one."""
        del tool_context
        level = _tool_logging()
        if level != TOOL_LOGGING_OFF:
            LOGGER.info("tool_call %s%s", tool.name, _argument_detail(level, tool_args))

    async def after_tool_callback(
        self,
        *,
        tool: BaseTool,
        tool_args: dict[str, Any],
        tool_context: ToolContext,
        result: dict[str, Any],
    ) -> None:
        del tool_context, tool_args
        level = _tool_logging()
        if level == TOOL_LOGGING_OFF:
            return
        # Results carry user data for the same reason arguments do.
        detail = f" result={result!r}" if level == TOOL_LOGGING_FULL else ""
        LOGGER.info("tool_done %s%s", tool.name, detail)

    async def on_tool_error_callback(
        self,
        *,
        tool: BaseTool,
        tool_args: dict[str, Any],
        tool_context: ToolContext,
        error: Exception,
    ) -> None:
        del tool_context
        level = _tool_logging()
        if level == TOOL_LOGGING_OFF:
            return
        # The type alone below "full": an exception message can quote the input.
        detail = f": {error}" if level == TOOL_LOGGING_FULL else ""
        LOGGER.warning(
            "tool_error %s %s%s%s",
            tool.name,
            type(error).__name__,
            detail,
            _argument_detail(level, tool_args),
        )

    async def before_run_callback(self, *, invocation_context: InvocationContext) -> None:
        """Use ADK's invocation-wide counter, shared by all workflow stages."""
        settings = get_runtime_config()
        limit = settings.max_model_calls_per_request
        requested = invocation_context.run_config or RunConfig()
        if requested.max_llm_calls > 0:
            limit = min(limit, requested.max_llm_calls)
        invocation_context.run_config = requested.model_copy(update={"max_llm_calls": limit})
        # Keep configuration request-local; ADK initializes the summarizer lazily.
        invocation_context.events_compaction_config = EventsCompactionConfig(
            token_threshold=settings.context_compaction_threshold_tokens,
            event_retention_size=6,
            summarizer=LlmEventSummarizer(
                llm=Gemini(
                    model=settings.model,
                    client_kwargs={"location": get_bootstrap_settings().model_location},
                )
            ),
        )

    async def before_model_callback(
        self, *, callback_context: CallbackContext, llm_request: LlmRequest
    ) -> None:
        """Limit transport retries independently from the agent's model-call count."""
        del callback_context
        settings = get_runtime_config()
        llm_request.model = settings.model
        options = llm_request.config.http_options or types.HttpOptions()
        llm_request.config.http_options = options.model_copy(
            update={"retry_options": types.HttpRetryOptions(attempts=settings.max_attempts)}
        )
