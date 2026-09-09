"""Stage one: turn a dish name into the structured recipe the card needs.

No tools. The stage produces content only, so that a failure here costs
nothing but a model call and the expensive stages never run on a bad recipe.
"""

from __future__ import annotations

from gemini_shared.runtime import create_model
from google.adk.agents import LlmAgent

from ..config import BOOTSTRAP

RECIPE_STATE_KEY = "recipe"

INSTRUCTION = """You write the content of a recipe card for a pantry business.

The user names a dish. Reply with a single JSON object and nothing else: no
prose before or after it, and no code fence.

The card is a fixed layout at a fixed type size, so text that runs long is
trimmed rather than shrunk. Write to these budgets:

- title: under 30 characters, the dish name only
- subtitle: under 60 characters
- description: under 200 characters
- chef_note.text: under 220 characters
- cooking_tip: a list, one tip per step page. Steps paginate in fours, so four
  steps or fewer need one tip, five to eight need two, and so on. Each tip is
  under 150 characters and concerns the steps on its own page
- steps: four to six, each title under 30 characters, each with 2 to 5
  instructions of roughly 100 characters
- variations: three, each under 90 characters
- bottom_banner_text: exactly two short lines, under 26 characters each
- variation_ingredients: anything a variation needs that the core list does
  not already carry, same shape as ingredients; omit when there is none
- ingredients: eight to twelve, each item under 26 characters

The ingredient list and the method must agree. Every ingredient listed has to
be used in a step, and every ingredient a step calls for has to be listed with
a quantity. Never invent an ingredient the recipe does not use. Staples in
`pantry` are the exception: oil, salt and pepper belong there and steps may use
them freely.

Shape:

{
  "slug": "short-hyphenated-name",
  "title": "Dish Name",
  "subtitle": "with a short qualifier",
  "servings": "4",
  "total_time": "45 MINUTE RECIPE",
  "season": "Winter",
  "card_title": "A short headline",
  "description": "One or two sentences.",
  "seasonal_blurb": "One sentence.",
  "chef_note": {"title": "Chef's Tip", "text": "One tip."},
  "tools": ["Large Pot"],
  "pantry": ["Olive Oil", "Salt"],
  "ingredients": [{"quantity": "12 oz", "item": "Spaghetti"}],
  "cooking_tip": ["One tip per step page."],
  "steps": [{"title": "Boil the pasta", "body": "One instruction.\\nAnother."}],
  "variations": ["One variation."],
  "variation_ingredients": [{"quantity": "1/2 cup", "item": "Manchego"}],
  "allergens": ["wheat/gluten"],
  "possible_cross_contact": ["depends on the pasta"],
  "bottom_banner_text": "Two short lines.",
  "brand_line": "Good Food\\nBrings People Together"
}

Set `servings` to the number alone. Omit every image field: the next stage adds
them.
"""

recipe_writer = LlmAgent(
    name="recipe_writer",
    model=create_model(BOOTSTRAP),
    description="Writes the structured recipe content for a card.",
    instruction=INSTRUCTION,
    output_key=RECIPE_STATE_KEY,
)
