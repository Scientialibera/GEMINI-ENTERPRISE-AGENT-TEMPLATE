"""Recipe overview layout helpers."""

from __future__ import annotations

from .content import title_font
from .drawing import (
    add_box,
    add_image,
    add_ink_image,
    add_rule,
    add_text,
    add_vrule,
    clean,
    limit_text,
)
from .footer import add_footer
from .icons import add_clock_icon, add_pot_icon
from .ingredients import add_ingredient_rail
from .theme import (
    CALLOUT_Y,
    CHEF_NOTE_FONT_SIZE,
    DESCRIPTION_FONT_SIZE,
    DESCRIPTION_H,
    HEAD_FONT,
    HEADER_PANEL_H,
    HEADER_POT_X,
    HEADER_POT_Y,
    HEADER_TIME_ICON_X,
    HEADER_TIME_TEXT_W,
    HEADER_TIME_TEXT_X,
    HERO_H,
    HERO_W,
    HERO_X,
    LEFT_W,
    MENU_BLURB_H,
    MENU_BLURB_W,
    MENU_LABEL_OFFSET,
    MENU_PICTURE_H,
    MENU_PICTURE_W,
    MENU_TITLE_FONT_SIZE,
    RIGHT_W,
    RIGHT_X,
    SUBTITLE_H,
    SUBTITLE_W,
    SUBTITLE_Y,
    TITLE_H,
    TITLE_W,
    TITLE_X,
    TITLE_Y,
    C,
)


def add_header_page1(slide, recipe):
    add_box(slide, 0, 0, LEFT_W, HEADER_PANEL_H, C["blue"])
    add_rule(slide, 0, 0.72, LEFT_W, C["white"], 0.8)
    # The time sits as one centred group rather than hugging the left edge.
    add_clock_icon(slide, HEADER_TIME_ICON_X, 0.36, 0.24, C["white"])
    add_text(
        slide,
        clean(recipe.get("total_time"), "45 MINUTE RECIPE").upper(),
        HEADER_TIME_TEXT_X,
        0.21,
        HEADER_TIME_TEXT_W,
        0.31,
        font_size=14,
        color=C["white"],
        bold=True,
    )
    add_pot_icon(slide, HEADER_POT_X, HEADER_POT_Y, 0.58, C["dark_blue"])
    add_text(
        slide,
        recipe.get("title", ""),
        TITLE_X,
        TITLE_Y,
        TITLE_W,
        TITLE_H,
        font_face=HEAD_FONT,
        font_size=title_font(clean(recipe.get("title"))),
        color=C["white"],
        align="center",
        margin=0.01,
    )
    add_text(
        slide,
        recipe.get("subtitle", ""),
        0.35,
        SUBTITLE_Y,
        SUBTITLE_W,
        SUBTITLE_H,
        font_size=17,
        color=C["white"],
        bold=True,
        align="center",
        margin=0.01,
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
        CALLOUT_Y,
        RIGHT_W - 0.74,
        0.31,
        font_face=HEAD_FONT,
        font_size=20,
        color=C["dark_blue"],
        bold=True,
    )
    # Two lines at a readable size rather than one cramped line.
    add_text(
        slide,
        limit_text(recipe.get("description"), 210),
        RIGHT_X + 0.36,
        8.06,
        RIGHT_W - 0.63,
        DESCRIPTION_H,
        font_size=DESCRIPTION_FONT_SIZE,
        valign="top",
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
    band_w = RIGHT_W - 0.20
    band_h = 0.84
    picture_w = MENU_PICTURE_W
    picture_x = band_x + band_w - picture_w
    add_box(slide, band_x, banner_y, band_w, band_h, C["cream"], C["cream"], radius=True)
    add_box(slide, band_x, banner_y, 0.88, band_h, C["yellow2"], C["yellow2"], radius=True)
    add_text(
        slide,
        clean(recipe.get("season")).upper() or "MENU",
        RIGHT_X + 0.08,
        banner_y + MENU_LABEL_OFFSET,
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
        RIGHT_X + 1.10,
        banner_y + 0.07,
        1.70,
        0.16,
        font_size=MENU_TITLE_FONT_SIZE,
        color=C["dark_blue"],
        bold=True,
    )
    add_text(
        slide,
        limit_text(recipe.get("seasonal_blurb") or recipe.get("description"), 120),
        RIGHT_X + 1.10,
        banner_y + 0.25,
        MENU_BLURB_W,
        MENU_BLURB_H,
        font_size=7.7,
        color=C["dark_blue"],
        valign="top",
    )
    # The photograph fills the band's full height at its right end.
    add_image(
        slide,
        recipe.get("footer_image_path") or recipe.get("hero_image_path"),
        picture_x,
        banner_y,
        picture_w,
        MENU_PICTURE_H,
        crop=True,
        placeholder="FOOD",
    )


def add_overview_slide(prs, recipe):
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    add_header_page1(slide, recipe)
    add_ingredient_rail(slide, recipe)
    add_overview_right(slide, recipe)
    add_footer(slide, recipe)
    return slide
