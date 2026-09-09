"""Drawing primitives and typography for recipe cards."""

from __future__ import annotations

import hashlib
import os
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from PIL import Image, ImageChops
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, MSO_AUTO_SIZE, PP_ALIGN
from pptx.util import Inches, Pt

from .assets import CURRENT_ASSETS
from .assets import resolve as _resolve
from .theme import (
    BODY_FONT,
    CHAR_WIDTH_RATIO,
    HEAD_CHAR_WIDTH_RATIO,
    HEAD_FONT,
    LINE_HEIGHT_RATIO,
    POINTS_PER_INCH,
    C,
)


def rgb(hex_color: str) -> RGBColor:
    h = hex_color.lstrip("#")
    return RGBColor(int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def clean(value: Any, fallback: str = "") -> str:
    if value is None:
        return fallback
    if isinstance(value, list):
        return ", ".join(str(v) for v in value if v)
    return str(value)


def limit_text(value: Any, n: int) -> str:
    """Trim to a length, breaking on a word so the tail stays readable."""
    s = clean(value)
    if len(s) <= n:
        return s
    cut = s[: max(0, n - 1)]
    # Prefer the last space, unless that throws away most of the text.
    space = cut.rfind(" ")
    if space > n * 0.6:
        cut = cut[:space]
    return cut.rstrip(" ,;:") + "…"


def servings_label(value: Any) -> str:
    """Return "4 SERVINGS" whether the value is "4" or "4 servings".

    A model writes the unit as often as it omits it, and the template supplies
    one of its own, so the word is stripped before it is added back.
    """
    text = clean(value, "4").strip()
    lowered = text.lower()
    for suffix in ("servings", "serving", "portions", "portion"):
        if lowered.endswith(suffix):
            text = text[: -len(suffix)].strip().strip("-")
            break
    return f"{text or '4'} SERVINGS"


def exists(path: Any) -> bool:
    resolved = _resolve(path)
    return bool(resolved) and os.path.exists(resolved)


def chunks(seq: list[Any], size: int) -> Iterable[list[Any]]:
    for i in range(0, len(seq), size):
        yield seq[i : i + size]


# -----------------------------------------------------------------------------
# LOW-LEVEL DRAWING HELPERS
# -----------------------------------------------------------------------------


# Autofit is a hint the renderer may honour: PowerPoint applies it, LibreOffice
# and PDF export do not. Text is therefore measured here and the size chosen
# before it is written, so a long title or a wordy step looks the same wherever
# the deck is opened.

# Mean advance width of one character as a fraction of font size, measured over
# running sentence text in each face (0.434 body, 0.394 headings) and rounded up
# slightly so an unusually wide line still fits.


def wrapped_line_count(text: str, width_in: float, font_size: float, ratio: float) -> int:
    """Lines this text needs at a size, wrapping on words like the renderer."""
    char_w = (font_size * ratio) / POINTS_PER_INCH
    if char_w <= 0:
        return 1
    per_line = max(1, int(width_in / char_w))
    lines = 0
    for paragraph in (text or " ").splitlines() or [" "]:
        words, current = paragraph.split(), 0
        if not words:
            lines += 1
            continue
        line_len = 0
        for word in words:
            need = len(word) if line_len == 0 else line_len + 1 + len(word)
            if need <= per_line:
                line_len = need
            else:
                current += 1
                line_len = len(word)
        lines += current + 1
    return max(1, lines)


def fit_to_box(
    text: Any,
    width_in: float,
    height_in: float,
    font_size: float,
    *,
    head: bool = False,
) -> str:
    """Trim text to what the box holds at a fixed size.

    Type sizes are part of the design, so they do not change from card to card.
    When a value is too long for its panel the value is shortened, which keeps
    every card's hierarchy identical and legible.
    """
    body = clean(text)
    if not body:
        return body

    ratio = HEAD_CHAR_WIDTH_RATIO if head else CHAR_WIDTH_RATIO
    max_lines = max(1, int((height_in * POINTS_PER_INCH) / (font_size * LINE_HEIGHT_RATIO)))
    if wrapped_line_count(body, width_in, font_size, ratio) <= max_lines:
        return body

    char_w = (font_size * ratio) / POINTS_PER_INCH
    per_line = max(1, int(width_in / char_w))
    # One ellipsis replaces the tail, so the sentence ends deliberately rather
    # than colliding with the edge of the panel.
    budget = max(1, per_line * max_lines - 1)
    return limit_text(body, budget)


def add_box(slide, x, y, w, h, fill, line=None, radius=False):
    shape_type = MSO_SHAPE.ROUNDED_RECTANGLE if radius else MSO_SHAPE.RECTANGLE
    shp = slide.shapes.add_shape(shape_type, Inches(x), Inches(y), Inches(w), Inches(h))
    shp.fill.solid()
    shp.fill.fore_color.rgb = rgb(fill)
    shp.line.color.rgb = rgb(line or fill)
    shp.line.width = Pt(0.9 if line else 0.1)
    # Reduce the exaggerated corner rounding of PowerPoint's rounded rectangle.
    if radius and hasattr(shp, "adjustments") and len(shp.adjustments):
        try:
            shp.adjustments[0] = 0.08
        except Exception:
            pass
    return shp


def add_rule(slide, x, y, w, color=None, width=1.0):
    line = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(x), Inches(y), Inches(w), Pt(width))
    line.fill.solid()
    line.fill.fore_color.rgb = rgb(color or C["line"])
    line.line.fill.background()
    return line


