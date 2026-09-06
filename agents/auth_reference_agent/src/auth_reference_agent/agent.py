"""Reference agent for the two supported authentication patterns.

Agent Identity reads Cloud Storage with the runtime's own identity. Delegated
auth queries BigQuery with the signed-in user's forwarded token. Both tools are
written here, against the Google Cloud APIs directly; reaching the same data
through a remote MCP server instead is what bigquery_mcp_agent demonstrates.
"""

from __future__ import annotations

from gemini_shared import apply_runtime_model, runtime_instruction
from google.adk.agents import Agent
from google.adk.models import Gemini
from vertexai.agent_engines import AdkApp

from .config import BOOTSTRAP
from .tools import (
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
        "Reference agent demonstrating Agent Identity for agent-scoped access and "
        "Gemini Enterprise delegated auth for access as the signed-in user."
    ),
    instruction=runtime_instruction,
    before_model_callback=apply_runtime_model,
    tools=[
        report_runtime_config,
        list_storage_objects,
        bigquery_query_tool,
    ],
)

# Agent Runtime serves the AdkApp wrapper, not a bare Agent.
app = AdkApp(agent=root_agent, enable_tracing=True)
