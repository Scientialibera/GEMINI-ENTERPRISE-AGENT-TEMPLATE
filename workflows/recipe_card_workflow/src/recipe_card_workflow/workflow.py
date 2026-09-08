"""A recipe card built as a fixed pipeline rather than a conversation.

The same job as ``recipe_card_agent``, expressed the other way. The agent is
handed tools and decides when to use them; this workflow fixes the order and
lets the model supply only the content of each stage:

    recipe_writer  -> state["recipe"]
    image_director -> state["images"]
    card_renderer  -> state["deck"]

``SequentialAgent`` runs the stages in order and each writes its result into
session state under an ``output_key``, which the next reads by name. The tools
are the agent's, unchanged, so both entry points produce identical cards and
there is one implementation to maintain.

The trigger is a dish name. The result is a link to the published deck.
"""

from __future__ import annotations

from google.adk.agents import SequentialAgent
from vertexai.agent_engines import AdkApp

from .stages import card_renderer, image_director, recipe_writer

root_agent = SequentialAgent(
    name="recipe_card_workflow",
    description=(
        "Turns a dish name into a published recipe card deck: writes the recipe, "
        "generates consistent unbranded photography, and renders the card. The "
        "stages always run in this order."
    ),
    sub_agents=[recipe_writer, image_director, card_renderer],
)

# Agent Runtime serves the AdkApp wrapper, not a bare agent.
app = AdkApp(agent=root_agent, enable_tracing=True)
