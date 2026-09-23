"""Construct an agent that inspects and edits other agents' runtime parameters."""

from __future__ import annotations

from gemini_shared import apply_runtime_model, runtime_instruction
from gemini_shared.runtime import create_app, create_model
from google.adk.agents import Agent

from .config import BOOTSTRAP
from .tools import (
    apply_parameter_update,
    list_runtime_parameters,
    preview_parameter_update,
    read_runtime_parameter,
)

root_agent = Agent(
    name="parameter_updater",
    model=create_model(BOOTSTRAP),
    description="Inspect and edit agents' live runtime parameters in Parameter Manager.",
    instruction=runtime_instruction,
    before_model_callback=apply_runtime_model,
    tools=[
        list_runtime_parameters,
        read_runtime_parameter,
        preview_parameter_update,
        apply_parameter_update,
    ],
)

# Expose the app to Agent Runtime.
app = create_app(root_agent, BOOTSTRAP)