def add_vrule(slide, x, y, h, color=None, width=1.0):
    line = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(x), Inches(y), Pt(width), Inches(h))
    line.fill.solid()
    line.fill.fore_color.rgb = rgb(color or C["line"])
    line.line.fill.background()
    return line


def add_text(
    slide,
    text,
    x,
    y,
    w,
    h,
    *,
    font_size=12,
    font_face=BODY_FONT,
    color=None,
    bold=False,
    italic=False,
    align="left",
    valign="middle",
    margin=0.0,
    fit=True,
    line_spacing=None,
):
    box = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = box.text_frame
    tf.clear()
    tf.margin_left = Inches(margin)
    tf.margin_right = Inches(margin)
    tf.margin_top = Inches(margin)
    tf.margin_bottom = Inches(margin)
    tf.word_wrap = True
    tf.vertical_anchor = {
        "top": MSO_ANCHOR.TOP,
        "middle": MSO_ANCHOR.MIDDLE,
        "bottom": MSO_ANCHOR.BOTTOM,
    }.get(valign, MSO_ANCHOR.MIDDLE)
    if fit:
        tf.auto_size = MSO_AUTO_SIZE.TEXT_TO_FIT_SHAPE
        # Type sizes are fixed so every card reads the same. Text that would
        # overflow is trimmed to what the box holds at this size rather than
        # shrunk, which would make one card's body copy smaller than another's.
        text = fit_to_box(
            text,
            max(0.1, w - 2 * margin),
            max(0.1, h),
            font_size,
            head=font_face == HEAD_FONT,
        )

    p = tf.paragraphs[0]
    p.alignment = {
        "left": PP_ALIGN.LEFT,
        "center": PP_ALIGN.CENTER,
        "right": PP_ALIGN.RIGHT,
    }.get(align, PP_ALIGN.LEFT)
    if line_spacing is not None:
        p.line_spacing = line_spacing

    run = p.add_run()
    run.text = clean(text)
    f = run.font
    f.name = font_face
    f.size = Pt(font_size)
    f.bold = bold
    f.italic = italic
    f.color.rgb = rgb(color or C["ink"])
    return box


def add_checkbox(slide, x, y, size=0.12):
    shp = slide.shapes.add_shape(
        MSO_SHAPE.RECTANGLE, Inches(x), Inches(y), Inches(size), Inches(size)
    )
    shp.fill.background()
    shp.line.color.rgb = rgb(C["ink"])
    shp.line.width = Pt(0.7)
    return shp


def _image_size(path: str) -> tuple[int, int]:
    with Image.open(_resolve(path)) as im:
        return im.size


def add_picture_crop(slide, path: str, x, y, w, h):
    """Add image cropped to fill a target box without distorting aspect ratio."""
    if not exists(path):
        return None
    iw, ih = _image_size(path)
    src_aspect = iw / ih
    dst_aspect = w / h
    pic = slide.shapes.add_picture(
        _resolve(path), Inches(x), Inches(y), width=Inches(w), height=Inches(h)
    )
    if src_aspect > dst_aspect:
        # Image is wider than target: crop left/right.
        shown_ratio = dst_aspect / src_aspect
        crop = (1.0 - shown_ratio) / 2.0
        pic.crop_left = crop
        pic.crop_right = crop
    elif src_aspect < dst_aspect:
        # Image is taller than target: crop top/bottom.
        shown_ratio = src_aspect / dst_aspect
        crop = (1.0 - shown_ratio) / 2.0
        pic.crop_top = crop
        pic.crop_bottom = crop
    return pic


# A line drawing arrives as ink on a solid white field, and dropped onto the
# cream variations panel that field reads as a white patch stuck to the page.
# Keying the white out lets the ink sit directly on the panel, the way the
# reference cards set their sketches.
# Light neutrals are background, not ink. The cutoff is well below white
# because a model asked for a transparent background sometimes draws the
# checkerboard that represents one, in greys around 220.
_INK_WHITE_CUTOFF = 205
_INK_SOFT_EDGE = 45
# A pixel is only background if it is also unsaturated: this keeps pale
# ink from being erased along with the checkerboard.
_INK_MAX_SATURATION = 26


