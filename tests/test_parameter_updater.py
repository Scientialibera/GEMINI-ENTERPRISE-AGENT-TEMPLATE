"""The Parameter Updater publishes only previewed, valid, non-stale changes."""

import json
from types import SimpleNamespace

import pytest
from gemini_shared.config.runtime_config import reset_runtime_config_for_tests
from google.api_core import exceptions

TARGET = "basic-assistant-config"
OWN = "parameter-updater-config"
LIVE = {
    "config_revision": "bootstrap-v1",
    "model": "gemini-3.7-flash",
    "instruction": "Line one.\nLine two.",
    "log_level": "INFO",
}


class FakeManager:
    """In-memory stand-in for the Parameter Manager calls the tools make."""

    def __init__(self):
        self.payloads = {
            TARGET: {"bootstrap-v1": json.dumps(LIVE)},
            OWN: {"bootstrap-v1": json.dumps(LIVE)},
            "not-a-config": {"v1": json.dumps({"hello": "world"})},
        }
        self.latest = {name: next(iter(v)) for name, v in self.payloads.items()}
        self.created = []
        self.projects = []

    def list_parameter_ids(self, project):
        self.projects.append(project)
        return sorted(self.payloads)

    def render(self, project, parameter, version="latest"):
        self.projects.append(project)
        if parameter not in self.payloads:
            raise exceptions.NotFound("missing")
        version = self.latest[parameter] if version == "latest" else version
        return SimpleNamespace(version=version, payload=self.payloads[parameter][version])

    def list_versions(self, project, parameter, limit):
        return [{"version": v} for v in self.payloads[parameter]][:limit]

    def create_version(self, project, parameter, version, payload):
        self.created.append((project, parameter, version, payload))
        self.payloads[parameter][version] = payload
        self.latest[parameter] = version
        return version


@pytest.fixture
def tools(monkeypatch):
    monkeypatch.delenv("CONFIG_PARAMETER", raising=False)
    monkeypatch.delenv("MANAGED_PROJECT", raising=False)
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "home-project")
    monkeypatch.setenv("GOOGLE_CLOUD_LOCATION", "us-central1")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-test")
    monkeypatch.setenv("AGENT_INSTRUCTION", "test instruction")
    reset_runtime_config_for_tests()

    from parameter_updater.tools import parameters

    fake = FakeManager()
    monkeypatch.setattr(parameters, "manager", fake)
    monkeypatch.setattr(parameters, "PROJECT_ID", "home-project")
    monkeypatch.setattr(parameters, "_own_parameter", lambda: OWN)
    yield parameters, fake
    reset_runtime_config_for_tests()


def _context():
    return SimpleNamespace(state={}, user_id="user-123")


def test_preview_publishes_nothing_and_apply_publishes_exactly_the_preview(tools):
    parameters, fake = tools
    context = _context()

    preview = parameters.preview_parameter_update(
        TARGET, json.dumps({"model": "gemini-3.7-pro"}), context
    )

    assert preview["status"] == "awaiting_confirmation"
    assert preview["changes"] == [
        {"field": "model", "before": "gemini-3.7-flash", "after": "gemini-3.7-pro"}
    ]
    assert fake.created == []

    applied = parameters.apply_parameter_update(preview["change_id"], context)

    assert applied["status"] == "applied"
    assert applied["previous_version"] == "bootstrap-v1"
    [(project, parameter, version, payload)] = fake.created
    written = json.loads(payload)
    assert (project, parameter, version) == ("home-project", TARGET, preview["new_revision"])
    assert written["model"] == "gemini-3.7-pro"
    assert written["instruction"] == LIVE["instruction"]
    assert written["config_revision"] == preview["new_revision"]
    # A second apply of the same ID must not publish again.
    assert parameters.apply_parameter_update(preview["change_id"], context)["status"] == "error"
    assert len(fake.created) == 1


def test_apply_refuses_when_another_version_went_live_after_the_preview(tools):
    parameters, fake = tools
    context = _context()
    preview = parameters.preview_parameter_update(
        TARGET, json.dumps({"log_level": "DEBUG"}), context
    )
    fake.create_version("home-project", TARGET, "someone-else", json.dumps(LIVE))
    fake.created.clear()

    result = parameters.apply_parameter_update(preview["change_id"], context)

    assert result["status"] == "stale"
    assert fake.created == []


