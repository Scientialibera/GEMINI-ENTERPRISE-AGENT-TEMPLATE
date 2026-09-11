"""Keying a product photograph's backdrop without eating the subject.

A line drawing is keyed by threshold: anything near white is background. A
photograph cannot be, because the subject is often white too — a salsa in a
white ramekin is mostly near-white pixels. The backdrop is therefore found by
flooding inwards from the corners, so only what touches an edge is cleared.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PIL import Image, ImageDraw
from recipe_cards.rendering import assets, drawing


def _photo(directory, name="cutout.png"):
    """A dark subject enclosing a white hollow, on a white backdrop.

    The hollow stands for the inside of a white bowl: near-white, but not
    reachable from any edge, so it must survive keying.
    """
    image = Image.new("RGB", (80, 80), (255, 255, 255))
    canvas = ImageDraw.Draw(image)
    canvas.ellipse((16, 16, 63, 63), fill=(40, 90, 40))
    canvas.ellipse((30, 30, 49, 49), fill=(252, 252, 252))
    path = directory / name
    image.save(path)
    return str(path)


@pytest.fixture
def context(tmp_path):
    """A request-scoped asset context, as the renderer builds for a deck.

    ``resolve`` returns nothing for a path the request never downloaded, so a
    keyer called on an unregistered file finds no image at all. The real flow
    registers each asset as it downloads it; these tests register theirs the
    same way rather than reaching past the guard.
    """
    with assets.asset_context({}, "test-project", str(tmp_path), "test-bucket") as current:
        yield current


def _registered(directory, current, name="cutout.png"):
    """Write a photograph and register it the way a download would."""
    path = _photo(directory, name)
    current.resolved[path] = path
    current.local_paths.add(path)
    return path


def _alpha(path):
    with Image.open(path) as image:
        return image.convert("RGBA").split()[3]


def test_backdrop_is_cleared_but_an_enclosed_white_subject_survives(tmp_path, context):
    source = _registered(tmp_path, context)

    keyed = drawing._transparent_cutout(source, str(tmp_path))

    alpha = _alpha(keyed)
    # The backdrop touches every corner, so it goes.
    assert alpha.getpixel((2, 2)) < 16
    assert alpha.getpixel((77, 77)) < 16
    # The subject stays, and so does the white hollow inside it: thresholding
    # on whiteness alone would have punched that out.
    assert alpha.getpixel((20, 40)) > 240
    assert alpha.getpixel((40, 40)) > 240


def test_keying_is_cached_per_request(tmp_path, context):
    source = _registered(tmp_path, context)

    first = drawing._transparent_cutout(source, str(tmp_path))
    second = drawing._transparent_cutout(source, str(tmp_path))

    assert first == second
    assert context.transparent[source] == first


def test_an_unreadable_photograph_is_placed_rather_than_dropped(tmp_path, context):
    broken = tmp_path / "broken.png"
    broken.write_bytes(b"not an image")
    context.resolved[str(broken)] = str(broken)
    context.local_paths.add(str(broken))

    # Keying fails, and the original path comes back so the card still shows it.
    assert drawing._transparent_cutout(str(broken), str(tmp_path)) == str(broken)


def test_a_dark_cornered_photograph_is_left_alone(tmp_path, context):
    """Only a light backdrop is flooded, so a full-bleed photo is untouched."""
    image = Image.new("RGB", (40, 40), (30, 30, 30))
    source = tmp_path / "dark.png"
    image.save(source)
    context.resolved[str(source)] = str(source)
    context.local_paths.add(str(source))

    keyed = drawing._transparent_cutout(str(source), str(tmp_path))

    assert _alpha(keyed).getpixel((2, 2)) > 240


def test_the_ingredient_rail_keys_its_cutouts(monkeypatch):
    """The rail must use the keyed path, not a plain placement."""
    from recipe_cards.rendering import ingredients

    calls = []
    monkeypatch.setattr(ingredients, "add_cutout_image", lambda *args, **kwargs: calls.append(args))
    monkeypatch.setattr(ingredients, "add_text", Mock())
    monkeypatch.setattr(ingredients, "add_rule", Mock())

    ingredients.add_ingredient_row(
        SimpleNamespace(shapes=SimpleNamespace(add_shape=Mock(), add_textbox=Mock())),
        {"quantity": "1 lb", "item": "Ground pork", "image_path": "dish/run/images/x.png"},
        0.5,
        0.6,
        field="ingredients[0]",
    )

    assert calls, "the ingredient rail no longer routes through the keyed path"


def test_placed_cutout_falls_back_when_keying_is_impossible(tmp_path, monkeypatch, context):
    """A keying failure still places the original rather than nothing."""
    source = _registered(tmp_path, context)
    monkeypatch.setattr(drawing, "_transparent_cutout", lambda *args: "")
    placed = []
    monkeypatch.setattr(drawing, "add_image", lambda *args, **kwargs: placed.append(kwargs))

    drawing.add_cutout_image(object(), source, 0, 0, 1, 1, placeholder="P")

    assert placed and placed[0]["crop"] is False
    assert placed[0]["placeholder"] == "P"


def test_a_png_written_by_keying_carries_alpha(tmp_path, context):
    source = _registered(tmp_path, context)

    keyed = drawing._transparent_cutout(source, str(tmp_path))

    with Image.open(keyed) as image:
        assert image.mode == "RGBA"
    # The file is registered so the renderer is allowed to read it.
    assert keyed in context.local_paths


def test_keyed_output_is_a_new_file_beside_the_original(tmp_path, context):
    source = _registered(tmp_path, context)

    keyed = drawing._transparent_cutout(source, str(tmp_path))

    assert keyed != source
    assert Path(keyed).stat().st_size > 0
