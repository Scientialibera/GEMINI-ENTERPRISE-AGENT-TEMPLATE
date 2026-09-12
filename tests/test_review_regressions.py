"""Recovery and resource bounds across tool calls."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from google.api_core.exceptions import NotFound, PreconditionFailed
from recipe_cards import discover, images


def test_retrieval_preserves_retry_state_and_known_images():
    context = SimpleNamespace(
        state={
            "recipe_card_runs": {
                "run": {
                    "slug": "dish",
                    "images": {"hero": "dish/run/images/hero.png"},
                    "render_attempts": 3,
                    "render_failure": {"status": "failed"},
                }
            }
        }
    )
    discover._register_runs([{"folder": "dish/run", "path": "dish/run/images/onion.png"}], context)
    run = context.state["recipe_card_runs"]["run"]
    assert run["render_attempts"] == 3
    assert run["render_failure"] == {"status": "failed"}
    assert set(run["images"]) == {"hero", "onion"}


@pytest.mark.parametrize("mode", ["parallel", "sequential_reference"])
def test_partial_generation_checkpoints_success(monkeypatch, mode):
    from gemini_shared.media import images as media

    monkeypatch.setattr(images, "OUTPUT_BUCKET", "test-bucket")
    monkeypatch.setattr(images, "_style_plates", lambda: ())
    monkeypatch.setattr(images, "upload_bytes", Mock())
    first = media.GeneratedImage("first", b"png", "image/png", "a")
    monkeypatch.setattr(media, "_generate_one", Mock(side_effect=[first, RuntimeError("failed")]))
    context = SimpleNamespace(state={})
    result = images.generate_recipe_images(
        "dish", ["a", "b"], ["first", "second"], context, mode=mode
    )
    assert result["status"] == "partial"
    assert result["remaining_names"] == ["second"]
    assert set(context.state["recipe_card_runs"][result["run_id"]]["images"]) == {"first"}
    assert images.upload_bytes.call_count == 1


def test_listing_stops_before_second_prefix_page(monkeypatch):
    from gemini_shared.connectors import cloud_storage
    from google.auth.credentials import AnonymousCredentials
    from google.cloud import storage

    client = storage.Client(project="test", credentials=AnonymousCredentials())
    request = Mock(return_value={"prefixes": ["root/a/", "root/b/"], "nextPageToken": "next"})
    monkeypatch.setattr(client._connection, "api_request", request)
    monkeypatch.setattr(cloud_storage.storage, "Client", lambda **kwargs: client)
    assert cloud_storage.list_objects("test", "bucket", "root/", limit=1, delimiter="/") == (
        [],
        ["root/a/"],
        True,
    )
    assert request.call_count == 1


def test_coordinator_uses_conditional_creation(monkeypatch):
    from gemini_shared.media import pacing

    blob = Mock()
    blob.reload.side_effect = NotFound("missing")
    client = Mock()
    client.bucket.return_value.blob.return_value = blob
    monkeypatch.setattr(pacing.storage, "Client", lambda **kwargs: client)
    pacing.acquire_slot("project", "bucket", "model")
    assert blob.upload_from_string.call_args.kwargs["if_generation_match"] == 0


def test_coordinator_fails_closed_after_contention(monkeypatch):
    from gemini_shared.media import pacing

    blob = Mock()
    blob.reload.side_effect = NotFound("missing")
    blob.upload_from_string.side_effect = PreconditionFailed("lost race")
    client = Mock()
    client.bucket.return_value.blob.return_value = blob
    monkeypatch.setattr(pacing.storage, "Client", lambda **kwargs: client)
    monkeypatch.setattr(pacing.time, "monotonic", Mock(side_effect=[0, 0, 121]))
    monkeypatch.setattr(pacing.time, "sleep", Mock())
    with pytest.raises(TimeoutError):
        pacing.acquire_slot("project", "bucket", "model")


def test_coordinator_waits_for_existing_worker_slot(monkeypatch):
    from gemini_shared.media import pacing

    now = datetime(2026, 9, 12, tzinfo=UTC)
    clock = Mock()
    clock.now.side_effect = [now, now.replace(second=32)]
    monkeypatch.setattr(pacing, "datetime", clock)
    blob = Mock(generation=7, updated=now)
    client = Mock()
    client.bucket.return_value.blob.return_value = blob
    monkeypatch.setattr(pacing.storage, "Client", lambda **kwargs: client)
    sleep = Mock()
    monkeypatch.setattr(pacing.time, "sleep", sleep)
    pacing.acquire_slot("project", "bucket", "model")
    sleep.assert_called_once_with(32.0)
    assert blob.upload_from_string.call_args.kwargs["if_generation_match"] == 7


def test_runtime_exports_exclude_unused_extensions():
    from deploy.dependencies import export_requirements
    from registry import AGENTS

    for spec in AGENTS.values():
        requirements = export_requirements(spec)
        assert not any(
            line.startswith(("nltk==", "pytest==", "llama-index-")) for line in requirements
        )
