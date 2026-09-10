"""Construct an agent using the managed Cloud Monitoring MCP server."""

from __future__ import annotations

from gemini_shared import apply_runtime_model, runtime_instruction
from gemini_shared.runtime import create_app, create_model
from google.adk.agents import Agent

from .config import BOOTSTRAP
from .tools import monitoring_mcp_toolset, report_runtime_config

root_agent = Agent(
    name="monitoring_mcp_agent",
    model=create_model(BOOTSTRAP),
    description=(
        "Answers Cloud Monitoring questions about metrics, alerts and dashboards using "
        "read-only tools served by Google's managed remote MCP server, called with the "
        "signed-in user's own credentials."
    ),
    instruction=runtime_instruction,
    before_model_callback=apply_runtime_model,
    tools=[
        report_runtime_config,
        monitoring_mcp_toolset,
    ],
)

# Expose the app to Agent Runtime.
app = create_app(root_agent, BOOTSTRAP)
