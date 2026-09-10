"""Recipe trust boundaries, bounded inputs and rendering isolation."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from io import BytesIO
from threading import Barrier
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PIL import Image
from pptx import Presentation
from recipe_cards.rendering import assets, pages
from recipe_cards.schema import MAX_IMAGES_PER_BATCH, load_recipes

RECIPE = {
    "title": "Soup",
    "slug": "soup",
    "ingredients": [{"quantity": "1 cup", "item": "Water"}],
    "steps": [{"title": "Heat", "body": "Boil the water."}],
}


def png():
    output = BytesIO()
    Image.new("RGB", (8, 8), "white").save(output, format="PNG")
    return output.getvalue()


@pytest.mark.parametrize(
    "payload",
    [
        {"recipes": "invalid"},
        {"recipes": []},
        {**RECIPE, "steps": ["not a step"]},
        {**RECIPE, "ingredients": []},
        {**RECIPE, "hero_image_path": "C:/private/image.png"},
        {**RECIPE, "hero_image_path": "https://example.com/image.png"},
        {**RECIPE, "steps": RECIPE["steps"] * 25},
        {**RECIPE, "unexpected": "value"},
    ],
)
def test_recipe_schema_rejects_invalid_payload(payload):
    with pytest.raises(ValueError):
        load_recipes(payload)


def test_legacy_image_aliases_are_normalized():
    result = load_recipes({**RECIPE, "heroImagePath": "gs://output/soup/hero.png"})
    assert result["recipes"][0]["hero_image_path"] == "gs://output/soup/hero.png"


def test_unregistered_image_rejected_before_download(monkeypatch, tmp_path):
    download = Mock()
    monkeypatch.setattr(assets, "download_bytes", download)
    with (
        pytest.raises(ValueError, match="not generated"),
        assets.asset_context(
            {"hero_image_path": "gs://private/secret.png"}, "test", str(tmp_path), set()
        ),
    ):
        pytest.fail("Unauthorized image accepted")
    download.assert_not_called()


def test_concurrent_asset_contexts_remain_isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(assets, "download_bytes", lambda *args, **kwargs: png())
    barrier = Barrier(2)

    def render(index):
        directory = tmp_path / str(index)
        directory.mkdir()
        uri = f"gs://output/run-{index}/hero.png"
        with assets.asset_context({"hero_image_path": uri}, "test", str(directory), {uri}):
            before = assets.resolve(uri)
            barrier.wait(timeout=10)
            assert before == assets.resolve(uri)
            assert assets.resolve(f"gs://output/run-{1 - index}/hero.png") == ""
        assert assets.CURRENT_ASSETS.get() is None

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(render, (0, 1)))


def test_failed_download_resets_asset_context(monkeypatch, tmp_path):
    monkeypatch.setattr(assets, "download_bytes", Mock(side_effect=ValueError("too large")))
    uri = "gs://output/hero.png"
    with (
        pytest.raises(ValueError, match="too large"),
        assets.asset_context({"hero_image_path": uri}, "test", str(tmp_path), {uri}),
    ):
        pytest.fail("Download unexpectedly succeeded")
    assert assets.CURRENT_ASSETS.get() is None


def test_render_keeps_complete_instruction():
    deck = Presentation(BytesIO(pages.render_deck(RECIPE, "test")))
    text = "\n".join(
        shape.text for slide in deck.slides for shape in slide.shapes if shape.has_text_frame
    )
    assert "Boil the water." in text


@pytest.mark.parametrize("core_count,extra_count", [(12, 1), (13, 0), (24, 12), (5, 12)])
def test_all_ingredients_and_quantities_are_rendered(core_count, extra_count):
    recipe = deepcopy(RECIPE)
    recipe["ingredients"] = [
        {"quantity": f"{i + 1} g", "item": f"Core {i + 1}"} for i in range(core_count)
    ]
    recipe["variation_ingredients"] = [
        {"quantity": f"{i + 25} g", "item": f"Extra {i + 1}"} for i in range(extra_count)
    ]
    deck = Presentation(BytesIO(pages.render_deck(recipe, "test")))
    texts = [shape.text for slide in deck.slides for shape in slide.shapes if shape.has_text_frame]
    for ingredient in recipe["ingredients"] + recipe["variation_ingredients"]:
        assert texts.count(ingredient["item"]) == 1
        assert texts.count(ingredient["quantity"]) == 1
    assert not any(text.startswith("+ ") and text.endswith("more") for text in texts)
    if extra_count:
        assert "OPTIONAL VARIATION" in texts


def test_overlong_ingredient_quantity_returns_a_correction():
    from recipe_cards.errors import ContentTooLong

    recipe = deepcopy(RECIPE)
    recipe["ingredients"][0]["quantity"] = "one hundred and twenty five grams of water"
    with pytest.raises(ContentTooLong, match="Ingredient quantity") as raised:
        pages.render_deck(recipe, "test")
    assert raised.value.field == "ingredients[0].quantity"


def test_overflow_raises_instead_of_truncating():
    """Cooking text is never silently shortened.

    The renderer stops and says which step overflowed and by how much, so the
    caller can shorten it. Dropping the words instead would hand someone a card
    missing part of a step, with nothing to show it had happened.
    """
    from recipe_cards.errors import ContentTooLong

    recipe = deepcopy(RECIPE)
    recipe["steps"][0]["body"] = " ".join(["Keep stirring the soup carefully."] * 30)
    with pytest.raises(ContentTooLong) as raised:
        pages.render_deck(recipe, "test")

    # The failure names the field to edit and the edit to make.
    assert raised.value.field.startswith("steps[")
    assert "words" in raised.value.suggestion


def test_image_batch_limits_before_paid_calls(monkeypatch):
    from recipe_cards import images

    monkeypatch.setattr(images, "OUTPUT_BUCKET", "output")
    generate = Mock()
    monkeypatch.setattr(images, "generate_images", generate)
    with pytest.raises(ValueError, match="At most"):
        images.generate_recipe_images(
            "soup",
            ["photo"] * (MAX_IMAGES_PER_BATCH + 1),
            [str(i) for i in range(MAX_IMAGES_PER_BATCH + 1)],
            SimpleNamespace(state={}),
        )
    generate.assert_not_called()


def test_image_names_cannot_collide_after_normalization(monkeypatch):
    from recipe_cards import images

    monkeypatch.setattr(images, "OUTPUT_BUCKET", "output")
    with pytest.raises(ValueError, match="unique after normalization"):
        images.generate_recipe_images(
            "soup", ["photo", "photo"], ["Step 1", "step-1"], SimpleNamespace(state={})
        )


def test_generated_assets_are_owned_by_session(monkeypatch):
    from recipe_cards import images, publish

    monkeypatch.setattr(images, "OUTPUT_BUCKET", "output")
    monkeypatch.setattr(publish, "OUTPUT_BUCKET", "output")
    monkeypatch.setattr(
        images,
        "generate_images",
        lambda *args, **kwargs: [SimpleNamespace(name="hero", data=png(), mime_type="image/png")],
    )
    monkeypatch.setattr(
        images,
        "upload_bytes",
        lambda project, bucket, name, *args, **kwargs: f"gs://{bucket}/{name}",
    )
    context = SimpleNamespace(state={})
    result = images.generate_recipe_images("soup", ["photo"], ["hero"], context)
    recipe = {**RECIPE, "hero_image_path": result["images"]["hero"]}
    import json

    with pytest.raises(ValueError, match="Unknown recipe run"):
        publish.render_recipe_card(json.dumps(recipe), SimpleNamespace(state={}), result["run_id"])
    render = Mock(return_value=b"deck")
    monkeypatch.setattr(publish, "render_deck", render)
    monkeypatch.setattr(publish, "upload_bytes", Mock(return_value="gs://output/deck.pptx"))
    publish.render_recipe_card(json.dumps(recipe), context, result["run_id"])
    assert render.call_args.kwargs["allowed_uris"] == {result["images"]["hero"]}


def test_bounded_download_reads_only_limit_plus_one(monkeypatch):
    from gemini_shared.connectors import cloud_storage

    client = Mock()
    blob = client.bucket.return_value.blob.return_value
    blob.download_as_bytes.return_value = b"12345"
    monkeypatch.setattr(cloud_storage.storage, "Client", Mock(return_value=client))
    with pytest.raises(ValueError, match="download limit"):
        cloud_storage.download_bytes("test", "gs://output/large.png", max_bytes=4)
    blob.download_as_bytes.assert_called_once_with(start=0, end=4, raw_download=True)


def test_authorized_image_is_embedded_in_deck(monkeypatch):
    monkeypatch.setattr(assets, "download_bytes", lambda *args, **kwargs: png())
    uri = "gs://output/soup/run/images/hero.png"
    recipe = {**RECIPE, "hero_image_path": uri, "decorative_image_path": uri}
    deck = Presentation(BytesIO(pages.render_deck(recipe, "test", allowed_uris={uri})))
    assert any(shape.shape_type == 13 for slide in deck.slides for shape in slide.shapes)
    assert assets.CURRENT_ASSETS.get() is None


def test_workflow_validation_blocks_bad_recipe_before_images():
    from recipe_card_workflow.stages.validation import validate_recipe_stage

    context = SimpleNamespace(state={"recipe": '{"recipes":"invalid"}'})
    with pytest.raises(ValueError):
        validate_recipe_stage(context)


@pytest.mark.parametrize("state", [{}, {"recipe": ""}, {"recipe": "   "}])
def test_workflow_validation_reports_a_missing_recipe(state):
    """An empty recipe means the writing stage produced nothing.

    That reached load_recipes as "" and raised a JSONDecodeError naming this
    file, which pointed at the wrong stage entirely.
    """
    from recipe_card_workflow.stages.validation import validate_recipe_stage

    with pytest.raises(ValueError, match="recipe_writer"):
        validate_recipe_stage(SimpleNamespace(state=state))


def test_workflow_validation_normalizes_recipe():
    import json

    from recipe_card_workflow.stages.validation import validate_recipe_stage

    context = SimpleNamespace(state={"recipe": json.dumps(RECIPE)})
    validate_recipe_stage(context)
    assert json.loads(context.state["recipe"])["title"] == "Soup"


def test_image_client_is_closed_after_attempt(monkeypatch):
    from gemini_shared.media import images as media

    client = Mock()
    manager = Mock()
    manager.__enter__ = Mock(return_value=client)
    manager.__exit__ = Mock(return_value=False)
    monkeypatch.setattr(media, "_client", Mock(return_value=manager))
    monkeypatch.setattr(media, "_wait_for_slot", lambda: None)
    monkeypatch.setattr(media, "_extract_image", lambda *args: (png(), "image/png"))
    result = media._generate_one("global", "test-model", media.ImageRequest("photo", "hero"), ())
    assert result.name == "hero"
    manager.__exit__.assert_called_once_with(None, None, None)
