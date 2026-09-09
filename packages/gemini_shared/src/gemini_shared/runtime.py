"""Explicit model and application construction shared by deployable entry points."""

from __future__ import annotations

import vertexai
from google.adk.agents import BaseAgent
from google.adk.models import Gemini
from vertexai.agent_engines import AdkApp

from .config.bootstrap import BootstrapSettings


def create_model(settings: BootstrapSettings) -> Gemini:
    return Gemini(
        model=settings.bootstrap_model,
        client_kwargs={"location": settings.model_location},
    )


def create_app(agent: BaseAgent, settings: BootstrapSettings) -> AdkApp:
    """Set the known project explicitly, so wrapper construction does not discover ADC."""
    vertexai.init(project=settings.project_id, location=settings.location)
    return AdkApp(agent=agent, enable_tracing=True)
