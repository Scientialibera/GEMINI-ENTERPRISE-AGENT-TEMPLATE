"""Recipe page layouts and deck assembly."""

from __future__ import annotations

import contextlib
import math
import re
import tempfile
from pathlib import Path
from typing import Any

from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE
from pptx.util import Inches, Pt

from ..errors import ContentTooLong
from ..schema import load_recipes
from .assets import asset_context
from .drawing import (
    _CHAR_WIDTH_RATIO,
    _LINE_HEIGHT_RATIO,
    _POINTS_PER_INCH,
    HEAD_FONT,
    HERO_H,
    HERO_W,
    HERO_X,
    LEFT_W,
    PAGE_H,
    PAGE_W,
    RIGHT_W,
    RIGHT_X,
    C,
    _wrapped_line_count,
    add_box,
    add_checkbox,
    add_image,
    add_ink_image,
    add_rule,
    add_text,
    add_vrule,
    chunks,
    clean,
    limit_text,
    rgb,
    servings_label,
)


def split_instructions(step: dict[str, Any]) -> list[str]:
    bullets = step.get("bullets")
    if bullets:
        return [clean(v).strip() for v in bullets if clean(v).strip()]

    body = clean(step.get("body") or step.get("instructions"))
    if not body:
        return []
    if "\n" in body:
        return [re.sub(r"^[-•□\s]+", "", s).strip() for s in body.splitlines() if s.strip()]

    body = re.sub(r";\s+", ". ", body)
    parts = re.split(r"\.\s+", body)
    out = []
    for p in parts:
        p = p.strip()
        if not p:
            continue
        if not re.search(r"[.!?]$", p):
            p += "."
        out.append(p)
    return out


# The dish name is display type, so it gets two deliberate sizes rather than a
# sliding scale: the headline size, and one step down for a name too long to
# set at it. Body copy elsewhere never changes size.
TITLE_FONT_SIZE = 36.0
TITLE_FONT_SIZE_LONG = 28.0
TITLE_LONG_THRESHOLD = 28


def title_font(title: str) -> float:
    """Headline size, stepping down once for a long dish name."""
    return TITLE_FONT_SIZE_LONG if len(clean(title)) > TITLE_LONG_THRESHOLD else TITLE_FONT_SIZE


# -----------------------------------------------------------------------------
# PAGE 1
# -----------------------------------------------------------------------------


def add_clock_icon(slide, cx, cy, d, color):
    """Small outlined clock, drawn rather than set as a glyph.

    A font symbol is only as reliable as the fonts on the machine that opens
    the deck, and the ones for these icons render as a hollow box or a solid
    block when they are missing. Shapes look the same everywhere.
    """
    ring = slide.shapes.add_shape(
        MSO_SHAPE.OVAL, Inches(cx - d / 2), Inches(cy - d / 2), Inches(d), Inches(d)
    )
    ring.fill.background()
    ring.line.color.rgb = rgb(color)
    ring.line.width = Pt(1.4)
    ring.shadow.inherit = False

    # Hands at roughly ten past ten, as on the example cards.
    for dx, dy in ((0.0, -d * 0.27), (d * 0.20, 0.0)):
        hand = slide.shapes.add_shape(
            MSO_SHAPE.RECTANGLE,
            Inches(cx - (0.006 if dx == 0 else 0)),
            Inches(cy - (d * 0.27 if dy else 0.006)),
            Inches(0.012 if dx == 0 else dx),
            Inches(abs(dy) if dy else 0.012),
        )
        hand.fill.solid()
        hand.fill.fore_color.rgb = rgb(color)
        hand.line.fill.background()
        hand.shadow.inherit = False


