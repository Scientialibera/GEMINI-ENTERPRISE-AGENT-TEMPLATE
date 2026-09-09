"""Recipe content layout helpers."""

from __future__ import annotations

import re
from typing import Any

from .drawing import (
    clean,
)
from .theme import (
    TITLE_FONT_SIZE,
    TITLE_FONT_SIZE_LONG,
    TITLE_LONG_THRESHOLD,
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


def title_font(title: str) -> float:
    """Headline size, stepping down once for a long dish name."""
    return TITLE_FONT_SIZE_LONG if len(clean(title)) > TITLE_LONG_THRESHOLD else TITLE_FONT_SIZE


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
