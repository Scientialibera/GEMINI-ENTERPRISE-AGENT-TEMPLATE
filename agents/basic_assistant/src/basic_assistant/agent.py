"""Construct a basic ADK assistant with live runtime settings."""

from __future__ import annotations

from gemini_shared import apply_runtime_model, runtime_instruction
from gemini_shared.runtime import create_app, create_model
from google.adk.agents import Agent

from .config import BOOTSTRAP
from .tools import report_runtime_config

root_agent = Agent(
    name="basic_assistant",
    model=create_model(BOOTSTRAP),
    description="Minimal ADK agent using shared runtime configuration.",
    instruction=runtime_instruction,
    before_model_callback=apply_runtime_model,
    tools=[report_runtime_config],
)

# Expose the app to Agent Runtime.
app = create_app(root_agent, BOOTSTRAP)
