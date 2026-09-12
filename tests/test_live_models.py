"""Model selection follows live configuration without reconstructing agents."""

import asyncio
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from gemini_shared.config.runtime_config import RuntimeConfig
from gemini_shared.limits import RuntimeLimitsPlugin
from gemini_shared.media import images
from google.adk.models.llm_request import LlmRequest


def config(model="text-a", image_model="image-a", **kwargs):
    return RuntimeConfig(
        config_revision="test", model=model, image_model=image_model, instruction="test", **kwargs
    )


def test_workflow_and_compaction_follow_live_model(monkeypatch):
    from gemini_shared import limits

    current = config()
    monkeypatch.setattr(limits, "get_runtime_config", lambda: current)
    plugin = RuntimeLimitsPlugin()
    for model in ("text-a", "text-b"):
        current = config(model=model)
        context = SimpleNamespace(run_config=None)
        asyncio.run(plugin.before_run_callback(invocation_context=context))
        assert context.events_compaction_config.summarizer._llm.model == model
        for name in ("recipe_writer", "image_director", "card_renderer"):
            request = LlmRequest(model="bootstrap")
            asyncio.run(
                plugin.before_model_callback(
                    callback_context=SimpleNamespace(agent_name=name), llm_request=request
                )
            )
            assert request.model == model


def test_image_model_changes_between_batches(monkeypatch):
    current = config()
    monkeypatch.setattr(images, "get_runtime_config", lambda: current)
    generate = Mock(return_value=images.GeneratedImage("hero", b"png", "image/png", "photo"))
    monkeypatch.setattr(images, "_generate_one", generate)
    for model in ("image-a", "image-b"):
        current = config(image_model=model)
        images.generate_images([images.ImageRequest("photo", "hero")])
        assert generate.call_args.args[1] == model


def test_reference_limit_defaults_to_five_and_is_live(monkeypatch):
    current = config()
    monkeypatch.setattr(images, "get_runtime_config", lambda: current)
    monkeypatch.setattr(images, "_wait_for_slot", lambda: None)
    client = Mock()
    manager = Mock(__enter__=Mock(return_value=client), __exit__=Mock(return_value=False))
    monkeypatch.setattr(images, "_client", lambda _: manager)
    monkeypatch.setattr(images, "_extract_image", lambda *args: (b"png", "image/png"))
    for limit in (5, 2):
        current = config(max_reference_images=limit)
        images._generate_one(
            "global",
            "image-a",
            images.ImageRequest("photo", "hero", (b"plate",) * 2),
            (b"previous",) * 8,
        )
        parts = client.models.generate_content.call_args.kwargs["contents"][0].parts
        assert sum(part.inline_data is not None for part in parts) == limit
    assert config().max_reference_images == 5


@pytest.mark.parametrize(
    "settings", [{"image_model": " "}, {"max_reference_images": 0}, {"max_reference_images": 15}]
)
def test_invalid_image_settings_rejected(settings):
    with pytest.raises(ValueError):
        config(**settings)
