"""Recipe icons layout helpers."""

from __future__ import annotations

import contextlib

from pptx.enum.shapes import MSO_SHAPE
from pptx.util import Inches, Pt

from .drawing import (
    rgb,
)


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
