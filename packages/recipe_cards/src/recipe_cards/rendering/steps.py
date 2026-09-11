"""Recipe steps layout helpers."""

from __future__ import annotations

import math
from typing import Any

from ..errors import ContentTooLong
from .content import cooking_tip_for_page, split_instructions
from .drawing import (
    add_box,
    add_checkbox,
    add_image,
    add_ink_image,
    add_rule,
    add_text,
    add_vrule,
    clean,
    limit_text,
    wrapped_line_count,
)
from .footer import add_footer
from .theme import (
    BANNER_FONT_SIZE,
    BANNER_TEXT_W,
    BANNER_TEXT_X,
    BULLET_FONT_SIZE,
    BULLET_LINE_HEIGHT,
    BULLET_ROW_PADDING,
    CHAR_WIDTH_RATIO,
    HEAD_FONT,
    LINE_HEIGHT_RATIO,
    POINTS_PER_INCH,
    STEP_BLOCK_COLUMN_SHARE,
    STEP_BLOCK_GAP,
    STEP_BLOCK_MAX_SCALE,
    STEP_BLOCK_MIN_HEIGHT,
    STEP_IMAGE_MIN_ASPECT,
    STEP_IMAGE_WIDTH_FRACTION,
    STEP_TITLE_BOX_HEIGHT,
    STEP_TITLE_FONT_SIZE,
    STEPS_LAST_PAGE_BOTTOM,
    STEPS_PAGE_BOTTOM,
    TIP_CHARS_PER_LINE,
    TIP_LINE_HEIGHT,
    TIP_VERTICAL_PADDING,
    VARIATIONS_GAP,
    VARIATIONS_MAX_TOP,
    VARIATIONS_MIN_TOP,
    VARIATIONS_MIN_TOP_SHORT_PAGE,
    VARIATIONS_PANEL_H,
    VARIATIONS_PANEL_OFFSET,
    VARIATIONS_SKETCH_X,
    VARIATIONS_TAB_H,
    VARIATIONS_TAB_W,
    VARIATIONS_TO_BANNER,
    WORDS_PER_BULLET_LINE,
    C,
)


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
        wrapped_line_count(bullet, text_w, BULLET_FONT_SIZE, CHAR_WIDTH_RATIO) for bullet in bullets
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
            wrapped_line_count(b, bullet_w, font_size, CHAR_WIDTH_RATIO)
            * font_size
            * LINE_HEIGHT_RATIO
            / POINTS_PER_INCH
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
    # The heading sits above the panel as a tab rather than inside it, so the
    # panel starts lower and carries only the list.
    panel_y = y + VARIATIONS_PANEL_OFFSET
    add_box(slide, 0.34, panel_y, 9.22, VARIATIONS_PANEL_H, C["pale"], C["pale"], radius=True)
    add_text(
        slide,
        clean(recipe.get("variations_title"), "Simple Variations"),
        0.34,
        y,
        VARIATIONS_TAB_W,
        VARIATIONS_TAB_H,
        font_face=HEAD_FONT,
        font_size=22,
        color=C["dark_blue"],
        bold=True,
    )
    variations = list(recipe.get("variations") or [])[:3]
    for i, variation in enumerate(variations):
        by = panel_y + 0.30 + i * 0.29
        add_checkbox(slide, 0.60, by + 0.035, 0.12)
        add_text(
            slide, limit_text(variation, 118), 0.85, by, 6.30, 0.20, font_size=10.7, valign="top"
        )
    add_ink_image(
        slide,
        recipe.get("variations_image_path") or recipe.get("decorative_image_path"),
        VARIATIONS_SKETCH_X,
        panel_y + 0.16,
        2.00,
        1.09,
    )


def add_bottom_banner(slide, recipe, y):
    add_box(slide, 0.34, y, 9.22, 1.08, C["yellow2"], C["yellow2"], radius=True)
    add_text(
        slide,
        clean(
            recipe.get("bottom_banner_text"), f"{clean(recipe.get('title'))}\nfor a cozy evening."
        ),
        BANNER_TEXT_X,
        y + 0.17,
        BANNER_TEXT_W,
        0.84,
        font_face=HEAD_FONT,
        font_size=BANNER_FONT_SIZE,
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


def add_steps_slide(
    prs, recipe, page_index, step_start, steps_on_page, total_step_pages, *, page_offset=1
):
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
            f"Page {page_index + page_offset + 1}",
            8.95,
            12.80,
            0.65,
            0.14,
            font_size=7,
            color=C["muted"],
            align="right",
        )
    return slide
