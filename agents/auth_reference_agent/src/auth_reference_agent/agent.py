"""Construct an agent with agent-scoped Storage and user-delegated BigQuery tools."""

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
    description=("Read Cloud Storage as the agent and query BigQuery as the signed-in user."),
    instruction=runtime_instruction,
    before_model_callback=apply_runtime_model,
    tools=[
        report_runtime_config,
        list_storage_objects,
        bigquery_query_tool,
    ],
)

# Expose the app to Agent Runtime.
app = AdkApp(agent=root_agent, enable_tracing=True)
