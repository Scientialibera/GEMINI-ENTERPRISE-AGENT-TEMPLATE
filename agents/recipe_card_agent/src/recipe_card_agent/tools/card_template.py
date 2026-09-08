"""Render recipe cards as an editable PowerPoint deck.

Layout lives here and content arrives as JSON, so the agent fills in values and
image locations while this module owns presentation and pagination. Keeping the
two apart is what makes every card come out identically structured.

Page 1  : title panel, hero image, ingredient rail, overview, tools, chef note,
          allergens and footer.
Page 2+ : cooking steps in a 2x2 grid, each reserving an image area. More than
          four steps continue onto further pages, and the last one carries the
          variations, bottom banner and footer.

Image fields accept a local path or a gs:// URI. A URI is downloaded once per
render into a temporary directory, because python-pptx embeds image bytes from
a file. A missing or unreadable image degrades to a labelled placeholder rather
than failing the render.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import math
import os
import re
import tempfile
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from PIL import Image
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, MSO_AUTO_SIZE, PP_ALIGN
from pptx.util import Inches, Pt

# -----------------------------------------------------------------------------
# PAGE / THEME
# -----------------------------------------------------------------------------

PAGE_W = 10.0
PAGE_H = 13.33
LEFT_W = 3.45
GAP = 0.28
RIGHT_X = LEFT_W + GAP
RIGHT_W = PAGE_W - RIGHT_X - 0.22

# The hero photograph runs to the top and right edges of the sheet, with the
# blue panel butting against it. Insetting it leaves a white margin the
# reference cards do not have.
HERO_X = LEFT_W
HERO_W = PAGE_W - LEFT_W
HERO_H = 7.42

C = {
    "blue": "6F97C5",
    "dark_blue": "07347A",
    "yellow": "F9B800",
    "yellow2": "FFC515",
    "ink": "1D2530",
    "muted": "5C6573",
    "pale": "F5F1E6",
    "line": "0D3D85",
    "white": "FFFFFF",
    "cream": "FBF8F0",
    "grey": "E8E8E8",
    "border": "D8D8D8",
}

HEAD_FONT = "Georgia"
BODY_FONT = "Aptos"


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


GS_URI_PREFIX = "gs://"

# Populated per render by build_pptx: gs:// URI -> downloaded local file. The
# same image is referenced several times in a card, so it is fetched once.
_RESOLVED_IMAGES: dict[str, str] = {}

# Scratch directory for the current render, used for keyed line drawings.
_INK_DIRECTORY = ""


def _resolve(path: Any) -> str:
    """Return a local path for a local path or an already-downloaded URI."""
    if not isinstance(path, str) or not path:
        return ""
    if path.startswith(GS_URI_PREFIX):
        return _RESOLVED_IMAGES.get(path, "")
    return path


def prefetch_images(data: dict[str, Any], project_id: str, directory: str) -> None:
    """Download every gs:// image the deck references.

    Done once up front rather than at each draw call, because a single image
    appears in more than one place and python-pptx needs a real file.
    """
    from gemini_shared.connectors.cloud_storage import download_bytes

    global _INK_DIRECTORY
    _INK_DIRECTORY = directory
    _TRANSPARENT_CACHE.clear()
    _RESOLVED_IMAGES.clear()
    for uri in sorted(_image_uris(data)):
        target = Path(directory) / f"{hashlib.sha256(uri.encode()).hexdigest()[:16]}.png"
        try:
            target.write_bytes(download_bytes(project_id, uri))
            _RESOLVED_IMAGES[uri] = str(target)
        except Exception:
            # A missing object degrades to the placeholder rather than losing
            # the whole deck.
            continue


def _image_uris(data: dict[str, Any]) -> set[str]:
    """Collect every gs:// value under any *_image_path key."""
    found: set[str] = set()

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if (
                    key.endswith("image_path")
                    and isinstance(value, str)
                    and value.startswith(GS_URI_PREFIX)
                ):
                    found.add(value)
                else:
                    walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(data)
    return found


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
_CHAR_WIDTH_RATIO = 0.45
_HEAD_CHAR_WIDTH_RATIO = 0.41
_LINE_HEIGHT_RATIO = 1.22
_POINTS_PER_INCH = 72.0


def _wrapped_line_count(text: str, width_in: float, font_size: float, ratio: float) -> int:
    """Lines this text needs at a size, wrapping on words like the renderer."""
    char_w = (font_size * ratio) / _POINTS_PER_INCH
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

    ratio = _HEAD_CHAR_WIDTH_RATIO if head else _CHAR_WIDTH_RATIO
    max_lines = max(1, int((height_in * _POINTS_PER_INCH) / (font_size * _LINE_HEIGHT_RATIO)))
    if _wrapped_line_count(body, width_in, font_size, ratio) <= max_lines:
        return body

    char_w = (font_size * ratio) / _POINTS_PER_INCH
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
_INK_WHITE_CUTOFF = 232
_INK_SOFT_EDGE = 30
_TRANSPARENT_CACHE: dict[str, str] = {}


