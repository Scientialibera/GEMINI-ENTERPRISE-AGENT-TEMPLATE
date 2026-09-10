"""Stage three: assemble the recipe and its images into the published deck.

Reuses the conversational agent's render tool unchanged, so both entry points
produce byte-identical cards from the same template.
"""

from __future__ import annotations

from gemini_shared.runtime import create_model
from google.adk.agents import LlmAgent
from recipe_cards.publish import render_recipe_card

from ..config import BOOTSTRAP

DECK_STATE_KEY = "deck"

INSTRUCTION = """You assemble a recipe card and publish it.

Recipe:
{recipe}

Images:
{images}

Merge the image URIs into the recipe and call `render_recipe_card` once,
passing the run_id from the images object so the deck is stored beside the
photographs it uses.

- `hero_image_path` is the hero image.
- Each step's `image_path` is its own `step-N` image, in order. Every step gets
  a different one; never point two steps at the same image.
- Each ingredient's `image_path` is its `ingredient-<item>` image, in both
  `ingredients` and `variation_ingredients`.
- `decorative_image_path` and `variations_image_path` are both `sketch`.
- `footer_image_path` may reuse the hero.

The layout is fixed by a template, so supply content and image locations only.

If `render_recipe_card` returns `status: needs_correction`, the recipe is too
long for the card rather than broken. It names the field and the edit to make:
shorten that field as described and call the tool again with the corrected
recipe and the same returned `run_id`. Preserve ingredient amounts when shortening
descriptions or abbreviating units. Extra ingredients continue on additional pages.
It says how many attempts remain; when none do, report the problem
rather than retrying.

Then reply with a single JSON object and nothing else:

{{"deck_url": "...", "deck_uri": "...", "run_id": "...", "title": "...",
  "recipe_count": 1}}

taking `deck_url`, `deck_uri` and `run_id` from what the tool returned, and
`title` from the recipe. Never invent a URI.
"""

card_renderer = LlmAgent(
    name="card_renderer",
    model=create_model(BOOTSTRAP),
    description="Renders the recipe card deck and publishes it to Cloud Storage.",
    instruction=INSTRUCTION,
    tools=[render_recipe_card],
    output_key=DECK_STATE_KEY,
)
