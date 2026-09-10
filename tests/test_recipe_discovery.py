"""Finding published cards, reusing their photography, and the dish fence."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from recipe_cards import discover
from recipe_cards.config import USE_CASE_PREFIX

DEV = Path(__file__).resolve().parents[1] / "dev"
sys.path.insert(0, str(DEV))
registry = importlib.import_module("registry")
sys.path.remove(str(DEV))

BUCKET = "test-bucket"
SLUG = "classic-beef-chili"
RUN = "20260910-120000-abc"


@pytest.fixture(autouse=True)
def bucket(monkeypatch):
    monkeypatch.setattr(discover, "OUTPUT_BUCKET", BUCKET)
    monkeypatch.setattr(discover, "PROJECT_ID", "test-project")


def _objects(*names: str) -> list[str]:
    return [f"{USE_CASE_PREFIX}/{SLUG}/{name}" for name in names]


def test_missing_bucket_fails_rather_than_listing_nothing(monkeypatch):
    """An unset bucket is a configuration fault, not an empty catalogue."""
    monkeypatch.setattr(discover, "OUTPUT_BUCKET", "")
    with pytest.raises(RuntimeError, match="RECIPE_CARD_BUCKET"):
        discover.list_recipe_cards()


def test_dishes_are_listed_from_the_use_case_prefix(monkeypatch):
    """Only this use case's dishes, named without their prefix."""
    listing = Mock(
        return_value=([], [f"{USE_CASE_PREFIX}/{SLUG}/", f"{USE_CASE_PREFIX}/tacos/"], False)
    )
    monkeypatch.setattr(discover, "list_objects", listing)

    result = discover.list_recipe_cards()

    assert result["dishes"] == [SLUG, "tacos"]
    assert result["truncated"] is False
    # A delimiter keeps this one metadata call instead of walking every object.
    assert listing.call_args.kwargs["delimiter"] == "/"
    assert listing.call_args.args[2] == f"{USE_CASE_PREFIX}/"


def test_truncation_is_reported_not_hidden(monkeypatch):
    """A partial list must not read as the complete catalogue."""
    monkeypatch.setattr(discover, "list_objects", Mock(return_value=([], [], True)))
    assert discover.list_recipe_cards()["truncated"] is True


def test_runs_are_grouped_newest_first_with_decks_and_counts(monkeypatch):
    older = "20260901-090000-zzz"
    names = _objects(
        f"{RUN}/images/hero.png",
        f"{RUN}/images/step-1.png",
        f"{RUN}/20260910-120500-recipe-cards.pptx",
        f"{older}/images/hero.png",
    )
    monkeypatch.setattr(discover, "list_objects", Mock(return_value=(names, [], False)))
    context = SimpleNamespace(state={})

    result = discover.find_recipe_runs(SLUG, context)

    assert [run["run_id"] for run in result["runs"]] == [RUN, older]
    newest = result["runs"][0]
    assert newest["image_count"] == 2
    assert newest["decks"] == [
        f"{discover.CONSOLE_URL_PREFIX}/{BUCKET}/{USE_CASE_PREFIX}/{SLUG}/{RUN}"
        "/20260910-120500-recipe-cards.pptx"
    ]
    assert result["reusable_image_count"] == 3


def test_found_images_become_renderable_for_that_dish(monkeypatch):
    """Rediscovered photography must pass render_recipe_card's fence.

    The renderer only accepts URIs registered for the run, so a rediscovered
    card would otherwise be listed but impossible to rebuild.
    """
    names = _objects(f"{RUN}/images/hero.png")
    monkeypatch.setattr(discover, "list_objects", Mock(return_value=(names, [], False)))
    context = SimpleNamespace(state={})

    result = discover.find_recipe_runs(SLUG, context)

    assert result["reuse_run_id"] == SLUG
    stored = context.state["recipe_card_runs"][SLUG]
    assert stored["slug"] == SLUG
    assert stored["reusable_uris"] == [
        f"gs://{BUCKET}/{USE_CASE_PREFIX}/{SLUG}/{RUN}/images/hero.png"
    ]