def test_instruction_change_is_diffed_and_carries_the_release_note(tools):
    parameters, _ = tools
    context = _context()
    preview = parameters.preview_parameter_update(
        TARGET, json.dumps({"instruction": "Line one.\nLine 2, edited."}), context
    )

    [change] = preview["changes"]
    assert change["field"] == "instruction"
    assert "-Line two." in change["diff"]
    assert "+Line 2, edited." in change["diff"]
    applied = parameters.apply_parameter_update(preview["change_id"], context)
    assert "prompt.md" in applied["note"]


@pytest.mark.parametrize(
    ("changes", "status"),
    [
        ({"config_revision": "mine"}, "refused"),
        ({"managed_project": "elsewhere"}, "refused"),
        ({"instruction": "__REF__(//secretmanager.googleapis.com/x)"}, "refused"),
        ({"max_attempts": 99}, "needs_correction"),
        ({"unknown_field": 1}, "needs_correction"),
        ({"model": ""}, "needs_correction"),
        ({}, "needs_correction"),
    ],
)
def test_invalid_or_protected_changes_are_never_staged(tools, changes, status):
    parameters, fake = tools
    context = _context()

    result = parameters.preview_parameter_update(TARGET, json.dumps(changes), context)

    assert result["status"] == status
    assert context.state == {}
    assert fake.created == []


def test_unparsable_changes_ask_for_correction(tools):
    parameters, _ = tools
    result = parameters.preview_parameter_update(TARGET, "model=pro", _context())
    assert result["status"] == "needs_correction"


def test_it_will_not_edit_its_own_parameter(tools):
    parameters, _ = tools
    result = parameters.preview_parameter_update(OWN, json.dumps({"model": "x"}), _context())
    assert result["status"] == "refused"

    listed = {p["parameter"]: p for p in parameters.list_runtime_parameters()["parameters"]}
    assert listed[OWN]["editable"] is False
    assert listed[TARGET]["editable"] is True
    assert listed["not-a-config"]["runtime_config"] is False


def test_non_runtime_config_parameters_are_not_edited(tools):
    parameters, _ = tools
    result = parameters.preview_parameter_update(
        "not-a-config", json.dumps({"model": "x"}), _context()
    )
    assert result["status"] == "refused"


def test_unchanged_values_publish_nothing(tools):
    parameters, _ = tools
    context = _context()
    result = parameters.preview_parameter_update(
        TARGET, json.dumps({"model": LIVE["model"]}), context
    )
    assert result["status"] == "no_change"
    assert context.state == {}


def test_written_payload_omits_unset_optional_fields(tools):
    """Runtimes deployed before a field existed reject it (extra="forbid"), so a
    null managed_project in someone else's payload would stop them loading."""
    parameters, fake = tools
    context = _context()
    preview = parameters.preview_parameter_update(TARGET, json.dumps({"model": "m2"}), context)
    parameters.apply_parameter_update(preview["change_id"], context)

    written = json.loads(fake.created[0][3])
    assert "managed_project" not in written
    assert "agent_identity_bucket_name" not in written


def test_managed_project_redirects_every_call(tools, monkeypatch):
    parameters, fake = tools
    monkeypatch.setenv("MANAGED_PROJECT", "other-project")
    reset_runtime_config_for_tests()

    parameters.list_runtime_parameters()

    assert set(fake.projects) == {"other-project"}


def test_api_errors_are_returned_rather_than_raised(tools, monkeypatch):
    parameters, fake = tools

    def denied(*_args, **_kwargs):
        raise exceptions.PermissionDenied("no access")

    monkeypatch.setattr(fake, "render", denied)
    result = parameters.preview_parameter_update(TARGET, json.dumps({"model": "x"}), _context())

    assert result["status"] == "error"
    assert result["error_type"] == "PermissionDenied"


def test_identity_is_granted_no_role_that_can_rewrite_history():
    import registry

    spec = registry.AGENTS["parameter_updater"]
    assert set(spec.agent_identity_project_roles) == {
        "roles/parametermanager.parameterViewer",
        "roles/parametermanager.parameterVersionAdder",
    }
    assert not spec.uses_delegated_auth