def add_pot_icon(slide, cx, cy, w, color):
    """Small lidded cooking pot, matching the mark on the reference cards."""
    body_w, body_h = w, w * 0.52
    body_y = cy - body_h / 2 + w * 0.06
    body = slide.shapes.add_shape(
        MSO_SHAPE.ROUNDED_RECTANGLE,
        Inches(cx - body_w / 2),
        Inches(body_y),
        Inches(body_w),
        Inches(body_h),
    )
    body.fill.solid()
    body.fill.fore_color.rgb = rgb(color)
    body.line.fill.background()
    body.shadow.inherit = False
    if hasattr(body, "adjustments") and len(body.adjustments):
        with contextlib.suppress(Exception):
            body.adjustments[0] = 0.18

    lid_w, lid_h = w * 1.16, w * 0.13
    lid = slide.shapes.add_shape(
        MSO_SHAPE.ROUNDED_RECTANGLE,
        Inches(cx - lid_w / 2),
        Inches(body_y - lid_h - w * 0.04),
        Inches(lid_w),
        Inches(lid_h),
    )
    lid.fill.solid()
    lid.fill.fore_color.rgb = rgb(color)
    lid.line.fill.background()
    lid.shadow.inherit = False

    knob_d = w * 0.16
    knob = slide.shapes.add_shape(
        MSO_SHAPE.OVAL,
        Inches(cx - knob_d / 2),
        Inches(body_y - lid_h - w * 0.04 - knob_d * 0.8),
        Inches(knob_d),
        Inches(knob_d),
    )
    knob.fill.solid()
    knob.fill.fore_color.rgb = rgb(color)
    knob.line.fill.background()
    knob.shadow.inherit = False


def add_header_page1(slide, recipe):
    add_box(slide, 0, 0, LEFT_W, 4.30, C["blue"])
    add_rule(slide, 0, 0.72, LEFT_W, C["white"], 0.8)
    add_clock_icon(slide, 0.52, 0.36, 0.24, C["white"])
    add_text(
        slide,
        clean(recipe.get("total_time"), "45 MINUTE RECIPE").upper(),
        0.72,
        0.21,
        2.3,
        0.28,
        font_size=14,
        color=C["white"],
        bold=True,
    )
    add_pot_icon(slide, LEFT_W / 2, 1.16, 0.58, C["dark_blue"])
    add_text(
        slide,
        recipe.get("title", ""),
        0.37,
        1.42,
        LEFT_W - 0.74,
        1.32,
        font_face=HEAD_FONT,
        font_size=title_font(clean(recipe.get("title"))),
        color=C["white"],
        align="center",
        margin=0.01,
    )
    add_text(
        slide,
        recipe.get("subtitle", ""),
        0.36,
        2.80,
        LEFT_W - 0.72,
        0.62,
        font_size=17,
        color=C["white"],
        bold=True,
        align="center",
        margin=0.01,
    )


def add_ingredient_row(slide, ing, y: float, row_h: float, *, muted: bool = False) -> None:
    """Draw one ingredient: cutout, quantity, rule, label.

    ``muted`` sets the row in the secondary colour, which is how an ingredient
    that belongs to a variation is distinguished from one the recipe requires.
    """
    colour = C["muted"] if muted else C["ink"]
    # The reference cards set the ingredient as a cutout on the panel with no
    # ring around it, so the photograph reads as the ingredient itself rather
    # than as an avatar of one.
    add_image(
        slide,
        ing.get("image_path") or ing.get("imagePath"),
        0.40,
        y + row_h * 0.10,
        0.62,
        row_h * 0.80,
        crop=False,
        placeholder=clean(ing.get("item"), "?")[:1].upper(),
        quiet=True,
    )
    add_text(
        slide,
        ing.get("quantity", ""),
        1.06,
        y + row_h * 0.20,
        0.56,
        row_h * 0.60,
        font_size=INGREDIENT_FONT_SIZE,
        color=colour,
        align="right",
    )
    add_vrule(slide, 1.72, y + row_h * 0.22, row_h * 0.56, C["border"], 0.7)
    note = clean(ing.get("note"))
    label = clean(ing.get("item"))
    if note:
        label = label + "\n" + note
    add_text(
        slide,
        label,
        1.82,
        y + row_h * 0.14,
        1.22,
        row_h * 0.72,
        font_size=INGREDIENT_FONT_SIZE,
        color=colour,
        margin=0.01,
    )


