"""Agent whose data tools come from a remote MCP server rather than this repository.

Google hosts the BigQuery MCP server, so nothing is deployed to get its tools.
Each call carries the signed-in user's delegated token, which is what decides
what the tools may read.
"""

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

# Agent Runtime serves the AdkApp wrapper, not a bare Agent.
app = AdkApp(agent=root_agent, enable_tracing=True)
