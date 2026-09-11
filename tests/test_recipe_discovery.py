"""Browsing published cards by relative path, and the root that fences them.

The model never handles a bucket name or an absolute URI: a listing hands it
relative paths and every path is rebuilt from the fixed use-case root. These
tests cover that structural guarantee rather than an allowlist comparison.
"""

from __future__ import annotations

import asyncio
import importlib
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import ClassVar
from unittest.mock import Mock

import pytest
from recipe_cards import discover
from recipe_cards.config import USE_CASE_PREFIX, resolve_relative

DEV = Path(__file__).resolve().parents[1] / "dev"
sys.path.insert(0, str(DEV))
registry = importlib.import_module("registry")
sys.path.remove(str(DEV))

BUCKET = "test-bucket"
SLUG = "classic-beef-chili"
RUN = "20260910-120000-abc"
FOLDER = f"{SLUG}/{RUN}"


@pytest.fixture(autouse=True)
def bucket(monkeypatch):
    monkeypatch.setattr(discover, "OUTPUT_BUCKET", BUCKET)
    monkeypatch.setattr(discover, "PROJECT_ID", "test-project")


def test_missing_bucket_fails_rather_than_listing_nothing(monkeypatch):
    """An unset bucket is a configuration fault, not an empty catalogue."""
    monkeypatch.setattr(discover, "OUTPUT_BUCKET", "")
    with pytest.raises(RuntimeError, match="RECIPE_CARD_BUCKET"):
        discover.list_folders()


def test_folders_are_relative_and_newest_first(monkeypatch):
    """Paths carry no bucket, and a dish's newest run comes first."""
    older = f"{USE_CASE_PREFIX}/{SLUG}/20260901-090000-zzz/"
    calls = [
        ([], [f"{USE_CASE_PREFIX}/{SLUG}/"], False),
        ([], [f"{USE_CASE_PREFIX}/{SLUG}/{RUN}/", older], False),
    ]
    monkeypatch.setattr(discover, "list_objects", Mock(side_effect=calls))

    result = discover.list_folders()

    assert [folder["path"] for folder in result["folders"]] == [
        FOLDER,
        f"{SLUG}/20260901-090000-zzz",
    ]
    assert all(folder["dish"] == SLUG for folder in result["folders"])
    # Nothing in the response exposes the bucket.
    assert BUCKET not in str(result)


def test_truncation_is_reported_not_hidden(monkeypatch):
    """A partial listing must not read as the complete catalogue."""
    monkeypatch.setattr(discover, "list_objects", Mock(return_value=([], [], True)))
    assert discover.list_folders()["truncated"] is True


def test_retrieve_returns_relative_paths_and_a_deck_link(monkeypatch):
    names = [
        f"{USE_CASE_PREFIX}/{FOLDER}/images/hero.png",
        f"{USE_CASE_PREFIX}/{FOLDER}/images/step-1.png",
        f"{USE_CASE_PREFIX}/{FOLDER}/20260910-120500-recipe-cards.pptx",
    ]
    monkeypatch.setattr(discover, "list_objects", Mock(return_value=(names, [], False)))

    result = asyncio.run(discover.retrieve([FOLDER], SimpleNamespace(state={})))

    assert result["image_count"] == 2
    assert [image["path"] for image in result["images"]] == [
        f"{FOLDER}/images/hero.png",
        f"{FOLDER}/images/step-1.png",
    ]
    # A deck is a link, never bytes: its content is useless to a model.
    assert result["decks"][0]["url"].startswith("https://storage.cloud.google.com/")
    assert "preview" not in result


def test_retrieve_accepts_several_folders(monkeypatch):
    listing = Mock(return_value=([], [], False))
    monkeypatch.setattr(discover, "list_objects", listing)

    asyncio.run(
        discover.retrieve([FOLDER, "tacos-al-pastor/20260908-x"], SimpleNamespace(state={}))
    )

    assert [call.args[2] for call in listing.call_args_list] == [
        f"{USE_CASE_PREFIX}/{FOLDER}/",
        f"{USE_CASE_PREFIX}/tacos-al-pastor/20260908-x/",
    ]