def add_ingredient_rail(slide, recipe):
    y0 = 3.86
    add_box(slide, 0.68, y0, 2.10, 0.38, C["yellow"], C["yellow"], radius=True)
    add_text(
        slide,
        servings_label(recipe.get("servings")),
        0.78,
        y0 + 0.04,
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
        add_ingredient_row(slide, ingredients[i], start_y + i * row_h, row_h)

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
            add_ingredient_row(slide, extras[i], heading_y + (i + 1) * row_h, row_h, muted=True)

    if len(ingredients) > max_rows:
        add_text(
            slide,
            f"+ {len(ingredients) - max_rows} more",
            0.50,
            panel_y + panel_h - 0.26,
            2.30,
            0.18,
            font_size=8.5,
            color=C["muted"],
            align="center",
        )


def add_overview_right(slide, recipe):
    add_image(
        slide,
        recipe.get("hero_image_path") or recipe.get("heroImagePath"),
        HERO_X,
        0.0,
        HERO_W,
        HERO_H,
        crop=True,
        placeholder="HERO IMAGE",
    )

    add_box(
        slide, RIGHT_X + 0.15, 7.48, RIGHT_W - 0.26, 1.02, C["yellow2"], C["yellow2"], radius=True
    )
    callout = (
        recipe.get("callout_title")
        or recipe.get("card_title")
        or f"A Classic {clean(recipe.get('region'))} Comfort Dish"
    )
    add_text(
        slide,
        callout,
        RIGHT_X + 0.36,
        7.70,
        RIGHT_W - 0.74,
        0.31,
        font_face=HEAD_FONT,
        font_size=20,
        color=C["dark_blue"],
        bold=True,
    )
    add_text(
        slide,
        limit_text(recipe.get("description"), 210),
        RIGHT_X + 0.36,
        8.08,
        RIGHT_W - 0.74,
        0.22,
        font_size=11.5,
    )

    add_text(
        slide,
        "Getting Started",
        RIGHT_X + 0.02,
        8.78,
        2.68,
        0.34,
        font_face=HEAD_FONT,
        font_size=22,
        color=C["dark_blue"],
        bold=True,
    )
    add_text(
        slide,
        "COOKING TOOLS",
        RIGHT_X + 0.04,
        9.24,
        2.30,
        0.16,
        font_size=8.5,
        color=C["dark_blue"],
        bold=True,
    )
    add_text(
        slide,
        "\n".join(recipe.get("tools") or []),
        RIGHT_X + 0.04,
        9.45,
        2.45,
        0.76,
        font_size=10.2,
        valign="top",
    )
    add_text(
        slide,
        "FROM YOUR PANTRY",
        RIGHT_X + 0.04,
        10.35,
        2.30,
        0.16,
        font_size=8.5,
        color=C["dark_blue"],
        bold=True,
    )
    add_text(
        slide,
        "\n".join(recipe.get("pantry") or []),
        RIGHT_X + 0.04,
        10.56,
        2.45,
        0.88,
        font_size=10.2,
        valign="top",
    )

    add_vrule(slide, RIGHT_X + 2.84, 8.75, 3.25, C["line"], 1.1)
    chef = recipe.get("chef_note") or {}
    add_text(
        slide,
        "Chef's Note",
        RIGHT_X + 3.12,
        8.78,
        2.80,
        0.34,
        font_face=HEAD_FONT,
        font_size=22,
        color=C["dark_blue"],
        bold=True,
    )
    add_text(
        slide,
        clean(chef.get("title"), "FEATURED INGREDIENT").upper(),
        RIGHT_X + 3.12,
        9.24,
        2.80,
        0.16,
        font_size=8.4,
        color=C["dark_blue"],
        bold=True,
    )
    add_text(
        slide,
        limit_text(chef.get("text"), 260),
        RIGHT_X + 3.12,
        9.48,
        2.55,
        1.55,
        font_size=CHEF_NOTE_FONT_SIZE,
        valign="top",
        margin=0.01,
    )
    add_ink_image(
        slide,
        recipe.get("decorative_image_path") or recipe.get("decorativeImagePath"),
        RIGHT_X + 4.42,
        10.38,
        1.80,
        1.28,
    )

    banner_y = 11.62
    # Derived from the band rather than repeated as literals, so the picture
    # cannot drift outside it: it used to overhang the right edge by a third of
    # an inch because the two were positioned independently.
    band_x = RIGHT_X + 0.02
    band_w = RIGHT_W - 0.24
    band_h = 0.84
    band_pad = 0.05
    picture_w = 2.20
    picture_x = band_x + band_w - band_pad - picture_w
    add_box(slide, band_x, banner_y, band_w, band_h, C["cream"], C["cream"], radius=True)
    add_box(slide, band_x, banner_y, 0.88, band_h, C["yellow2"], C["yellow2"], radius=True)
    add_text(
        slide,
        clean(recipe.get("season")).upper() or "MENU",
        RIGHT_X + 0.08,
        banner_y + 0.31,
        0.75,
        0.18,
        font_size=8,
        color=C["dark_blue"],
        bold=True,
        align="center",
    )
    add_text(
        slide,
        "Seasonal Menu",
        RIGHT_X + 1.15,
        banner_y + 0.22,
        1.70,
        0.16,
        font_size=8.7,
        color=C["dark_blue"],
        bold=True,
    )
    add_text(
        slide,
        limit_text(recipe.get("seasonal_blurb") or recipe.get("description"), 120),
        RIGHT_X + 1.15,
        banner_y + 0.44,
        picture_x - (RIGHT_X + 1.15) - 0.12,
        0.24,
        font_size=7.7,
        color=C["dark_blue"],
        valign="top",
    )
    add_image(
        slide,
        recipe.get("footer_image_path") or recipe.get("hero_image_path"),
        picture_x,
        banner_y + band_pad,
        picture_w,
        band_h - 2 * band_pad,
        crop=True,
        placeholder="FOOD",
    )


def add_footer(slide, recipe):
    add_rule(slide, 0.30, 12.74, 9.38, C["line"], 0.75)
    add_text(
        slide,
        clean(recipe.get("region"))
        + (f"  |  {clean(recipe.get('season'))}" if recipe.get("season") else ""),
        0.30,
        12.58,
        2.70,
        0.12,
        font_size=6.2,
        color=C["muted"],
    )
    allergens = ", ".join(recipe.get("allergens") or []) or "See ingredient packaging"
    cross = recipe.get("possible_cross_contact") or []
    cross_text = f"\nPossible cross-contact: {', '.join(cross)}" if cross else ""
    add_text(
        slide,
        f"Food safety: cook ingredients thoroughly and refrigerate leftovers promptly.\nALLERGENS: {allergens}.{cross_text}",
        0.52,
        12.92,
        5.90,
        0.30,
        font_size=6.8,
        color=C["ink"],
        valign="top",
    )
    add_text(
        slide,
        clean(recipe.get("brand_line"), "Good Food\nBrings People Together"),
        7.35,
        12.84,
        1.85,
        0.42,
        font_face=HEAD_FONT,
        font_size=11,
        color=C["line"],
        italic=True,
        align="center",
    )


def add_overview_slide(prs, recipe):
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    add_header_page1(slide, recipe)
    add_ingredient_rail(slide, recipe)
    add_overview_right(slide, recipe)
    add_footer(slide, recipe)
    return slide


# -----------------------------------------------------------------------------
# COOKING STEP PAGES
# -----------------------------------------------------------------------------


# A tip long enough to wrap needs a taller banner, or the second line is
# clipped by the box drawn behind it.
TIP_CHARS_PER_LINE = 92
TIP_LINE_HEIGHT = 0.26
TIP_VERTICAL_PADDING = 0.30

# Floor for a step bullet line, below which the text stops being readable.
# Body copy is a fixed size across every card, so the design stays consistent.
INGREDIENT_FONT_SIZE = 10.0
INGREDIENT_ROW_MAX_HEIGHT = 0.72
# Below this a cutout and its label stop being readable, so a very long list
# overflows into the "+ N more" line rather than shrinking further.
INGREDIENT_ROW_MIN_HEIGHT = 0.46
INGREDIENT_PANEL_PADDING = 0.22
INGREDIENT_MAX_ROWS = 12
# The panel starts below the servings chip and may run down to just above the
# footer rule.
INGREDIENT_PANEL_TOP = 4.45
INGREDIENT_PANEL_MAX_BOTTOM = 12.42
# The step photograph is portrait and fills the column beside the text, as on
# the reference cards, rather than sitting in a fixed square.
# The photograph is a share of its block rather than a fixed size, so it grows
# with the block on a page that has room to spare.
STEP_IMAGE_WIDTH_FRACTION = 0.46
# Shortest portrait proportion a step photograph is allowed to be. This sets the
# floor on a block whose text alone would not justify one.
STEP_IMAGE_MIN_ASPECT = 1.05
# Steps are measured, not given a share of a fixed grid, so a short step does
# not reserve the same block as a long one.
CHEF_NOTE_FONT_SIZE = 11.5
# The variations panel and bottom banner follow the steps, within these bounds.
VARIATIONS_GAP = 0.30
VARIATIONS_MIN_TOP = 8.30
VARIATIONS_MAX_TOP = 10.30
VARIATIONS_MIN_TOP_SHORT_PAGE = 6.40
VARIATIONS_TO_BANNER = 1.84
STEP_BLOCK_GAP = 0.24
STEP_BLOCK_MIN_HEIGHT = 2.60
# How far a block may be stretched to use a page that few steps would leave
# empty. Beyond this the photograph starts to dominate its own instructions.
STEP_BLOCK_MAX_SCALE = 1.85
# Most of a column one step may claim when another must fit beneath it.
STEP_BLOCK_COLUMN_SHARE = 0.58
# Where the step columns must stop: higher on the last page, which also carries
# the variations panel and the bottom banner.
STEPS_PAGE_BOTTOM = 12.60
STEPS_LAST_PAGE_BOTTOM = 8.90
STEP_TITLE_FONT_SIZE = 20.0
# Room for a two-line step name at that size.
STEP_TITLE_BOX_HEIGHT = 0.62
BULLET_FONT_SIZE = 10.0
BULLET_LINE_HEIGHT = 0.56
# Roughly how many words fit on one bullet line at the body size, used to turn
# an overflow measured in inches into an edit the model can make.
WORDS_PER_BULLET_LINE = 6
# Breathing room under a bullet, so consecutive rows do not touch.
BULLET_ROW_PADDING = 0.10


def add_top_tip(slide, text):
    """Draw the tip banner, or nothing when this page has no tip.

    A page without a tip returns the line the steps would start under anyway,
    so a missing tip closes the gap rather than leaving an empty yellow bar.
    """
    body = clean(text).strip()
    if not body:
        rule_y = 0.30 + TIP_VERTICAL_PADDING
        add_rule(slide, 0.34, rule_y, 4.55, C["line"], 0.8)
        add_rule(slide, 5.12, rule_y, 4.44, C["line"], 0.8)
        return rule_y

    tip = f"Cooking Tip: {limit_text(body, 200)}"
    lines = max(1, math.ceil(len(tip) / TIP_CHARS_PER_LINE))
    box_h = lines * TIP_LINE_HEIGHT + TIP_VERTICAL_PADDING

    add_box(slide, 0.34, 0.30, 9.22, box_h, C["yellow2"], C["yellow2"], radius=True)
    add_text(
        slide,
        tip,
        0.53,
        0.30,
        8.85,
        box_h,
        font_face=HEAD_FONT,
        font_size=15.5,
        color=C["dark_blue"],
        bold=True,
        valign="middle",
    )

    rule_y = 0.30 + box_h + 0.10
    add_rule(slide, 0.34, rule_y, 4.55, C["line"], 0.8)
    add_rule(slide, 5.12, rule_y, 4.44, C["line"], 0.8)
    return rule_y


def step_block_height(step: dict[str, Any], width: float) -> float:
    """Height this step needs: its title, its bullets and its photograph.

    Steps differ in length, so each block is measured rather than given a
    share of a fixed grid. The photograph sets a floor, because a block
    shorter than its own image would crop it.
    """
    bullets = split_instructions(step)
    image_w = width * STEP_IMAGE_WIDTH_FRACTION
    text_w = width - image_w - 0.16 - 0.30

    lines = sum(
        _wrapped_line_count(bullet, text_w, BULLET_FONT_SIZE, _CHAR_WIDTH_RATIO)
        for bullet in bullets
    )
    # The text sets the height. The photograph then fills whatever the text
    # asked for, rather than imposing a floor of its own: letting the image
    # dictate the minimum made every block the same height whatever its
    # content, which is the fixed grid this replaced.
    text_h = max(len(bullets), lines) * BULLET_LINE_HEIGHT * 0.62 + len(bullets) * 0.12

    # The photograph keeps a portrait proportion of its own. A step with one or
    # two instructions would otherwise get a block barely taller than its text,
    # and a noticeably smaller picture than the steps beside it, which reads as
    # a mistake rather than as a short step.
    image_h = image_w * STEP_IMAGE_MIN_ASPECT
    content_h = STEP_TITLE_BOX_HEIGHT + 0.12 + max(text_h, image_h)
    return max(STEP_BLOCK_MIN_HEIGHT, content_h + 0.22)


def add_step_block(slide, step, idx, x, y, w, h):
    title = f"{idx + 1}. {clean(step.get('title'), 'Step')}"
    # Two lines, so a longer step name sets at the same size as a short one.
    add_text(
        slide,
        title,
        x,
        y,
        w,
        STEP_TITLE_BOX_HEIGHT,
        font_face=HEAD_FONT,
        font_size=STEP_TITLE_FONT_SIZE,
        color=C["dark_blue"],
        bold=True,
        valign="top",
    )

    # Always reserve a standardized image area for every step, even when an image
    # has not yet been generated. This is deliberate: the image agent can fill the
    # placeholder later without changing layout geometry.
    # The reference cards set the step photograph in portrait, filling the
    # column beside the text rather than sitting in a fixed square. Deriving
    # the height from the width keeps that proportion whatever the panel size.
    img_w = w * STEP_IMAGE_WIDTH_FRACTION
    img_x = x + w - img_w
    bullet_top = y + STEP_TITLE_BOX_HEIGHT + 0.06
    img_y = bullet_top + 0.06
    # The photograph fills the block beside the text, so a taller step gets a
    # taller image and the two always end together.
    img_h = h - (img_y - y) - 0.12
    text_w = w - img_w - 0.16
    add_image(
        slide,
        step.get("image_path") or step.get("imagePath"),
        img_x,
        img_y,
        img_w,
        img_h,
        crop=True,
        placeholder="STEP IMAGE",
    )

    # Reject overflow rather than dropping or shortening cooking instructions.
    bullets = split_instructions(step)
    available_h = h - (bullet_top - y) - 0.16
    line_h = BULLET_LINE_HEIGHT
    font_size = BULLET_FONT_SIZE
    # Each bullet is given the height its own wrapped text needs, so a long
    # instruction is not clipped to the two lines a uniform row would allow.
    bullet_w = text_w - 0.30
    heights = [
        max(
            line_h,
            _wrapped_line_count(b, bullet_w, font_size, _CHAR_WIDTH_RATIO)
            * font_size
            * _LINE_HEIGHT_RATIO
            / _POINTS_PER_INCH
            + BULLET_ROW_PADDING,
        )
        for b in bullets
    ]

    if sum(heights) > available_h:
        # The model can fix this, so say which step and by how much rather than
        # failing with a generic message it cannot act on.
        overflow = sum(heights) - available_h
        words_over = max(1, round(overflow / BULLET_LINE_HEIGHT * WORDS_PER_BULLET_LINE))
        raise ContentTooLong(
            field=f"steps[{idx}].body",
            detail=(
                f"Step {idx + 1} needs {sum(heights):.2f}in of text area but has "
                f"{available_h:.2f}in."
            ),
            suggestion=(
                f"Remove about {words_over} words from step {idx + 1}, or split it into two steps."
            ),
        )

    by = bullet_top
    for bullet, height in zip(bullets, heights, strict=False):
        add_checkbox(slide, x, by + 0.035, 0.12)
        add_text(
            slide,
            bullet,
            x + 0.26,
            by - 0.02,
            bullet_w,
            height,
            font_size=font_size,
            valign="top",
            margin=0.01,
            fit=False,
        )
        by += height

    add_rule(slide, x, y + h - 0.05, w, C["line"], 0.55)


def add_variations_panel(slide, recipe, y):
    add_box(slide, 0.34, y, 9.22, 1.50, C["pale"], C["pale"], radius=True)
    add_text(
        slide,
        clean(recipe.get("variations_title"), "Simple Variations"),
        0.58,
        y + 0.15,
        4.0,
        0.32,
        font_face=HEAD_FONT,
        font_size=22,
        color=C["dark_blue"],
        bold=True,
    )
    variations = list(recipe.get("variations") or [])[:3]
    for i, variation in enumerate(variations):
        by = y + 0.63 + i * 0.29
        add_checkbox(slide, 0.63, by + 0.035, 0.12)
        add_text(
            slide, limit_text(variation, 118), 0.88, by, 6.30, 0.20, font_size=10.7, valign="top"
        )
    add_ink_image(
        slide,
        recipe.get("variations_image_path") or recipe.get("decorative_image_path"),
        7.52,
        y + 0.08,
        2.00,
        1.34,
    )


def add_bottom_banner(slide, recipe, y):
    add_box(slide, 0.34, y, 9.22, 1.08, C["yellow2"], C["yellow2"], radius=True)
    add_text(
        slide,
        clean(
            recipe.get("bottom_banner_text"), f"{clean(recipe.get('title'))}\nfor a cozy evening."
        ),
        0.60,
        y + 0.14,
        3.35,
        0.82,
        font_face=HEAD_FONT,
        font_size=22,
        color=C["dark_blue"],
        bold=True,
        valign="top",
    )
    add_image(
        slide,
        recipe.get("footer_image_path") or recipe.get("hero_image_path"),
        4.02,
        y,
        5.54,
        1.08,
        crop=True,
        placeholder="FOOD BANNER",
    )


def cooking_tip_for_page(recipe: dict[str, Any], page_index: int) -> str:
    """The tip banner for one step page.

    Steps paginate in fours, so a long recipe has more than one step page and
    repeating a single tip across them reads as a fault. ``cooking_tip`` may
    therefore be a list, one entry per page, each about the steps that page
    shows. A plain string still works and is used on the first page only,
    because a tip about boiling pasta is noise above the steps for the sauce.
    """
    tips = recipe.get("cooking_tip")
    if isinstance(tips, list):
        entries = [clean(tip) for tip in tips if clean(tip)]
        return entries[page_index] if page_index < len(entries) else ""
    return clean(tips) if page_index == 0 else ""


def add_steps_slide(prs, recipe, page_index, step_start, steps_on_page, total_step_pages):
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    rule_y = add_top_tip(slide, cooking_tip_for_page(recipe, page_index))

    # The grid starts below the banner, which grows when the tip wraps.
    top = rule_y + 0.18
    is_last = page_index == total_step_pages - 1
    bottom = STEPS_LAST_PAGE_BOTTOM if is_last else STEPS_PAGE_BOTTOM

    # Two independent columns rather than a fixed grid. Each step is given the
    # height its own text and photograph need, so a three-bullet step does not
    # reserve the same block as a six-bullet one and leave a gap under it. This
    # is what the reference cards do: the second step in a column starts where
    # the first one ended, not at a shared row line.
    # One step alone on a page uses the full width rather than leaving an empty
    # second column beside it, which reads as a rendering fault.
    columns = ((0.34, 9.22),) if len(steps_on_page) == 1 else ((0.34, 4.45), (5.18, 4.38))

    # Blocks are measured from their own text, then scaled together to use the
    # page. A page carrying fewer steps than a full one therefore gives each of
    # them more room, and the photograph grows with its block, rather than the
    # page ending early with a band of white under the last step. Four steps
    # already fill the page, so they scale by one and match the other pages.
    natural = [
        step_block_height(step, columns[index % len(columns)][1])
        for index, step in enumerate(steps_on_page)
    ]

    # No single step may take so much of its column that the one under it is
    # squeezed against the bottom of the page. Two steps share a column, so a
    # block is capped at a little over half the height available and the long
    # step gives up the excess rather than its neighbour's photograph.
    room = bottom - top
    if len(columns) > 1 and len(steps_on_page) > len(columns):
        cap = (room - STEP_BLOCK_GAP) * STEP_BLOCK_COLUMN_SHARE
        natural = [min(height, cap) for height in natural]
    per_column: list[float] = [0.0] * len(columns)
    for index, height in enumerate(natural):
        per_column[index % len(columns)] += height + STEP_BLOCK_GAP
    tallest = max(per_column) - STEP_BLOCK_GAP if per_column else 0.0
    scale = min(STEP_BLOCK_MAX_SCALE, room / tallest) if tallest > 0 else 1.0
    scale = max(1.0, scale)

    placed: list[tuple[float, float, float, float]] = []
    column_y = [top] * len(columns)
    last_in_column: dict[int, int] = {}
    for index in range(len(steps_on_page)):
        # Strict reading order: a card is followed left to right, top to bottom,
        # so a step never appears before the one numbered above it. The height
        # cap above is what keeps a long step from squeezing its neighbour.
        column = index % len(columns)
        x, width = columns[column]
        # Never run past the space this page has for steps.
        height = min(natural[index] * scale, bottom - column_y[column])
        placed.append((x, column_y[column], width, height))
        column_y[column] += height + STEP_BLOCK_GAP
        last_in_column[column] = index

    # A column of short steps still ends level with the longest column, and the
    # room left over goes to its final block. Otherwise a step with one
    # instruction keeps a small photograph beside a column of tall ones, which
    # reads as a mistake rather than as a short step.
    tallest_column_end = max(column_y)
    for column, index in last_in_column.items():
        spare = tallest_column_end - column_y[column]
        if spare <= 0:
            continue
        x, y, width, height = placed[index]
        placed[index] = (x, y, width, height + spare)
        column_y[column] += spare

    if len(columns) > 1:
        add_vrule(
            slide, 4.98, top - 0.10, max(column_y) - top - STEP_BLOCK_GAP + 0.10, C["line"], 0.75
        )

    for i, step in enumerate(steps_on_page):
        add_step_block(slide, step, step_start + i, *placed[i])

    if is_last:
        # The closing panels follow the steps rather than sitting at a fixed
        # line, so short steps do not leave a band of empty page above the
        # variations. They are held within the space the footer leaves.
        steps_end = max(column_y) - STEP_BLOCK_GAP
        # A trailing page with one or two steps ends high, so the panels are
        # allowed to rise with it rather than leaving a band of empty page.
        floor = VARIATIONS_MIN_TOP_SHORT_PAGE if len(steps_on_page) <= 2 else VARIATIONS_MIN_TOP
        variations_y = min(VARIATIONS_MAX_TOP, max(floor, steps_end + VARIATIONS_GAP))
        add_variations_panel(slide, recipe, variations_y)
        add_bottom_banner(slide, recipe, variations_y + VARIATIONS_TO_BANNER)
        add_footer(slide, recipe)
    else:
        add_text(
            slide,
            f"{clean(recipe.get('title'))} — continued",
            0.35,
            12.80,
            3.80,
            0.14,
            font_size=7,
            color=C["muted"],
        )
        add_text(
            slide,
            f"Page {page_index + 2}",
            8.95,
            12.80,
            0.65,
            0.14,
            font_size=7,
            color=C["muted"],
            align="right",
        )
    return slide


# -----------------------------------------------------------------------------
# GENERATION
# -----------------------------------------------------------------------------


def add_recipe(prs, recipe):
    add_overview_slide(prs, recipe)
    steps = list(recipe.get("steps") or [])
    step_pages = list(chunks(steps, 4)) or [[]]
    for page_index, group in enumerate(step_pages):
        add_steps_slide(prs, recipe, page_index, page_index * 4, group, len(step_pages))


def build_pptx(data: dict[str, Any], output: str) -> None:
    """Write the deck for every recipe in ``data`` to ``output``."""
    prs = Presentation()
    prs.slide_width = Inches(PAGE_W)
    prs.slide_height = Inches(PAGE_H)

    # Remove the default first slide if present (normally Presentation() has none).
    while len(prs.slides) > 0:
        r_id = prs.slides._sldIdLst[0].rId
        prs.part.drop_rel(r_id)
        del prs.slides._sldIdLst[0]

    recipes = data.get("recipes") or []
    if not recipes:
        raise ValueError("Input contains no recipes.")

    for recipe in recipes:
        add_recipe(prs, recipe)

    Path(output).parent.mkdir(parents=True, exist_ok=True)
    prs.save(output)


def render_deck(
    data: dict[str, Any], project_id: str, *, allowed_uris: set[str] | None = None
) -> bytes:
    """Render validated content using only the run's authorized images."""
    data = load_recipes(data)
    with (
        tempfile.TemporaryDirectory(prefix="recipe-card-") as work_dir,
        asset_context(data, project_id, work_dir, allowed_uris or set()),
    ):
        output = Path(work_dir) / "recipe_cards.pptx"
        build_pptx(data, str(output))
        return output.read_bytes()
