"""Workflow stages take their instructions from live configuration.

A workflow has no single instruction to publish: SequentialAgent takes none and
each stage carries its own. These cover the two properties that make publishing
them safe — an unpublished stage still runs, and the session-state hand-off
between stages survives the move to a callable instruction.
"""

from __future__ import annotations

import asyncio
import importlib
from types import SimpleNamespace

import pytest
from gemini_shared.config import runtime_agent
from gemini_shared.config.runtime_config import RuntimeConfig

STAGES = ("recipe_writer", "image_director", "card_renderer")


def config(**kwargs):
    return RuntimeConfig(
        config_revision="test", model="text-a", instruction="agent instruction", **kwargs
    )


class FakeContext(SimpleNamespace):
    """Stands in for ReadonlyContext, which only the state mapping is read from."""

    def __init__(self, state=None):
        session = SimpleNamespace(state=state or {})
        super().__init__(_invocation_context=SimpleNamespace(session=session))
        self.state = state or {}


def resolve(provider, state=None):
    return asyncio.run(provider(FakeContext(state)))


def test_an_unpublished_stage_uses_the_text_in_its_module(monkeypatch):
    """Publishing nothing must change nothing, or a deploy would need a publish."""
    monkeypatch.setattr(runtime_agent, "get_runtime_config", config)
    provider = runtime_agent.stage_instruction("recipe_writer", "compiled in")
    assert resolve(provider) == "compiled in"


def test_a_published_stage_overrides_its_module(monkeypatch):
    monkeypatch.setattr(
        runtime_agent,
        "get_runtime_config",
        lambda: config(stage_instructions={"recipe_writer": "published"}),
    )
    provider = runtime_agent.stage_instruction("recipe_writer", "compiled in")
    assert resolve(provider) == "published"


@pytest.mark.parametrize("published", ["", "   "])
def test_a_blank_entry_falls_back_rather_than_emptying_the_stage(monkeypatch, published):
    """An empty instruction would leave the stage with nothing to do."""
    monkeypatch.setattr(
        runtime_agent,
        "get_runtime_config",
        lambda: config(stage_instructions={"recipe_writer": published}),
    )
    provider = runtime_agent.stage_instruction("recipe_writer", "compiled in")
    assert resolve(provider) == "compiled in"


def test_an_unreadable_parameter_still_runs_the_stage(monkeypatch):
    """A configuration fault must not stop work the module text can still do."""

    def broken():
        raise RuntimeError("parameter unreadable")

    monkeypatch.setattr(runtime_agent, "get_runtime_config", broken)
    provider = runtime_agent.stage_instruction("card_renderer", "compiled in")
    assert resolve(provider) == "compiled in"


@pytest.mark.parametrize("source", ["module", "published"])
def test_state_placeholders_are_filled_either_way(monkeypatch, source):
    """The hand-off between stages depends on this substitution.

    ADK reports a callable instruction as bypassing state injection, so a
    resolver that returned the string unchanged would hand the model a literal
    `{recipe}` and silently break the chain.
    """
    template = "Recipe:\n{recipe}\nEnd."
    published = {"image_director": template} if source == "published" else {}
    monkeypatch.setattr(
        runtime_agent, "get_runtime_config", lambda: config(stage_instructions=published)
    )
    provider = runtime_agent.stage_instruction("image_director", template)
    assert resolve(provider, {"recipe": "a chili"}) == "Recipe:\na chili\nEnd."


def test_every_workflow_stage_resolves_from_configuration():
    """Each stage must go through the resolver, not a static string."""
    module = importlib.import_module("recipe_card_workflow.workflow")
    stages = {stage.name: stage for stage in module.root_agent.sub_agents}
    assert set(stages) == set(STAGES)
    for name, stage in stages.items():
        assert callable(stage.instruction), f"{name} does not resolve its instruction"


def test_stage_names_match_the_published_keys():
    """A typo in either place silently leaves that stage unpublishable."""
    from recipe_card_workflow import stages as stage_package

    for name in STAGES:
        agent = getattr(stage_package, name)
        assert agent.name == name
