"""Stage two: photograph the recipe written by the previous stage.

Reuses the conversational agent's image tool unchanged. The workflow differs
in when the tool is called, not in what it does, so there is one implementation
of batching, pacing and publishing rather than two that can drift apart.
"""

from __future__ import annotations

from google.adk.agents import LlmAgent
from google.adk.models import Gemini
from recipe_card_agent.tools import generate_recipe_images

from ..config import BOOTSTRAP

IMAGES_STATE_KEY = "images"

INSTRUCTION = """You art-direct the photography for a recipe card.

The recipe is below. Produce every image it needs, then reply with a single
JSON object mapping each image name to the gs:// URI the tool returned, plus
the run_id. No prose, no code fence.

Recipe:
{recipe}

Call `generate_recipe_images` exactly twice.

**First the ingredients, with mode="parallel"**, one per ingredient in the
recipe, named `ingredient-<item>`. Every ingredient prompt ends with:

> Single ingredient, isolated and centred on a pure white background, soft even
> studio lighting, sharp focus, photorealistic product photography. Plain
> unbranded packaging with no logos, no labels, no text of any kind. No hands,
> no props, no surface, no shadow beyond a soft contact shadow.

A canned or packaged item appears in a plain unmarked container. Never name or
depict a brand.

**Then the hero, steps and sketch together, with
mode="sequential_reference"**, passing the run_id the first call returned.
Order them `hero`, `step-1`, `step-2`, ..., ending with `sketch`. The tool
feeds each finished image into the next, so the kitchen carries through.

Open each prompt with a named camera angle, then the action, then this scene:

> Editorial food photography for a premium cooking magazine, shot on a 50mm
> lens at f/2.8 with shallow depth of field. A bright, characterful kitchen:
> honed white Carrara marble countertop with grey veining, warm brass fixtures,
> pale oak cutting boards, a navy linen napkin, and unbranded stainless, copper
> and cream stoneware cookware. Soft directional window light from the left
> with gentle falloff and warm highlights. Rich saturated colour, crisp texture
> on the food, shallow shadows, styled with a few loose herbs or scattered salt
> for life. Appetising and tactile, photorealistic, no text or watermark.

Vary the angle down the series: hero an overhead flat lay, then a 45-degree
three-quarter view, an overhead macro, a close three-quarter view. Show the
food at the stage that step describes, not the finished dish. For every image
after the first, end with: "Keep the same kitchen, cookware, surface and
lighting as the reference images, but change the camera angle and composition."

The final image, `sketch`, is a line drawing rather than a photograph:

> A delicate single-colour navy blue ink line drawing of [two or three of the
> dish's signature ingredients], in the style of a vintage botanical engraving.
> Fine hatching, no shading, no colour fill. Pure solid white background,
> nothing behind the subject: no backdrop, no paper texture, no border, no
> frame, no shadow, no checkerboard and no text. The strokes sit alone on
> plain white.

Reply with:

{{"run_id": "...", "images": {{"hero": "gs://...", "step-1": "gs://..."}}}}

Never invent a URI. Use only what a tool returned.
"""

image_director = LlmAgent(
    name="image_director",
    model=Gemini(
        model=BOOTSTRAP.bootstrap_model,
        client_kwargs={"location": BOOTSTRAP.model_location},
    ),
    description="Generates and publishes every photograph a recipe card needs.",
    instruction=INSTRUCTION,
    tools=[generate_recipe_images],
    output_key=IMAGES_STATE_KEY,
)