def test_retrieve_needs_at_least_one_folder():
    with pytest.raises(ValueError, match="at least one folder"):
        asyncio.run(discover.retrieve([], SimpleNamespace(state={})))


@pytest.mark.parametrize(
    "path",
    [
        "../secrets/key.png",
        "chili/../../other/hero.png",
        "/absolute/hero.png",
        "gs://other-bucket/hero.png",
        "https://example.com/hero.png",
        "",
    ],
)
def test_paths_cannot_escape_the_use_case_root(path):
    """Resolution is what authorizes an asset, so traversal must fail closed."""
    with pytest.raises(ValueError):
        resolve_relative(path)


def test_resolution_rebuilds_the_path_under_the_root():
    assert resolve_relative(FOLDER) == f"{USE_CASE_PREFIX}/{FOLDER}"
    # A trailing slash is tolerated, since a folder reads naturally with one.
    assert resolve_relative(f"{FOLDER}/") == f"{USE_CASE_PREFIX}/{FOLDER}"
    # A leading slash is not: it was meant to be absolute, and quietly
    # reinterpreting it under the root would substitute a different object.
    with pytest.raises(ValueError, match="relative to the card store"):
        resolve_relative(f"/{FOLDER}")


def test_a_traversing_folder_is_rejected_before_listing(monkeypatch):
    listing = Mock()
    monkeypatch.setattr(discover, "list_objects", listing)
    with pytest.raises(ValueError):
        asyncio.run(discover.retrieve(["../../etc"], SimpleNamespace(state={})))
    listing.assert_not_called()


def test_preview_actually_saves_the_artifact(monkeypatch):
    """save_artifact is a coroutine, so an unawaited call saves nothing.

    The fake below is async for that reason: a synchronous stand-in accepts the
    bare call happily and hides a preview that reports a filename it never
    wrote.
    """
    names = [f"{USE_CASE_PREFIX}/{FOLDER}/images/hero.png"]
    monkeypatch.setattr(discover, "list_objects", Mock(return_value=(names, [], False)))
    monkeypatch.setattr(discover, "download_bytes", Mock(return_value=b"\x89PNG"))
    saved = {}

    async def save_artifact(filename, artifact):
        saved.update({"filename": filename, "mime": artifact.inline_data.mime_type})
        return 1

    context = SimpleNamespace(state={}, save_artifact=save_artifact)
    result = asyncio.run(
        discover.retrieve([FOLDER], context, preview_image=f"{FOLDER}/images/hero.png")
    )

    assert saved, "the preview reported success without saving anything"
    assert result["preview"] == saved["filename"]
    assert saved["mime"] == "image/png"


def test_only_an_image_can_be_previewed(monkeypatch):
    monkeypatch.setattr(discover, "list_objects", Mock(return_value=([], [], False)))
    download = Mock()
    monkeypatch.setattr(discover, "download_bytes", download)
    with pytest.raises(ValueError, match="Only an image"):
        asyncio.run(
            discover.retrieve(
                [FOLDER], SimpleNamespace(state={}), preview_image=f"{FOLDER}/deck.pptx"
            )
        )
    download.assert_not_called()


def test_a_folder_listing_reports_truncation_from_prefixes(monkeypatch):
    """max_results bounds objects, not prefixes.

    A delimited listing returns its children as prefixes, so counting only
    objects lets a folder listing omit folders while claiming completeness.
    """
    from gemini_shared.connectors import cloud_storage

    class FakeIterator:
        prefixes: ClassVar[set[str]] = {f"{USE_CASE_PREFIX}/dish-{i}/" for i in range(4)}

        def __iter__(self):
            return iter(())

    client = Mock()
    client.list_blobs.return_value = FakeIterator()
    monkeypatch.setattr(cloud_storage.storage, "Client", lambda **kwargs: client)

    names, prefixes, truncated = cloud_storage.list_objects(
        "test-project", BUCKET, f"{USE_CASE_PREFIX}/", limit=1, delimiter="/"
    )

    assert names == []
    assert len(prefixes) == 1, "prefixes must respect the limit"
    assert truncated is True, "a partial folder listing must not claim to be complete"