def test_a_dish_with_no_runs_registers_nothing(monkeypatch):
    """Nothing found means nothing becomes renderable."""
    monkeypatch.setattr(discover, "list_objects", Mock(return_value=([], [], False)))
    context = SimpleNamespace(state={})

    result = discover.find_recipe_runs("never-made", context)

    assert result["run_count"] == 0
    assert result["reuse_run_id"] == ""
    assert context.state == {}


def test_lookup_is_scoped_to_the_requested_dish(monkeypatch):
    """Another dish's images must never be pulled into this card."""
    listing = Mock(return_value=([], [], False))
    monkeypatch.setattr(discover, "list_objects", listing)

    discover.find_recipe_runs("Classic Beef Chili!!", SimpleNamespace(state={}))

    # The slug is normalized and the query is fenced to that dish alone.
    assert listing.call_args.args[2] == f"{USE_CASE_PREFIX}/{SLUG}/"


def test_render_accepts_reused_images_but_not_another_dishs(monkeypatch):
    """The fence is the dish: its own runs are reusable, others are not."""
    from recipe_cards import publish

    monkeypatch.setattr(publish, "OUTPUT_BUCKET", BUCKET)
    captured = {}

    def render(data, project, allowed_uris):
        captured["allowed"] = allowed_uris
        return b"deck"

    monkeypatch.setattr(publish, "render_deck", render)
    monkeypatch.setattr(publish, "upload_bytes", Mock(return_value=f"gs://{BUCKET}/deck.pptx"))
    monkeypatch.setattr(publish, "load_recipes", lambda _: {"recipes": [{"slug": SLUG}]})

    reused = f"gs://{BUCKET}/{USE_CASE_PREFIX}/{SLUG}/{RUN}/images/hero.png"
    foreign = f"gs://{BUCKET}/{USE_CASE_PREFIX}/tacos/{RUN}/images/hero.png"
    context = SimpleNamespace(
        state={"recipe_card_runs": {SLUG: {"slug": SLUG, "images": {}, "reusable_uris": [reused]}}}
    )

    publish.render_recipe_card("{}", context, SLUG)

    assert reused in captured["allowed"]
    assert foreign not in captured["allowed"]


def test_deck_and_images_share_the_use_case_prefix():
    """Both artefacts must land under the same dish prefix to be discoverable."""
    from recipe_cards.images import _object_name

    name = _object_name(SLUG, RUN, "hero")
    assert name.startswith(f"{USE_CASE_PREFIX}/{SLUG}/{RUN}/images/")
    assert discover.dish_prefix(SLUG) == f"{USE_CASE_PREFIX}/{SLUG}/"


@pytest.mark.parametrize("entry", ["recipe_card_agent", "recipe_card_workflow"])
def test_both_entry_points_declare_the_same_prefix(entry):
    """Split prefixes would hide the workflow's cards from the agent."""
    spec = registry.get_agent_spec(entry)
    assert dict(spec.runtime_env)["RECIPE_CARD_PREFIX"] == "recipe-cards"


def test_only_the_agent_gets_discovery_tools():
    """A fixed pipeline cannot ask whether to reuse, so it has no discovery."""
    agent = importlib.import_module("recipe_card_agent.agent")
    names = {getattr(tool, "__name__", "") for tool in agent.root_agent.tools if callable(tool)}
    assert {"list_recipe_cards", "find_recipe_runs"} <= names

    workflow = importlib.import_module("recipe_card_workflow.workflow")
    staged = {
        getattr(tool, "__name__", "")
        for stage in workflow.root_agent.sub_agents
        for tool in (stage.tools or [])
        if callable(tool)
    }
    assert not ({"list_recipe_cards", "find_recipe_runs"} & staged)
