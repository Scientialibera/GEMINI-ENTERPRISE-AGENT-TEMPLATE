"""Agent that turns a dish into a finished, illustrated recipe card deck.

Two tools do the work: one generates every photograph in a single batch and
publishes it, the other renders the fixed card template and publishes the deck.
Both write to the agent's own Cloud Storage bucket under its Agent Identity.
"""

from __future__ import annotations

from gemini_shared import apply_runtime_model, runtime_instruction
from google.adk.agents import Agent
from google.adk.models import Gemini
from vertexai.agent_engines import AdkApp

from .config import BOOTSTRAP
from .tools import generate_recipe_images, render_recipe_card, report_runtime_config

root_agent = Agent(
    name="recipe_card_agent",
    model=Gemini(
        model=BOOTSTRAP.bootstrap_model,
        client_kwargs={"location": BOOTSTRAP.model_location},
    ),
    description=(
        "Produces print-ready recipe cards for a pantry business: writes the recipe, "
        "generates consistent food photography, and publishes an editable PowerPoint "
        "deck to Cloud Storage."
    ),
    instruction=runtime_instruction,
    before_model_callback=apply_runtime_model,
    tools=[
        report_runtime_config,
        generate_recipe_images,
        render_recipe_card,
    ],
)

# Agent Runtime serves the AdkApp wrapper, not a bare Agent.
app = AdkApp(agent=root_agent, enable_tracing=True)
