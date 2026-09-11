"""Render the finished recipe card deck and publish it to Cloud Storage."""

from __future__ import annotations

import time

from gemini_shared.config.runtime_config import get_runtime_config
from gemini_shared.connectors.cloud_storage import upload_bytes
from google.adk.tools import ToolContext

from .config import OUTPUT_BUCKET, OUTPUT_BUCKET_ENV, PROJECT_ID, dish_prefix
from .errors import ContentTooLong
from .rendering.pages import render_deck
from .runs import get_run, new_run_id, safe_slug, save_run
from .schema import load_recipes

PPTX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
# How many times the model may correct a recipe that does not fit before the
# tool stops asking. Without a bound a model that cannot shorten enough would
# retry until the request times out.
# Authenticated browser download; the viewer still needs read access.
CONSOLE_URL_PREFIX = "https://storage.cloud.google.com"


def render_recipe_card(
    recipe_json: str, tool_context: ToolContext, run_id: str = ""
) -> dict[str, object]:
    """Render recipe cards from structured JSON and store the PowerPoint deck.

    Call this once the images exist, with their relative paths already placed
    in the JSON. The layout is fixed by a template, so supply content and image
    locations only.

    Expected shape, as `{"recipes": [ ... ]}` or a single recipe object:
      slug, title, subtitle, servings, total_time, card_title, description,
      chef_note {title, text}, tools [], pantry [],
      ingredients [{quantity, item, image_path}],
      cooking_tip, steps [{title, body, image_path}], variations [],
      allergens [], possible_cross_contact [], bottom_banner_text, brand_line,
      hero_image_path, footer_image_path, decorative_image_path,
    variations_image_path, variation_ingredients [{quantity, item, image_path}],
    customizations [{name, replaces [core item names],
      ingredients [{quantity, item, image_path}],
      steps [{step: one-based number, instructions: [checkbox text]}]}].
    Use customizations for new alternatives, including every replacement quantity
    and every affected step. Legacy variations strings remain supported.

    Every image field takes a path exactly as generate_recipe_images or
    retrieve returned it, relative to the card store. Before publishing a finished
    card, use retrieve to check every ingredient, step, hero and sketch path.
    Missing image fields produce placeholders for explicitly requested drafts;
    do not treat such a draft as a complete illustrated card.

    When a step's text does not fit its panel this returns
    `{"status": "needs_correction", ...}` naming the field and the edit to make,
    rather than failing. Shorten what it names and call again with the returned `run_id`.

    Args:
        recipe_json: The recipe payload as a JSON string.
        run_id: The `run_id` returned by generate_recipe_images, so the deck is
            stored beside the images it uses. When reusing existing photography
            or making an explicitly requested draft, omit on the first call and
            reuse the returned ID for corrections.
    """
    if not OUTPUT_BUCKET:
        raise RuntimeError(
            f"{OUTPUT_BUCKET_ENV} is not set, so there is nowhere to publish the deck."
        )

    data = load_recipes(recipe_json)
    recipes = data.get("recipes") or []
    if not recipes:
        raise ValueError("The payload contains no recipes.")

    first = recipes[0]
    slug = safe_slug(str(first.get("slug") or first.get("title") or "recipe"))
    # One prefix per card, so two people asking for the same dish at once do
    # not overwrite each other's deck.
    run = get_run(tool_context, run_id) if run_id else {"slug": slug, "images": {}}
    if run["slug"] != slug:
        raise ValueError("The run belongs to a different recipe.")
    run_id = run_id or new_run_id()

    # Text that does not fit is the model's to fix, so it is answered rather
    # than raised: a raised error reaches the model as a generic failure with
    # nothing to act on. Attempts are counted per run so a recipe that
    # cannot be shortened enough stops rather than looping.
    if run.get("render_failure"):
        return dict(run["render_failure"])
    max_attempts = get_runtime_config().max_attempts
    attempts = int(run.get("render_attempts", 0)) + 1
    save_run(tool_context, run_id, run)
    try:
        deck = render_deck(data, PROJECT_ID, bucket=OUTPUT_BUCKET)
    except ContentTooLong as too_long:
        run["render_attempts"] = attempts
        result = {**too_long.as_tool_result(attempts, max_attempts), "run_id": run_id}
        if attempts >= max_attempts:
            run["render_failure"] = result
        save_run(tool_context, run_id, run)
        return result

    run["render_attempts"] = 0
    save_run(tool_context, run_id, run)
    # A fresh timestamp also preserves previous renders of this run. Only the
    # clock part is needed: run_id already carries this run's random suffix.
    object_name = f"{dish_prefix(slug)}{run_id}/{time.strftime('%Y%m%d-%H%M%S')}-recipe-cards.pptx"
    uri = upload_bytes(
        PROJECT_ID, OUTPUT_BUCKET, object_name, deck, PPTX_CONTENT_TYPE, create_only=True
    )
    return {
        "bucket": OUTPUT_BUCKET,
        "run_id": run_id,
        "recipe_count": len(recipes),
        "size_bytes": len(deck),
        "deck_uri": uri,
        # A gs:// URI cannot be opened in a browser. This one can, by anyone the
        # bucket's IAM already allows, so it is the link a person is given.
        "deck_url": f"{CONSOLE_URL_PREFIX}/{OUTPUT_BUCKET}/{object_name}",
    }
