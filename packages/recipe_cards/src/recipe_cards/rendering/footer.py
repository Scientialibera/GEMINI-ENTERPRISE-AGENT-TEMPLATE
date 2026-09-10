"""Recipe footer layout helpers."""

from __future__ import annotations

from .drawing import (
    add_rule,
    add_text,
    clean,
)
from .theme import (
    HEAD_FONT,
    C,
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
