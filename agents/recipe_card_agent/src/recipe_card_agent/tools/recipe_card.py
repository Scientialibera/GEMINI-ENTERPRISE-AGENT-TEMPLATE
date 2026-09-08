"""Render the finished recipe card deck and publish it to Cloud Storage."""

from __future__ import annotations

from gemini_shared.connectors.cloud_storage import ensure_bucket, upload_bytes

from ..config import OUTPUT_BUCKET, OUTPUT_BUCKET_ENV, OUTPUT_BUCKET_LOCATION, PROJECT_ID
from .card_template import load_recipes, render_deck
from .recipe_images import new_run_id, safe_slug

PPTX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
# Authenticated browser download; the viewer still needs read access.
CONSOLE_URL_PREFIX = "https://storage.cloud.google.com"


def render_recipe_card(recipe_json: str, run_id: str = "") -> dict[str, object]:
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
    run = safe_slug(run_id, "") or new_run_id()

    created = ensure_bucket(PROJECT_ID, OUTPUT_BUCKET, OUTPUT_BUCKET_LOCATION)
    deck = render_deck(data, PROJECT_ID)
    object_name = f"{slug}/{run}/{slug}-recipe-cards.pptx"
    uri = upload_bytes(PROJECT_ID, OUTPUT_BUCKET, object_name, deck, PPTX_CONTENT_TYPE)
    return {
        "bucket": OUTPUT_BUCKET,
        "bucket_created": created,
        "run_id": run,
        "recipe_count": len(recipes),
        "size_bytes": len(deck),
        "deck_uri": uri,
        # A gs:// URI cannot be opened in a browser. This one can, by anyone the
        # bucket's IAM already allows, so it is the link a person is given.
        "deck_url": f"{CONSOLE_URL_PREFIX}/{OUTPUT_BUCKET}/{object_name}",
    }
