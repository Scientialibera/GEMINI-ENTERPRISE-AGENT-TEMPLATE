"""Reject malformed stage hand-offs before the next stage reads them."""

import json

from google.adk.agents.callback_context import CallbackContext
from recipe_cards.schema import load_recipes


def validate_images_stage(callback_context: CallbackContext) -> None:
    """Fail readably when the photography stage produced no image mapping.

    ``card_renderer``'s instruction interpolates ``{images}`` from session
    state, and an absent key raises a KeyError while the instruction is being
    built — before any tool runs. That surfaces as a bare FAILED_PRECONDITION
    with empty error details, which names neither the stage nor the cause.

    The mapping is what every image path on the card comes from, so an empty
    one cannot be rendered around: stopping here with the reason is better
    than publishing a deck of placeholders.
    """
    raw = str(callback_context.state.get("images", "")).strip()
    if not raw:
        raise ValueError(
            "No images in session state: the image_director stage produced no output, "
            "so there is nothing to assemble. Its photographs may still be in the run "
            "folder; retrieve that folder and reuse them rather than regenerating."
        )
    try:
        images = json.loads(raw)
    except json.JSONDecodeError as error:
        raise ValueError(
            "The image_director stage did not return a JSON object mapping image "
            f"names to paths, so the card cannot be assembled: {error}."
        ) from error
    if not isinstance(images, dict) or not images.get("images"):
        raise ValueError(
            "The image_director stage returned no image paths, so every picture on "
            "the card would be a placeholder. Retrieve the run folder and reuse the "
            "photographs it already holds."
        )


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
