"""Reject malformed recipes before spending on image generation."""

import json

from google.adk.agents.callback_context import CallbackContext
from recipe_cards.schema import load_recipes


def validate_recipe_stage(callback_context: CallbackContext) -> None:
    data = load_recipes(callback_context.state.get("recipe", ""))
    callback_context.state["recipe"] = json.dumps(data["recipes"][0])
