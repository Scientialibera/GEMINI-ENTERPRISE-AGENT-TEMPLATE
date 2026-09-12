"""Stage two: photograph the recipe written by the previous stage.

Reuses the conversational agent's image tool unchanged. The workflow differs
in when the tool is called, not in what it does, so there is one implementation
of batching, pacing and publishing rather than two that can drift apart.
"""

from __future__ import annotations

from gemini_shared import stage_instruction
from gemini_shared.runtime import create_model
from google.adk.agents import LlmAgent
from recipe_cards.discover import retrieve
from recipe_cards.images import generate_recipe_images

from ..config import BOOTSTRAP
from .validation import validate_recipe_stage

IMAGES_STATE_KEY = "images"

INSTRUCTION = """You art-direct the photography for a recipe card.

The recipe is below. Produce every image it needs, then reply with a single
JSON object mapping each image name to the relative path the tool returned, plus
the run_id. No prose, no code fence.

Recipe:
{recipe}

Normally make three image calls: ingredients, food photography, then an independent
sketch. Each call allows 24 images and each run allows 48. Split larger batches
across additional calls with the same run_id rather than omitting images.

**First the ingredients, with mode="parallel"**, one per entry in both
`ingredients` and each customization's `ingredients` (plus any legacy
`variation_ingredients`), named `ingredient-<item>`. Deduplicate identical items
and reuse their images across options. Every
ingredient prompt ends with:

> Single ingredient, isolated and centred on a pure white background, soft even
> studio lighting, sharp focus, photorealistic product photography. Plain
> unbranded packaging with no logos, no labels, no text of any kind. No hands,
> no props, no surface and no shadow of any kind.

A canned or packaged item appears in a plain unmarked container. Never name or
depict a brand.

After ingredients, call retrieve on the run folder (the path before /images/).
Compare the stored files with both ingredient lists. Generate only missing images
and check again before moving on. Use the exact returned image mapping keys.

**Second, the hero and steps together, with
mode="sequential_reference"**, passing the run_id the first call returned.
Order them `hero`, `step-1`, `step-2`, ... without a sketch. The tool
feeds each finished image into the next, so the kitchen carries through.

Open each prompt with a named camera angle, then the action, then this scene:

> Editorial food photography for a premium cooking magazine, shot on a 50mm
> lens at f/2.8 with shallow depth of field. A bright, characterful kitchen:
> honed white Carrara marble countertop with grey veining, pale oak cutting
> boards, a navy linen napkin, and unbranded stainless, copper and cream
> stoneware cookware. Soft directional window light from the left
> with gentle falloff and warm highlights. Rich saturated colour, crisp texture
> on the food, shallow shadows, styled with a few loose herbs or scattered salt
> for life. Appetising and tactile, photorealistic, no text or watermark.

The kitchen has to make sense. Show the surface the action actually happens on
and nothing that contradicts it: a pan on a hob needs the hob visible under it,
grilling needs a grill, knife work needs a board. Never place a tap or sink
beside a cooking surface, and never show a fixture with nothing it belongs to.
Anything not used in that step stays out of frame or sits softly out of focus
behind it. The room is the same room in every shot, seen from a different
angle, so the counter, cookware and light stay consistent while what is on the
counter changes with the step.

Vary the angle down the series: hero an overhead flat lay, then a 45-degree
three-quarter view, an overhead macro, a close three-quarter view. Show the
food at the stage that step describes, not the finished dish. For every image
after the first, end with: "Keep the same kitchen, cookware, surface and
lighting as the reference images, but change the camera angle and composition."

Verify the hero and every step with retrieve.

Third, call generate_recipe_images for `sketch` alone with mode="parallel",
use_reference_images=false and the same run_id. No house style plates or previous
photographs are sent. Omit kitchen, camera and reference-matching instructions.
The sketch is a line drawing rather than a photograph:

> A delicate single-colour navy blue ink line drawing of [two or three of the
> dish's signature ingredients], in the style of a vintage botanical engraving.
> Fine hatching, no shading, no colour fill. Pure solid white background,
> nothing behind the subject: no backdrop, no paper texture, no border, no
> frame, no shadow, no checkerboard and no text. The strokes sit alone on
> plain white.

Call retrieve again to confirm all ingredient, step, hero and sketch files exist.
Do not hand off an incomplete image set as finished. If a tool fails, report the
failure rather than inventing paths. A listing verifies presence, not visual style.

Reply with:

{"run_id": "...", "images": {"hero": "dish/run/images/hero.png",
"step-1": "dish/run/images/step-1.png", "ingredient-salmon":
"dish/run/images/ingredient-salmon.png", "sketch": "dish/run/images/sketch.png"}}

Include every generated image in the mapping, not just the example entries.
Never invent a path or convert one to gs://. Use only what a tool returned.
"""

image_director = LlmAgent(
    name="image_director",
    before_agent_callback=validate_recipe_stage,
    model=create_model(BOOTSTRAP),
    description="Generates and publishes every photograph a recipe card needs.",
    instruction=stage_instruction("image_director", INSTRUCTION),
    tools=[generate_recipe_images, retrieve],
    output_key=IMAGES_STATE_KEY,
)
