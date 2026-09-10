"""Browsing published cards by relative path, and the root that fences them.

The model never handles a bucket name or an absolute URI: a listing hands it
relative paths and every path is rebuilt from the fixed use-case root. These
tests cover that structural guarantee rather than an allowlist comparison.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from types import SimpleNamespace
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

    result = discover.retrieve([FOLDER], SimpleNamespace(state={}))

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

    discover.retrieve([FOLDER, "tacos-al-pastor/20260908-x"], SimpleNamespace(state={}))

    assert [call.args[2] for call in listing.call_args_list] == [
        f"{USE_CASE_PREFIX}/{FOLDER}/",
        f"{USE_CASE_PREFIX}/tacos-al-pastor/20260908-x/",
    ]


def test_retrieve_needs_at_least_one_folder():
    with pytest.raises(ValueError, match="at least one folder"):
        discover.retrieve([], SimpleNamespace(state={}))


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
        discover.retrieve(["../../etc"], SimpleNamespace(state={}))
    listing.assert_not_called()


def test_preview_loads_one_image_the_model_can_see(monkeypatch):
    names = [f"{USE_CASE_PREFIX}/{FOLDER}/images/hero.png"]
    monkeypatch.setattr(discover, "list_objects", Mock(return_value=(names, [], False)))
    monkeypatch.setattr(discover, "download_bytes", Mock(return_value=b"\x89PNG"))
    saved = {}

    context = SimpleNamespace(
        state={},
        save_artifact=lambda filename, artifact: saved.update(
            {"filename": filename, "mime": artifact.inline_data.mime_type}
        ),
    )
    result = discover.retrieve([FOLDER], context, preview_image=f"{FOLDER}/images/hero.png")

    assert result["preview"] == saved["filename"]
    assert saved["mime"] == "image/png"


def test_only_an_image_can_be_previewed(monkeypatch):
    monkeypatch.setattr(discover, "list_objects", Mock(return_value=([], [], False)))
    download = Mock()
    monkeypatch.setattr(discover, "download_bytes", download)
    with pytest.raises(ValueError, match="Only an image"):
        discover.retrieve([FOLDER], SimpleNamespace(state={}), preview_image=f"{FOLDER}/deck.pptx")
    download.assert_not_called()


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


def test_only_the_agent_gets_browsing_tools():
    """A fixed pipeline cannot ask whether to reuse, so it has no browsing."""
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
    assert not ({"list_folders", "retrieve"} & staged)
