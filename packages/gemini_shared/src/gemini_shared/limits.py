"""Server-controlled request and transport attempt limits."""

from google.adk.agents.callback_context import CallbackContext
from google.adk.agents.invocation_context import InvocationContext
from google.adk.agents.run_config import RunConfig
from google.adk.apps.app import EventsCompactionConfig
from google.adk.models.llm_request import LlmRequest
from google.adk.plugins.base_plugin import BasePlugin
from google.genai import types

from .config.runtime_config import get_runtime_config


class RuntimeLimitsPlugin(BasePlugin):
    def __init__(self) -> None:
        super().__init__(name="runtime_limits")

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
        )

    async def before_model_callback(
        self, *, callback_context: CallbackContext, llm_request: LlmRequest
    ) -> None:
        """Limit transport retries independently from the agent's model-call count."""
        del callback_context
        options = llm_request.config.http_options or types.HttpOptions()
        llm_request.config.http_options = options.model_copy(
            update={
                "retry_options": types.HttpRetryOptions(attempts=get_runtime_config().max_attempts)
            }
        )