def test_generated_images_are_returned_as_relative_paths():
    """What generation returns must be what a recipe field accepts."""
    from recipe_cards.images import _object_name

    name = _object_name(SLUG, RUN, "hero")
    assert name.startswith(f"{USE_CASE_PREFIX}/{SLUG}/{RUN}/images/")
    assert resolve_relative(name.removeprefix(f"{USE_CASE_PREFIX}/")) == name


@pytest.mark.parametrize("entry", ["recipe_card_agent", "recipe_card_workflow"])
def test_both_entry_points_declare_the_same_prefix(entry):
    """Split prefixes would hide the workflow's cards from the agent."""
    spec = registry.get_agent_spec(entry)
    assert dict(spec.runtime_env)["RECIPE_CARD_PREFIX"] == "recipe-cards"


def test_workflow_can_verify_assets_without_browsing_existing_dishes():
    """Both paths inspect files; only the conversational agent offers reuse."""
    agent = importlib.import_module("recipe_card_agent.agent")
    names = {getattr(tool, "__name__", "") for tool in agent.root_agent.tools if callable(tool)}
    assert {"list_folders", "retrieve"} <= names

    workflow = importlib.import_module("recipe_card_workflow.workflow")
    staged = {
        getattr(tool, "__name__", "")
        for stage in workflow.root_agent.sub_agents
        for tool in (stage.tools or [])
        if callable(tool)
    }
    assert "list_folders" not in staged
    assert "retrieve" in staged


def test_a_retrieved_run_can_be_topped_up_and_rendered(monkeypatch):
    """The sequence a reuse request actually produces, end to end.

    Asked to reuse existing photography and generate the few missing images,
    the model retrieves a folder and passes that run id back. Session state
    only knew runs this conversation created, so the id it had just been handed
    was rejected and the request failed at the first image call.
    """
    from recipe_cards import images as images_module
    from recipe_cards import publish

    stored = [
        f"{USE_CASE_PREFIX}/{FOLDER}/images/ingredient-pork.png",
        f"{USE_CASE_PREFIX}/{FOLDER}/images/step-1.png",
    ]
    monkeypatch.setattr(discover, "list_objects", Mock(return_value=(stored, [], False)))
    context = SimpleNamespace(state={})

    asyncio.run(discover.retrieve([FOLDER], context))

    # The run the bucket holds is now resolvable by run id, not only by slug.
    assert RUN in context.state["recipe_card_runs"]
    registered = context.state["recipe_card_runs"][RUN]
    assert registered["slug"] == SLUG
    assert set(registered["images"]) == {"ingredient-pork", "step-1"}

    # Topping the run up with the hero it was missing now succeeds.
    monkeypatch.setattr(images_module, "OUTPUT_BUCKET", BUCKET)
    monkeypatch.setattr(
        images_module,
        "generate_images",
        Mock(return_value=[SimpleNamespace(name="hero", data=b"\x89PNG", mime_type="image/png")]),
    )
    monkeypatch.setattr(images_module, "upload_bytes", Mock())
    result = images_module.generate_recipe_images(
        SLUG, ["A hero shot"], ["hero"], context, run_id=RUN
    )

    assert result["run_id"] == RUN
    assert result["images"]["hero"].startswith(f"{SLUG}/{RUN}/images/")

    # And the deck renders against that same run rather than starting a new one.
    monkeypatch.setattr(publish, "OUTPUT_BUCKET", BUCKET)
    monkeypatch.setattr(publish, "render_deck", Mock(return_value=b"deck"))
    monkeypatch.setattr(publish, "upload_bytes", Mock(return_value=f"gs://{BUCKET}/deck.pptx"))
    monkeypatch.setattr(publish, "load_recipes", lambda _: {"recipes": [{"slug": SLUG}]})

    rendered = publish.render_recipe_card("{}", context, RUN)

    assert rendered["run_id"] == RUN


