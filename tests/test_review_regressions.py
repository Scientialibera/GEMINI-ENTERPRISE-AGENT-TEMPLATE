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


@pytest.mark.parametrize(
    ("mode", "expected"),
    [("sequential_reference", [0, 2, 2]), ("parallel", [2, 2, 2])],
)
def test_the_image_opening_a_series_gets_no_style_plates(monkeypatch, mode, expected):
    """The plates are finished cards, so they need a subject to defer to.

    A hero generated against them alone copied their content rather than their
    light and came back as a spaghetti step-card, numbered panels and all. Every
    later image in a sequential batch is anchored by the photographs ahead of
    it, so the plates help there.
    """
    from recipe_cards import images as recipe_images

    monkeypatch.setattr(recipe_images, "OUTPUT_BUCKET", "test-bucket")
    monkeypatch.setattr(recipe_images, "_style_plates", lambda: (b"plate-1", b"plate-2"))
    monkeypatch.setattr(recipe_images, "upload_bytes", Mock())
    monkeypatch.setattr(recipe_images, "image_model_name", lambda: "test-image-model")
    seen = []

    def capture(requests, *, mode, on_image=None, model=None):
        seen.extend(len(request.reference_images) for request in requests)
        return []

    monkeypatch.setattr(recipe_images, "generate_images", capture)
    recipe_images.generate_recipe_images(
        "tacos", ["a", "b", "c"], ["hero", "step-1", "step-2"], SimpleNamespace(state={}), mode=mode
    )

    assert seen == expected


@pytest.mark.parametrize(
    "payload", ["{", "[]", "hello", '{"recipes": []}', '{"recipes": [{"title": "T"}]}']
)
def test_an_unreadable_payload_is_corrected_not_raised(monkeypatch, payload):
    """Every way a payload can be wrong reaches the model, not just the schema's.

    json.loads raises before pydantic ever runs, so unparsable JSON and a
    payload that is not an object used to escape the tool as a bare traceback
    and end the invocation.
    """
    from recipe_cards import publish

    monkeypatch.setattr(publish, "OUTPUT_BUCKET", "test-bucket")
    monkeypatch.setattr(publish, "get_runtime_config", lambda: SimpleNamespace(max_attempts=3))

    result = publish.render_recipe_card(payload, SimpleNamespace(state={}))

    assert result["status"] == "needs_correction"
    assert result["retryable"] is True
    # The edit asked for must match the failure: nothing here is too long.
    assert result["next_step"].startswith("Correct")
    assert result["problem"]
