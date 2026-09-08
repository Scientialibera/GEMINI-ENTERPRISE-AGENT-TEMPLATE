"""Render the finished recipe card deck and publish it to Cloud Storage."""

from __future__ import annotations

from gemini_shared.connectors.cloud_storage import upload_bytes
from google.adk.tools import ToolContext

from .config import OUTPUT_BUCKET, OUTPUT_BUCKET_ENV, PROJECT_ID
from .errors import ContentTooLong
from .rendering.pages import render_deck
from .runs import get_run, new_run_id, safe_slug
from .schema import load_recipes

PPTX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
# How many times the model may correct a recipe that does not fit before the
# tool stops asking. Without a bound a model that cannot shorten enough would
# retry until the request times out.
MAX_CORRECTION_ATTEMPTS = 3
_ATTEMPT_STATE_KEY = "recipe_card_render_attempts"
# Authenticated browser download; the viewer still needs read access.
CONSOLE_URL_PREFIX = "https://storage.cloud.google.com"


def render_recipe_card(
    recipe_json: str, tool_context: ToolContext, run_id: str = ""
) -> dict[str, object]:
    """Render recipe cards from structured JSON and store the PowerPoint deck.

    Call this once the images exist, with their gs:// URIs already placed in
    the JSON. The layout is fixed by a template, so supply content and image
    locations only.

    Expected shape, as `{"recipes": [ ... ]}` or a single recipe object:
      slug, title, subtitle, servings, total_time, card_title, description,
      chef_note {title, text}, tools [], pantry [],
      ingredients [{quantity, item, image_path}],
      cooking_tip, steps [{title, body, image_path}], variations [],
      allergens [], possible_cross_contact [], bottom_banner_text, brand_line,
      hero_image_path, footer_image_path, decorative_image_path,
      variations_image_path.

    Any image field may be a gs:// URI returned by generate_recipe_images. A
    missing image renders as a placeholder rather than failing the deck.

    When a step's text does not fit its panel this returns
    `{"status": "needs_correction", ...}` naming the field and the edit to make,
    rather than failing. Shorten what it names and call again.

    Args:
        recipe_json: The recipe payload as a JSON string.
        run_id: The `run_id` returned by generate_recipe_images, so the deck is
            stored beside the images it uses.
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
    # nothing to act on. Attempts are counted per session so a recipe that
    # cannot be shortened enough stops rather than looping.
    attempts = int(tool_context.state.get(_ATTEMPT_STATE_KEY, 0)) + 1
    try:
        deck = render_deck(data, PROJECT_ID, allowed_uris=set(run["images"].values()))
    except ContentTooLong as too_long:
        tool_context.state[_ATTEMPT_STATE_KEY] = attempts
        if attempts >= MAX_CORRECTION_ATTEMPTS:
            raise
        return too_long.as_tool_result(attempts, MAX_CORRECTION_ATTEMPTS)

    tool_context.state[_ATTEMPT_STATE_KEY] = 0
    # A fresh deck name also preserves previous renders of this run.
    object_name = f"{slug}/{run_id}/{new_run_id()}-recipe-cards.pptx"
    uri = upload_bytes(
        PROJECT_ID, OUTPUT_BUCKET, object_name, deck, PPTX_CONTENT_TYPE, create_only=True
    )
    return {
        "bucket": OUTPUT_BUCKET,
        "bucket_created": False,
        "run_id": run_id,
        "recipe_count": len(recipes),
        "size_bytes": len(deck),
        "deck_uri": uri,
        # A gs:// URI cannot be opened in a browser. This one can, by anyone the
        # bucket's IAM already allows, so it is the link a person is given.
        "deck_url": f"{CONSOLE_URL_PREFIX}/{OUTPUT_BUCKET}/{object_name}",
    }
