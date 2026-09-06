"""Minimal independently deployable ADK agent using the shared runtime contract."""

from gemini_shared import (
    apply_runtime_model,
    get_bootstrap_settings,
    get_runtime_config_status,
    runtime_instruction,
)
from google.adk.agents import Agent
from google.adk.models import Gemini
from vertexai.agent_engines import AdkApp

BOOTSTRAP = get_bootstrap_settings()


def runtime_config_tool() -> dict[str, object]:
    """Return non-sensitive metadata about the active runtime configuration.

    The docstring and type hints are the tool contract: ADK derives the
    function declaration sent to the model from them, so a tool without a
    docstring is advertised with no description.
    """
    return get_runtime_config_status()


root_agent = Agent(
    name="basic_assistant",
    model=Gemini(
        model=BOOTSTRAP.bootstrap_model,
        client_kwargs={"location": BOOTSTRAP.model_location},
    ),
    description="Minimal ADK agent using shared runtime configuration.",
    instruction=runtime_instruction,
    before_model_callback=apply_runtime_model,
    tools=[runtime_config_tool],
)

# Agent Runtime serves the AdkApp wrapper; a bare Agent exposes none of the
# declared class methods. root_agent stays exported for local `adk` runs.
app = AdkApp(agent=root_agent, enable_tracing=True)