def test_an_invented_run_id_is_still_rejected(monkeypatch):
    """Registering retrieved runs must not let the model conjure one.

    The guard exists so a run id that was never produced by a tool cannot be
    used to write into an arbitrary folder.
    """
    from recipe_cards import images as images_module

    monkeypatch.setattr(discover, "list_objects", Mock(return_value=([], [], False)))
    context = SimpleNamespace(state={})
    asyncio.run(discover.retrieve([FOLDER], context))

    monkeypatch.setattr(images_module, "OUTPUT_BUCKET", BUCKET)
    monkeypatch.setattr(images_module, "generate_images", Mock())
    with pytest.raises(ValueError, match="Unknown recipe run"):
        images_module.generate_recipe_images(
            SLUG, ["A hero shot"], ["hero"], context, run_id="20260101-000000-invented"
        )


def test_a_stored_photograph_is_not_silently_regenerated(monkeypatch):
    """Registering a run makes its stored names count as taken.

    Reusing a folder means its photographs are real files. The name guard and
    the per-run image budget both read `images`, so a retrieved run refuses a
    name the bucket already holds instead of overwriting it. The model is told
    to generate only what is missing, so this is the boundary of that
    instruction rather than an obstacle to it.
    """
    from recipe_cards import images as images_module

    stored = [f"{USE_CASE_PREFIX}/{FOLDER}/images/hero.png"]
    monkeypatch.setattr(discover, "list_objects", Mock(return_value=(stored, [], False)))
    context = SimpleNamespace(state={})
    asyncio.run(discover.retrieve([FOLDER], context))

    monkeypatch.setattr(images_module, "OUTPUT_BUCKET", BUCKET)
    generate = Mock()
    monkeypatch.setattr(images_module, "generate_images", generate)
    with pytest.raises(ValueError, match="already exists"):
        images_module.generate_recipe_images(SLUG, ["Another hero"], ["hero"], context, run_id=RUN)
    assert not generate.called, "a refused name must not reach the image model"


def test_a_top_up_returns_only_what_it_generated(monkeypatch):
    """The return value is this call's work; the run carries the whole set.

    A top-up reports only the images it just made, so the recipe's remaining
    image fields are filled from what `retrieve` listed rather than from here.
    The stored paths are still added to the run, which is what the name guard,
    the per-run budget and the renderer read.
    """
    from recipe_cards import images as images_module

    stored = [
        f"{USE_CASE_PREFIX}/{FOLDER}/images/ingredient-pork.png",
        f"{USE_CASE_PREFIX}/{FOLDER}/images/step-1.png",
    ]
    monkeypatch.setattr(discover, "list_objects", Mock(return_value=(stored, [], False)))
    context = SimpleNamespace(state={})
    asyncio.run(discover.retrieve([FOLDER], context))

    monkeypatch.setattr(images_module, "OUTPUT_BUCKET", BUCKET)
    monkeypatch.setattr(
        images_module,
        "generate_images",
        Mock(return_value=[SimpleNamespace(name="hero", data=b"\x89PNG", mime_type="image/png")]),
    )
    monkeypatch.setattr(images_module, "upload_bytes", Mock())

    result = images_module.generate_recipe_images(
        SLUG, ["A hero shot"], ["hero"], context, run_id=RUN
    )

    assert set(result["images"]) == {"hero"}, "the return value reports this call's work"
    stored_run = context.state["recipe_card_runs"][RUN]["images"]
    assert set(stored_run) == {"hero", "ingredient-pork", "step-1"}
