"""Construct an agent using the managed BigQuery MCP server."""

from __future__ import annotations

from gemini_shared import apply_runtime_model, runtime_instruction
from gemini_shared.runtime import create_app, create_model
from google.adk.agents import Agent

from .config import BOOTSTRAP
from .tools import bigquery_mcp_toolset

root_agent = Agent(
    name="bigquery_mcp_agent",
    model=create_model(BOOTSTRAP),
    description=(
        "Answers BigQuery questions using read-only tools served by Google's managed "
        "remote MCP server, called with the signed-in user's own credentials."
    ),
    instruction=runtime_instruction,
    before_model_callback=apply_runtime_model,
    tools=[bigquery_mcp_toolset],
)

# Expose the app to Agent Runtime.
app = create_app(root_agent, BOOTSTRAP)
