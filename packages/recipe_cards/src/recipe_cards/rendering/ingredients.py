"""Recipe ingredients layout helpers."""

from __future__ import annotations

from ..errors import ContentTooLong
from .drawing import (
    add_box,
    add_image,
    add_rule,
    add_text,
    add_vrule,
    chunks,
    clean,
    fit_to_box,
    servings_label,
)
from .footer import add_footer
from .theme import (
    HEAD_FONT,
    INGREDIENT_FONT_SIZE,
    INGREDIENT_MAX_ROWS,
    INGREDIENT_PANEL_MAX_BOTTOM,
    INGREDIENT_PANEL_PADDING,
    INGREDIENT_PANEL_TOP,
    INGREDIENT_ROW_MAX_HEIGHT,
    INGREDIENT_ROW_MIN_HEIGHT,
    LEFT_W,
    SERVINGS_TEXT_OFFSET,
    SERVINGS_Y,
    C,
)


def add_ingredient_row(
    slide,
    ing,
    y: float,
    row_h: float,
    *,
    muted: bool = False,
    x: float = 0.40,
    width: float = 2.64,
    field: str = "ingredients",
) -> None:
    """Draw one ingredient: cutout, quantity, rule, label.

    ``muted`` sets the row in the secondary colour, which is how an ingredient
    that belongs to a variation is distinguished from one the recipe requires.
    """
    colour = C["muted"] if muted else C["ink"]
    scale = width / 2.64
    note = clean(ing.get("note"))
    label = clean(ing.get("item")) + ("\n" + note if note else "")
    quantity = clean(ing.get("quantity"))
    for name, text, w, h in (
        ("quantity", quantity, 0.56 * scale, row_h * 0.60),
        ("item/note", label, 1.22 * scale - 0.02, row_h * 0.72 - 0.02),
    ):
        if fit_to_box(text, w, h, INGREDIENT_FONT_SIZE) != text:
            raise ContentTooLong(
                f"{field}.{name}",
                f"Ingredient {name} does not fit its row.",
                "Use a shorter ingredient description or unit abbreviation; preserve the amount.",
            )
    # The reference cards set the ingredient as a cutout on the panel with no
    # ring around it, so the photograph reads as the ingredient itself rather
    # than as an avatar of one.
    add_image(
        slide,
        ing.get("image_path") or ing.get("imagePath"),
        x,
        y + row_h * 0.10,
        0.62 * scale,
        row_h * 0.80,
        crop=False,
        placeholder=clean(ing.get("item"), "?")[:1].upper(),
        quiet=True,
    )
    add_text(
        slide,
        quantity,
        x + 0.66 * scale,
        y + row_h * 0.20,
        0.56 * scale,
        row_h * 0.60,
        font_size=INGREDIENT_FONT_SIZE,
        color=colour,
        align="right",
        fit=False,
    )
    add_vrule(slide, x + 1.32 * scale, y + row_h * 0.22, row_h * 0.56, C["border"], 0.7)
    add_text(
        slide,
        label,
        x + 1.42 * scale,
        y + row_h * 0.14,
        1.22 * scale,
        row_h * 0.72,
        font_size=INGREDIENT_FONT_SIZE,
        color=colour,
        margin=0.01,
        fit=False,
    )


def ingredient_entries(recipe):
    """Keep core and optional ingredients ordered, with their correction paths."""
    return [
        (ingredient, key == "variation_ingredients", f"{key}[{index}]")
        for key in ("ingredients", "variation_ingredients")
        for index, ingredient in enumerate(recipe.get(key) or [])
    ]


