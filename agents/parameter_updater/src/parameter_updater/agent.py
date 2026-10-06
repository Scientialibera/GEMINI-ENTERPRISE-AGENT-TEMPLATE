"""Construct an agent that inspects and edits other agents' runtime parameters."""

from __future__ import annotations

from gemini_shared import apply_runtime_model, runtime_instruction
from gemini_shared.runtime import create_app
from google.adk.agents import Agent
from google.adk.tools import FunctionTool

from .config import BOOTSTRAP
from .model import RefreshingGemini
from .tools import (
    apply_parameter_update,
    list_runtime_parameters,
    preview_parameter_update,
    read_runtime_parameter,
)

root_agent = Agent(
    name="parameter_updater",
    model=RefreshingGemini(
        model=BOOTSTRAP.bootstrap_model,
        client_kwargs={"location": BOOTSTRAP.model_location},
    ),
    description="Inspect and edit agents' live runtime parameters in Parameter Manager.",
    instruction=runtime_instruction,
    before_model_callback=apply_runtime_model,
    tools=[
        list_runtime_parameters,
        read_runtime_parameter,
        preview_parameter_update,
        FunctionTool(apply_parameter_update, require_confirmation=True),
    ],
)

# Expose the app to Agent Runtime.
app = create_app(root_agent, BOOTSTRAP)
