"""Construct an agent using the managed BigQuery MCP server."""

from __future__ import annotations

from gemini_shared import apply_runtime_model, runtime_instruction
from google.adk.agents import Agent
from google.adk.models import Gemini
from vertexai.agent_engines import AdkApp

from .config import BOOTSTRAP
from .tools import bigquery_mcp_toolset, report_runtime_config

root_agent = Agent(
    name="bigquery_mcp_agent",
    model=Gemini(
        model=BOOTSTRAP.bootstrap_model,
        client_kwargs={"location": BOOTSTRAP.model_location},
    ),
    description=(
        "Answers BigQuery questions using read-only tools served by Google's managed "
        "remote MCP server, called with the signed-in user's own credentials."
    ),
    instruction=runtime_instruction,
    before_model_callback=apply_runtime_model,
    tools=[
        report_runtime_config,
        bigquery_mcp_toolset,
    ],
)

# Expose the app to Agent Runtime.
app = AdkApp(agent=root_agent, enable_tracing=True)