def add_ingredient_rail(slide, recipe):
    y0 = SERVINGS_Y
    add_box(slide, 0.68, y0, 2.10, 0.38, C["yellow"], C["yellow"], radius=True)
    add_text(
        slide,
        servings_label(recipe.get("servings")),
        0.78,
        y0 + SERVINGS_TEXT_OFFSET,
        1.90,
        0.26,
        font_size=15,
        bold=True,
        color=C["dark_blue"],
        align="center",
    )

    core = list(recipe.get("ingredients") or [])
    # Ingredients a variation needs are listed too, under their own heading, so
    # a cook can shop for one without reading the whole method. They are kept
    # apart from the core list because they are optional: mixed in, an optional
    # item reads as required.
    extras = list(recipe.get("variation_ingredients") or [])

    max_rows = min(len(core), INGREDIENT_MAX_ROWS)
    remaining = max(0, INGREDIENT_MAX_ROWS - max_rows)
    extra_rows = min(len(extras), remaining)
    total_rows = max_rows + extra_rows
    # The heading costs the height of one row.
    heading_rows = 1 if extra_rows else 0

    # Rows keep a constant pitch and the panel is drawn to fit them, so a short
    # list gives a shorter panel rather than one with an empty lower half.
    # Only a list long enough to reach the bottom of the page compresses its
    # rows, and never below the readable minimum.
    panel_y = INGREDIENT_PANEL_TOP
    available_h = INGREDIENT_PANEL_MAX_BOTTOM - panel_y
    usable_h = available_h - 2 * INGREDIENT_PANEL_PADDING
    row_h = min(INGREDIENT_ROW_MAX_HEIGHT, usable_h / max(1, total_rows + heading_rows))
    row_h = max(row_h, INGREDIENT_ROW_MIN_HEIGHT)
    panel_h = min(
        available_h,
        row_h * (total_rows + heading_rows) + 2 * INGREDIENT_PANEL_PADDING,
    )

    add_box(slide, 0.27, panel_y, LEFT_W - 0.54, panel_h, C["white"], C["border"], radius=True)
    ingredients = core
    start_y = panel_y + INGREDIENT_PANEL_PADDING

    for i in range(max_rows):
        add_ingredient_row(
            slide, ingredients[i], start_y + i * row_h, row_h, field=f"ingredients[{i}]"
        )

    if extra_rows:
        heading_y = start_y + max_rows * row_h
        add_rule(slide, 0.42, heading_y + row_h * 0.30, LEFT_W - 0.84, C["border"], 0.7)
        add_text(
            slide,
            "FOR THE VARIATIONS",
            0.42,
            heading_y + row_h * 0.42,
            LEFT_W - 0.84,
            row_h * 0.40,
            font_size=8.4,
            color=C["dark_blue"],
            bold=True,
        )
        for i in range(extra_rows):
            add_ingredient_row(
                slide,
                extras[i],
                heading_y + (i + 1) * row_h,
                row_h,
                muted=True,
                field=f"variation_ingredients[{i}]",
            )

    if len(core) + len(extras) > total_rows:
        add_text(
            slide,
            "Ingredients continue on the next page",
            0.35,
            INGREDIENT_PANEL_MAX_BOTTOM + 0.03,
            LEFT_W - 0.70,
            0.12,
            font_size=7,
            color=C["muted"],
            align="center",
        )


def add_ingredient_continuation_slides(prs, recipe) -> int:
    """Render every remaining ingredient in two readable columns per page."""
    remaining = ingredient_entries(recipe)[INGREDIENT_MAX_ROWS:]
    pages = list(chunks(remaining, INGREDIENT_MAX_ROWS))
    for entries in pages:
        slide = prs.slides.add_slide(prs.slide_layouts[6])
        add_text(
            slide,
            recipe.get("title", ""),
            0.4,
            0.3,
            9.2,
            0.65,
            font_face=HEAD_FONT,
            font_size=28,
            color=C["dark_blue"],
        )
        add_text(
            slide,
            "INGREDIENTS CONTINUED",
            0.4,
            1.1,
            9.2,
            0.3,
            font_size=14,
            bold=True,
            color=C["dark_blue"],
        )
        rows_per_column = INGREDIENT_MAX_ROWS // 2
        row_h = 1.60
        for index, (ingredient, optional, field) in enumerate(entries):
            column, row = divmod(index, rows_per_column)
            x, y = 0.4 + column * 4.8, 1.9 + row * row_h
            if optional:
                add_text(
                    slide,
                    "OPTIONAL VARIATION",
                    x,
                    y,
                    4.3,
                    0.18,
                    font_size=8,
                    bold=True,
                    color=C["muted"],
                )
            add_ingredient_row(
                slide,
                ingredient,
                y + 0.20,
                row_h - 0.30,
                x=x,
                width=4.3,
                muted=optional,
                field=field,
            )
            add_rule(slide, x, y + row_h - 0.06, 4.3, C["border"], 0.5)
        add_footer(slide, recipe)
    return len(pages)