def _transparent_ink(path: str, directory: str) -> str:
    """Return a copy of a line drawing with its white background removed.

    Pixels at or above the cutoff become fully transparent and the band just
    below it fades, so the strokes keep a soft edge instead of an aliased one.
    """
    resolved = _resolve(path)
    if not resolved or not os.path.exists(resolved):
        return resolved
    if resolved in _TRANSPARENT_CACHE:
        return _TRANSPARENT_CACHE[resolved]

    try:
        with Image.open(resolved) as source:
            image = source.convert("RGBA")
        alpha = []
        for pixel in image.getdata():
            lightness = min(pixel[0], pixel[1], pixel[2])
            if lightness >= _INK_WHITE_CUTOFF:
                alpha.append(0)
            elif lightness >= _INK_WHITE_CUTOFF - _INK_SOFT_EDGE:
                fade = (_INK_WHITE_CUTOFF - lightness) / _INK_SOFT_EDGE
                alpha.append(int(255 * fade))
            else:
                alpha.append(255)
        image.putalpha(Image.new("L", image.size).point(lambda _: 0))
        image.putdata([(p[0], p[1], p[2], a) for p, a in zip(image.getdata(), alpha, strict=True)])
        target = Path(directory) / f"ink-{hashlib.sha256(resolved.encode()).hexdigest()[:12]}.png"
        image.save(target)
        _TRANSPARENT_CACHE[resolved] = str(target)
        return str(target)
    except Exception:
        # A drawing that cannot be keyed is still better placed than dropped.
        return resolved


def add_ink_image(slide, path, x, y, w, h, *, placeholder="SKETCH"):
    """Place a line drawing with its white background keyed out."""
    if exists(path) and _INK_DIRECTORY:
        keyed = _transparent_ink(path, _INK_DIRECTORY)
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


