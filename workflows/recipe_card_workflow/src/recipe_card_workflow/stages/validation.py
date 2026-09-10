"""Reject malformed recipes before spending on image generation."""

import json

from google.adk.agents.callback_context import CallbackContext
from recipe_cards.schema import load_recipes


def validate_recipe_stage(callback_context: CallbackContext) -> None:
    # An absent recipe means the writing stage produced nothing, which reaches
    # load_recipes as "" and surfaces as a JSONDecodeError naming this file
    # rather than the stage that actually failed. Say what went wrong instead.
    recipe = str(callback_context.state.get("recipe", "")).strip()
    if not recipe:
        raise ValueError(
            "No recipe in session state: the recipe_writer stage produced no output, "
            "so there is nothing to photograph."
        )
    data = load_recipes(recipe)
    callback_context.state["recipe"] = json.dumps(data["recipes"][0])
