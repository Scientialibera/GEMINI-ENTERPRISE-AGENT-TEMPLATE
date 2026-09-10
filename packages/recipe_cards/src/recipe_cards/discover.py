"""Find recipe cards already published, so a dish is not rebuilt blindly.

Session state is per conversation and holds only the most recent runs, so it
cannot answer "does a chili card already exist?" in a fresh chat. The bucket
outlives every conversation, so it is the source of truth here and state is
only a cache of what this conversation has touched.
"""

from __future__ import annotations

from gemini_shared.connectors.cloud_storage import list_objects
from google.adk.tools import ToolContext

from .config import OUTPUT_BUCKET, OUTPUT_BUCKET_ENV, PROJECT_ID, USE_CASE_PREFIX, dish_prefix
from .publish import CONSOLE_URL_PREFIX
from .runs import safe_slug, save_run

# Bounded so listing stays one cheap metadata call rather than a bucket walk.
MAX_DISHES = 100
MAX_OBJECTS_PER_DISH = 400
DECK_SUFFIX = ".pptx"
IMAGES_SEGMENT = "/images/"


def _require_bucket() -> None:
    if not OUTPUT_BUCKET:
        raise RuntimeError(f"{OUTPUT_BUCKET_ENV} is not set, so there are no cards to list.")


def list_recipe_cards() -> dict[str, object]:
    """List the dishes that already have recipe cards published.

    Use this before generating a card, so an existing dish can be offered for
    reuse instead of being photographed again. Returns dish slugs only; call
    find_recipe_runs for one dish's versions.
    """
    _require_bucket()
    _, prefixes, truncated = list_objects(
        PROJECT_ID,
        OUTPUT_BUCKET,
        f"{USE_CASE_PREFIX}/",
        limit=MAX_DISHES,
        delimiter="/",
    )
    dishes = [prefix.removeprefix(f"{USE_CASE_PREFIX}/").rstrip("/") for prefix in prefixes]
    return {
        "bucket": OUTPUT_BUCKET,
        "prefix": USE_CASE_PREFIX,
        "dish_count": len(dishes),
        "dishes": dishes,
        # Say so rather than implying the list is complete.
        "truncated": truncated,
    }


def find_recipe_runs(recipe_slug: str, tool_context: ToolContext) -> dict[str, object]:
    """List the existing versions of one dish's recipe card.

    Each run is a version: its own photography and deck, kept separately, so an
    earlier card is never overwritten. Calling this makes that dish's published
    images reusable by render_recipe_card, so a new version can reuse the
    photography instead of generating it again.

    Args:
        recipe_slug: The dish identifier, for example `classic-beef-chili`.
    """
    _require_bucket()
    slug = safe_slug(recipe_slug)
    prefix = dish_prefix(slug)
    names, _, truncated = list_objects(
        PROJECT_ID, OUTPUT_BUCKET, prefix, limit=MAX_OBJECTS_PER_DISH
    )

    runs: dict[str, dict[str, object]] = {}
    for name in names:
        remainder = name.removeprefix(prefix)
        run_id, _, tail = remainder.partition("/")
        if not run_id or not tail:
            continue
        run = runs.setdefault(run_id, {"run_id": run_id, "image_count": 0, "decks": []})
        if tail.endswith(DECK_SUFFIX):
            run["decks"].append(f"{CONSOLE_URL_PREFIX}/{OUTPUT_BUCKET}/{name}")
        elif tail.startswith("images/"):
            run["image_count"] = int(run["image_count"]) + 1

    # Every image of this dish, whichever run made it, so a new version can
    # reuse earlier photography. Scoped to this dish: another dish's images and
    # unrelated objects in the same bucket stay unrenderable.
    reusable = [
        f"gs://{OUTPUT_BUCKET}/{name}"
        for name in names
        if IMAGES_SEGMENT in name.removeprefix(prefix)
    ]
    if reusable:
        # Register under the dish so render_recipe_card accepts these URIs.
        # A run created here has no generated images of its own yet.
        save_run(
            tool_context,
            slug,
            {"slug": slug, "images": {}, "reusable_uris": reusable},
        )

    ordered = sorted(runs.values(), key=lambda run: str(run["run_id"]), reverse=True)
    return {
        "bucket": OUTPUT_BUCKET,
        "slug": slug,
        "run_count": len(ordered),
        # Newest first: run IDs begin with a timestamp.
        "runs": ordered,
        "reusable_image_count": len(reusable),
        # Pass this as run_id to render_recipe_card to build a new version
        # reusing the photography above.
        "reuse_run_id": slug if reusable else "",
        "truncated": truncated,
    }
