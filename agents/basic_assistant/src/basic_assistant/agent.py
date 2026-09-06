"""Minimal independently deployable ADK agent using the shared runtime contract."""

from gemini_shared import get_bootstrap_settings, get_runtime_config, get_runtime_config_status
from google.adk.agents import Agent
from google.adk.agents.callback_context import CallbackContext
from google.adk.agents.readonly_context import ReadonlyContext
from google.adk.models import Gemini
from google.adk.models.llm_request import LlmRequest
from vertexai.agent_engines import AdkApp

BOOTSTRAP = get_bootstrap_settings()


def runtime_config_tool() -> dict[str, object]:
    """Return non-sensitive metadata about the active runtime configuration.

    The docstring and type hints are the tool contract: ADK derives the
    function declaration sent to the model from them, so a tool without a
    docstring is advertised with no description.
    """
    return get_runtime_config_status()


def _runtime_instruction(readonly_context: ReadonlyContext) -> str:
    del readonly_context
    return get_runtime_config().instruction


def _apply_runtime_model(
    callback_context: CallbackContext,
    llm_request: LlmRequest,
) -> None:
    del callback_context
    llm_request.model = get_runtime_config().model


root_agent = Agent(
    name="basic_assistant",
    model=Gemini(
        model=BOOTSTRAP.bootstrap_model,
        client_kwargs={"location": BOOTSTRAP.model_location},
    ),
    description="Minimal ADK agent using shared runtime configuration.",
    instruction=_runtime_instruction,
    before_model_callback=_apply_runtime_model,
    tools=[runtime_config_tool],
)

# Agent Runtime serves the AdkApp wrapper; a bare Agent exposes none of the
# declared class methods. root_agent stays exported for local `adk` runs.
app = AdkApp(agent=root_agent, enable_tracing=True)
