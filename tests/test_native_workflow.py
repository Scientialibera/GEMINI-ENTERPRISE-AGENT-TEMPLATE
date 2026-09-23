from unittest.mock import Mock

import pytest
from register import native_workflow as native

URL = "https://discoveryengine.googleapis.com/v1alpha/projects/123/agents"
BACKEND = "projects/123/agents/backend"
WRAPPER = "projects/123/agents/wrapper"
RUNTIME = "projects/123/locations/us-central1/reasoningEngines/456"


def backend(display="Recipe Workflow"):
    return {
        "name": BACKEND,
        "displayName": display,
        "adkAgentDefinition": {"provisionedReasoningEngine": {"reasoningEngine": RUNTIME}},
    }


def test_backend_migration_preserves_id():
    assert native.find_backend([backend()], "Recipe Workflow", RUNTIME) == BACKEND
    assert (
        native.find_backend([backend("Recipe Workflow Backend")], "Recipe Workflow", RUNTIME)
        == BACKEND
    )


def test_backend_rejects_wrong_runtime_and_duplicates():
    with pytest.raises(ValueError, match="different runtime"):
        native.find_backend([backend()], "Recipe Workflow", "other")
    with pytest.raises(ValueError, match="Multiple"):
        native.find_backend([backend(), backend()], "Recipe Workflow", RUNTIME)


def test_wrapper_payload_is_manual_and_references_backend():
    payload = native.wrapper_payload("recipe", "Recipe Workflow", BACKEND)
    assert "adkAgentDefinition" not in payload
    nodes = payload["workflowAgentDefinition"]["agentFlow"]["nodes"]
    assert nodes[0]["nodeType"] == "MANUAL_TRIGGER"
    assert nodes[1]["agentReferenceNode"]["agent"] == BACKEND
    assert payload["state"] == "ENABLED"


def test_unmanaged_wrapper_name_collision_fails():
    with pytest.raises(ValueError, match="unmanaged"):
        native.find_wrapper(
            [{"displayName": "Recipe Workflow", "workflowAgentDefinition": {}}],
            "recipe",
            "Recipe Workflow",
        )


def test_create_verifies_remote_reference(monkeypatch):
    payload = native.wrapper_payload("recipe", "Recipe Workflow", BACKEND)
    payload["name"] = WRAPPER
    monkeypatch.setattr(native, "iter_resources", lambda *args: iter([]))
    call = Mock(side_effect=[{"name": WRAPPER}, payload])
    monkeypatch.setattr(native, "request", call)
    assert native.ensure_wrapper(URL, "123", "recipe", "Recipe Workflow", BACKEND) == WRAPPER
    assert [c.args[0] for c in call.call_args_list] == ["POST", "GET"]


def test_repeat_release_preserves_schedule_prompt_and_sharing(monkeypatch):
    payload = native.wrapper_payload("recipe", "Recipe Workflow", BACKEND)
    payload.update(name=WRAPPER, state="PRIVATE")
    payload["workflowAgentDefinition"]["agentFlow"]["nodes"][0] = {"nodeType": "SCHEDULE_TRIGGER"}
    monkeypatch.setattr(native, "iter_resources", lambda *args: iter([payload]))
    call = Mock(return_value=payload)
    monkeypatch.setattr(native, "request", call)
    assert native.ensure_wrapper(URL, "123", "recipe", "Recipe Workflow", BACKEND) == WRAPPER
    assert call.call_count == 1
    assert call.call_args.args[0] == "GET"


def test_changed_reference_requires_review(monkeypatch):
    payload = native.wrapper_payload("recipe", "Recipe Workflow", "other")
    payload["name"] = WRAPPER
    monkeypatch.setattr(native, "iter_resources", lambda *args: iter([payload]))
    call = Mock()
    monkeypatch.setattr(native, "request", call)
    with pytest.raises(ValueError, match="no longer references"):
        native.ensure_wrapper(URL, "123", "recipe", "Recipe Workflow", BACKEND)
    call.assert_not_called()
