"""Construct a basic ADK assistant with live runtime settings."""

from __future__ import annotations

from gemini_shared import apply_runtime_model, runtime_instruction
from google.adk.agents import Agent
from google.adk.models import Gemini
from vertexai.agent_engines import AdkApp

from .config import BOOTSTRAP
from .tools import report_runtime_config

root_agent = Agent(
    name="basic_assistant",
    model=Gemini(
        model=BOOTSTRAP.bootstrap_model,
        client_kwargs={"location": BOOTSTRAP.model_location},
    ),
    description="Minimal ADK agent using shared runtime configuration.",
    instruction=runtime_instruction,
    before_model_callback=apply_runtime_model,
    tools=[report_runtime_config],
)

# Expose the app to Agent Runtime.
app = AdkApp(agent=root_agent, enable_tracing=True)
