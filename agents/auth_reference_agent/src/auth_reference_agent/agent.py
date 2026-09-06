"""Reference agent for the supported authentication and tool patterns.

Agent Identity reads Cloud Storage with the runtime's own identity. Delegated
auth queries BigQuery with the signed-in user's forwarded token, both through a
tool written here and through Google's managed BigQuery MCP server.
"""

from __future__ import annotations

from gemini_shared import apply_runtime_model, runtime_instruction
from google.adk.agents import Agent
from google.adk.models import Gemini
from vertexai.agent_engines import AdkApp

from .config import BOOTSTRAP
from .tools import (
    bigquery_mcp_toolset,
    bigquery_query_tool,
    list_storage_objects,
    report_runtime_config,
)

root_agent = Agent(
    name="auth_reference_agent",
    model=Gemini(
        model=BOOTSTRAP.bootstrap_model,
        client_kwargs={"location": BOOTSTRAP.model_location},
    ),
    description=(
        "Reference agent demonstrating Agent Identity, Gemini Enterprise delegated auth "
        "and a remote MCP server called with the signed-in user's token."
    ),
    instruction=runtime_instruction,
    before_model_callback=apply_runtime_model,
    tools=[
        report_runtime_config,
        list_storage_objects,
        bigquery_query_tool,
        bigquery_mcp_toolset,
    ],
)

# Agent Runtime serves the AdkApp wrapper, not a bare Agent.
app = AdkApp(agent=root_agent, enable_tracing=True)