def _transparent_ink(path: str, directory: str) -> str:
    """Return a copy of a line drawing with its white background removed.

    Pixels at or above the cutoff become fully transparent and the band just
    below it fades, so the strokes keep a soft edge instead of an aliased one.
    """
    resolved = _resolve(path)
    assets = CURRENT_ASSETS.get()
    if assets is None:
        return ""
    if not resolved or not os.path.exists(resolved):
        return resolved
    if resolved in assets.transparent:
        return assets.transparent[resolved]

    try:
        with Image.open(resolved) as source:
            image = source.convert("RGBA")
        red, green, blue, original_alpha = image.split()
        low = ImageChops.darker(ImageChops.darker(red, green), blue)
        high = ImageChops.lighter(ImageChops.lighter(red, green), blue)
        neutral = ImageChops.subtract(high, low).point(
            lambda value: 255 if value <= _INK_MAX_SATURATION else 0
        )
        fade = low.point(
            lambda value: max(0, min(255, int(255 * (_INK_WHITE_CUTOFF - value) / _INK_SOFT_EDGE)))
        )
        alpha = Image.composite(fade, Image.new("L", image.size, 255), neutral)
        image.putalpha(ImageChops.multiply(alpha, original_alpha))
        target = Path(directory) / f"ink-{hashlib.sha256(resolved.encode()).hexdigest()[:12]}.png"
        image.save(target)
        assets.transparent[resolved] = str(target)
        assets.local_paths.add(str(target))
        return str(target)
    except Exception:
        # A drawing that cannot be keyed is still better placed than dropped.
        return resolved


def add_ink_image(slide, path, x, y, w, h, *, placeholder="SKETCH"):
    """Place a line drawing with its white background keyed out."""
    assets = CURRENT_ASSETS.get()
    if exists(path) and assets is not None:
        keyed = _transparent_ink(path, assets.directory)
        if keyed and os.path.exists(keyed):
            try:
                return add_picture_contain(slide, keyed, x, y, w, h)
            except Exception:
                pass
    return add_image(slide, path, x, y, w, h, crop=False, placeholder=placeholder, quiet=True)


def add_picture_contain(slide, path: str, x, y, w, h):
    """Add image fully contained in target box, preserving aspect ratio."""
    if not exists(path):
        return None
    iw, ih = _image_size(path)
    src_aspect = iw / ih
    dst_aspect = w / h
    if src_aspect >= dst_aspect:
        rw = w
        rh = w / src_aspect
        rx = x
        ry = y + (h - rh) / 2
    else:
        rh = h
        rw = h * src_aspect
        rx = x + (w - rw) / 2
        ry = y
    return slide.shapes.add_picture(
        _resolve(path), Inches(rx), Inches(ry), width=Inches(rw), height=Inches(rh)
    )


def add_image(slide, path, x, y, w, h, *, crop=True, placeholder="IMAGE", quiet=False):
    """Place an image, or a placeholder when it is missing or unreadable.

    ``quiet`` draws nothing but the label. A boxed placeholder is right for a
    large area such as a step photograph, where the gap should be obvious, but
    wrong for a small inline cutout, where the box is more distracting than the
    absence it marks.
    """
    if exists(path):
        try:
            return (
                add_picture_crop(slide, path, x, y, w, h)
                if crop
                else add_picture_contain(slide, path, x, y, w, h)
            )
        except Exception:
            pass

    if not quiet:
        add_box(slide, x, y, w, h, C["grey"], C["line"], radius=True)
    add_text(
        slide,
        placeholder,
        x + 0.05,
        y + h / 2 - 0.13,
        w - 0.10,
        0.26,
        font_size=9,
        color=C["muted"],
        bold=True,
        align="center",
    )
    return None


def add_circle_image(slide, path, cx, cy, d, fallback=""):
    circle = slide.shapes.add_shape(
        MSO_SHAPE.OVAL,
        Inches(cx - d / 2),
        Inches(cy - d / 2),
        Inches(d),
        Inches(d),
    )
    circle.fill.solid()
    circle.fill.fore_color.rgb = rgb(C["white"] if exists(path) else C["cream"])
    circle.line.color.rgb = rgb(C["border"])
    circle.line.width = Pt(0.6)

    # python-pptx cannot directly mask an image to an ellipse. Use a cropped square
    # image placed inside the circle; with ingredient cutout PNGs this reads visually
    # as the same circular ingredient treatment while remaining editable.
    if exists(path):
        pad = 0.025
        add_image(
            slide,
            path,
            cx - d / 2 + pad,
            cy - d / 2 + pad,
            d - 2 * pad,
            d - 2 * pad,
            crop=True,
            placeholder=fallback,
        )
    else:
        add_text(
            slide,
            (fallback[:1] or "?").upper(),
            cx - d / 2,
            cy - 0.11,
            d,
            0.22,
            font_size=8.5,
            color=C["line"],
            bold=True,
            align="center",
        )
