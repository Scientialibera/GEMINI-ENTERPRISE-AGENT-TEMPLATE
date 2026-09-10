"""Construct an agent with agent-scoped Storage and user-delegated BigQuery tools."""

from __future__ import annotations

from gemini_shared import apply_runtime_model, runtime_instruction
from gemini_shared.runtime import create_app, create_model
from google.adk.agents import Agent

from .config import BOOTSTRAP
from .tools import bigquery_query_tool, list_storage_objects

root_agent = Agent(
    name="auth_reference_agent",
    model=create_model(BOOTSTRAP),
    description=("Read Cloud Storage as the agent and query BigQuery as the signed-in user."),
    instruction=runtime_instruction,
    before_model_callback=apply_runtime_model,
    tools=[
        list_storage_objects,
        bigquery_query_tool,
    ],
)

# Expose the app to Agent Runtime.
app = create_app(root_agent, BOOTSTRAP)