def split_instructions(step: dict[str, Any]) -> list[str]:
    bullets = step.get("bullets")
    if isinstance(bullets, list):
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
    add_pot_icon(slide, LEFT_W / 2, 1.22, 0.34, C["dark_blue"])
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

    ingredients = list(recipe.get("ingredients") or [])
    max_rows = min(len(ingredients), INGREDIENT_MAX_ROWS)

    # Rows keep a constant pitch and the panel is drawn to fit them, so a short
    # list gives a shorter panel rather than one with an empty lower half.
    # Only a list long enough to reach the bottom of the page compresses its
    # rows, and never below the readable minimum.
    panel_y = INGREDIENT_PANEL_TOP
    available_h = INGREDIENT_PANEL_MAX_BOTTOM - panel_y
    usable_h = available_h - 2 * INGREDIENT_PANEL_PADDING
    row_h = min(INGREDIENT_ROW_MAX_HEIGHT, usable_h / max(1, max_rows))
    row_h = max(row_h, INGREDIENT_ROW_MIN_HEIGHT)
    panel_h = min(available_h, row_h * max_rows + 2 * INGREDIENT_PANEL_PADDING)

    add_box(slide, 0.27, panel_y, LEFT_W - 0.54, panel_h, C["white"], C["border"], radius=True)
    start_y = panel_y + INGREDIENT_PANEL_PADDING

    for i in range(max_rows):
        ing = ingredients[i]
        y = start_y + i * row_h
        img = ing.get("image_path") or ing.get("imagePath")
        # The reference cards set the ingredient as a cutout on the panel with
        # no ring around it, so the photograph reads as the ingredient itself
        # rather than as an avatar of one.
        add_image(
            slide,
            img,
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
            color=C["ink"],
            align="right",
        )
        add_vrule(slide, 1.72, y + row_h * 0.22, row_h * 0.56, C["border"], 0.7)
        note = clean(ing.get("note"))
        label = clean(ing.get("item"))
        if note:
            label = f"{label}\n{note}"
        add_text(
            slide,
            label,
            1.82,
            y + row_h * 0.14,
            1.22,
            row_h * 0.72,
            font_size=INGREDIENT_FONT_SIZE,
            color=C["ink"],
            margin=0.01,
        )

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
        font_size=11.5,
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
    add_box(
        slide, RIGHT_X + 0.02, banner_y, RIGHT_W - 0.24, 0.84, C["cream"], C["cream"], radius=True
    )
    add_box(slide, RIGHT_X + 0.02, banner_y, 0.88, 0.84, C["yellow2"], C["yellow2"], radius=True)
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
        2.50,
        0.24,
        font_size=7.7,
        color=C["dark_blue"],
        valign="top",
    )
    add_image(
        slide,
        recipe.get("footer_image_path") or recipe.get("hero_image_path"),
        RIGHT_X + 3.95,
        banner_y + 0.06,
        2.20,
        0.72,
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
STEP_IMAGE_WIDTH_FRACTION = 0.46
STEP_IMAGE_MAX_WIDTH = 2.10
STEP_IMAGE_ASPECT = 1.32
STEP_TITLE_FONT_SIZE = 20.0
# Room for a two-line step name at that size.
STEP_TITLE_BOX_HEIGHT = 0.62
BULLET_FONT_SIZE = 10.0
BULLET_LINE_HEIGHT = 0.56


def add_top_tip(slide, text):
    tip = f"Cooking Tip: {limit_text(text, 200)}"
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
    img_w = min(STEP_IMAGE_MAX_WIDTH, w * STEP_IMAGE_WIDTH_FRACTION)
    img_x = x + w - img_w
    bullet_top = y + STEP_TITLE_BOX_HEIGHT + 0.06
    img_y = bullet_top + 0.06
    img_h = min(h - (img_y - y) - 0.12, img_w * STEP_IMAGE_ASPECT)
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

    # A dropped bullet is a lost cooking instruction, so every one is drawn and
    # the type shrinks to fit instead. The floor keeps a step with an unusual
    # number of instructions legible rather than merely present.
    # Body copy is one fixed size on every card. The number of bullets a panel
    # shows is what varies, and the prompt asks for a step count that fits, so
    # trimming here is a guard rather than the normal path.
    bullets = split_instructions(step)
    available_h = h - (bullet_top - y) - 0.16
    line_h = BULLET_LINE_HEIGHT
    font_size = BULLET_FONT_SIZE
    max_bullets = max(1, int(available_h / line_h))
    if len(bullets) > max_bullets:
        # Merge the overflow into the last visible bullet instead of dropping
        # instructions, which would leave the cook a step short.
        head, tail = bullets[: max_bullets - 1], bullets[max_bullets - 1 :]
        bullets = [*head, " ".join(tail)]
    by = bullet_top

    for bullet in bullets:
        add_checkbox(slide, x, by + 0.035, 0.12)
        add_text(
            slide,
            limit_text(bullet, 160),
            x + 0.26,
            by - 0.02,
            text_w - 0.30,
            line_h,
            font_size=font_size,
            valign="top",
            margin=0.01,
        )
        by += line_h

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


def add_steps_slide(prs, recipe, page_index, step_start, steps_on_page, total_step_pages):
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    rule_y = add_top_tip(
        slide,
        recipe.get("cooking_tip")
        or "Reserve a little cooking liquid before draining. It helps the sauce coat evenly.",
    )

    # The grid starts below the banner, which grows when the tip wraps.
    top = rule_y + 0.18
    row_two = top + 3.84
    blocks = [
        (0.34, top, 4.45, 3.60),
        (5.18, top, 4.38, 3.60),
        (0.34, row_two, 4.45, 3.60),
        (5.18, row_two, 4.38, 3.60),
    ]
    add_vrule(slide, 4.98, top - 0.10, 7.65, C["line"], 0.75)

    for i, step in enumerate(steps_on_page):
        add_step_block(slide, step, step_start + i, *blocks[i])

    is_last = page_index == total_step_pages - 1
    if is_last:
        add_variations_panel(slide, recipe, 9.02)
        add_bottom_banner(slide, recipe, 10.86)
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


def render_deck(data: dict[str, Any], project_id: str) -> bytes:
    """Return the finished deck as bytes, fetching any gs:// images first.

    Bytes rather than a path, because the caller uploads the result to Cloud
    Storage and never needs the file to outlive the call.
    """
    with tempfile.TemporaryDirectory(prefix="recipe-card-") as work_dir:
        prefetch_images(data, project_id, work_dir)
        output = Path(work_dir) / "recipe_cards.pptx"
        build_pptx(data, str(output))
        return output.read_bytes()


def load_recipes(payload: str | dict[str, Any]) -> dict[str, Any]:
    """Accept the recipe payload as a JSON string or an already-parsed object.

    A model emits JSON as text, so accepting both keeps the tool from failing
    on a well-formed request that arrives in the other shape.
    """
    data = json.loads(payload) if isinstance(payload, str) else payload
    if not isinstance(data, dict):
        raise ValueError("Recipe payload must be an object.")
    # A single recipe passed on its own is still a valid request.
    if "recipes" not in data:
        data = {"recipes": [data]}
    return data
