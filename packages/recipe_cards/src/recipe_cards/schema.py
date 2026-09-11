"""Bounded recipe input shared by tools and workflow stages."""

from __future__ import annotations

import json
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

MAX_PAYLOAD_BYTES = 128 * 1024
MAX_IMAGES_PER_BATCH = 24
MAX_IMAGES_PER_RUN = 48
Text = Annotated[str, StringConstraints(max_length=1200)]
ShortText = Annotated[str, StringConstraints(max_length=160)]
# Relative to the use-case root, exactly as a listing tool returned it. A
# bucket, a URL or a traversal segment is rejected before anything is fetched.
_SEGMENT = r"[A-Za-z0-9][A-Za-z0-9._-]*"
RELATIVE_ASSET_PATH = rf"^({_SEGMENT}(/{_SEGMENT})*)?$"
ImagePath = Annotated[str, StringConstraints(max_length=1024, pattern=RELATIVE_ASSET_PATH)]


class InputModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, populate_by_name=True)


class Ingredient(InputModel):
    quantity: ShortText = ""
    item: ShortText
    note: ShortText = ""
    image_path: ImagePath = Field(default="", alias="imagePath")


class Step(InputModel):
    title: ShortText
    body: Text = ""
    instructions: Text = ""
    bullets: list[ShortText] = Field(default_factory=list, max_length=12)
    image_path: ImagePath = Field(default="", alias="imagePath")

    @model_validator(mode="after")
    def require_instructions(self) -> Step:
        if not (self.body.strip() or self.instructions.strip() or self.bullets):
            raise ValueError("Each step needs instructions.")
        return self


class ChefNote(InputModel):
    title: ShortText = ""
    text: Text = ""


class CustomizedStep(InputModel):
    step: int = Field(ge=1, le=24)
    instructions: list[ShortText] = Field(min_length=1, max_length=12)


class Customization(InputModel):
    name: Annotated[str, StringConstraints(min_length=1, max_length=40)]
    replaces: list[ShortText] = Field(default_factory=list, max_length=24)
    ingredients: list[Ingredient] = Field(default_factory=list, max_length=12)
    steps: list[CustomizedStep] = Field(min_length=1, max_length=24)


class Recipe(InputModel):
    title: Annotated[str, StringConstraints(min_length=1, max_length=100)]
    slug: ShortText = ""
    subtitle: ShortText = ""
    servings: ShortText = ""
    total_time: ShortText = ""
    region: ShortText = ""
    season: ShortText = ""
    card_title: ShortText = ""
    callout_title: ShortText = ""
    description: Text = ""
    seasonal_blurb: Text = ""
    chef_note: ChefNote = Field(default_factory=ChefNote)
    tools: list[ShortText] = Field(default_factory=list, max_length=20)
    pantry: list[ShortText] = Field(default_factory=list, max_length=20)
    ingredients: list[Ingredient] = Field(min_length=1, max_length=24)
    variation_ingredients: list[Ingredient] = Field(default_factory=list, max_length=12)
    steps: list[Step] = Field(min_length=1, max_length=24)
    cooking_tip: Text | Annotated[list[ShortText], Field(max_length=6)] = ""
    variations: list[ShortText] = Field(default_factory=list, max_length=6)
    customizations: list[Customization] = Field(default_factory=list, max_length=6)
    variations_title: ShortText = ""
    allergens: list[ShortText] = Field(default_factory=list, max_length=20)
    possible_cross_contact: list[ShortText] = Field(default_factory=list, max_length=20)
    bottom_banner_text: ShortText = ""
    brand_line: ShortText = ""
    hero_image_path: ImagePath = Field(default="", alias="heroImagePath")
    decorative_image_path: ImagePath = Field(default="", alias="decorativeImagePath")
    variations_image_path: ImagePath = ""
    footer_image_path: ImagePath = ""

    @model_validator(mode="after")
    def check_customization_references(self) -> Recipe:
        items = {ingredient.item.casefold() for ingredient in self.ingredients}
        for option in self.customizations:
            if any(item.casefold() not in items for item in option.replaces):
                raise ValueError("Customization replacements must name core ingredients.")
            if any(change.step > len(self.steps) for change in option.steps):
                raise ValueError("Customized steps must reference an existing recipe step.")
        return self


class RecipeDeck(InputModel):
    recipes: list[Recipe] = Field(min_length=1, max_length=3)


def load_recipes(payload: str | dict[str, Any]) -> dict[str, Any]:
    """Validate before downloading images or rendering pages."""
    raw = payload if isinstance(payload, str) else json.dumps(payload)
    if len(raw.encode("utf-8")) > MAX_PAYLOAD_BYTES:
        raise ValueError("Recipe payload exceeds 128 KiB.")
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("Recipe payload must be an object.")
    if "recipes" not in data:
        data = {"recipes": [data]}
    return RecipeDeck.model_validate(data).model_dump(exclude_unset=True)
