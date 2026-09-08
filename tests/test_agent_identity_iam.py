from __future__ import annotations

import importlib
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, call

import pytest

DEV = Path(__file__).resolve().parents[1] / "dev"
sys.path.insert(0, str(DEV))
agent_iam = importlib.import_module("iam.apply_agent_identity_iam")
common = importlib.import_module("common")
sys.path.remove(str(DEV))

SPEC = common.AGENTS["auth_reference_agent"]
RESOURCE_NAME = "projects/123456789/locations/us-central1/reasoningEngines/engine-123"
PRINCIPAL = (
    "principal://agents.global.org-999.system.id.goog/resources/aiplatform/"
    "projects/123456789/locations/us-central1/reasoningEngines/engine-123"
)


@pytest.fixture(autouse=True)
def clear_agent_identity_environment(monkeypatch):
    for name in (
        agent_iam.agent_identity_id_env(SPEC),
        agent_iam.agent_identity_project_roles_env(SPEC),
        agent_iam.agent_identity_storage_bucket_roles_env(SPEC),
    ):
        monkeypatch.delenv(name, raising=False)


def test_agent_identity_environment_names_are_parameterized():
    assert agent_iam.agent_identity_id_env(SPEC) == "AUTH_REFERENCE_AGENT_AGENT_IDENTITY_ID"
    assert (
        agent_iam.agent_identity_project_roles_env(SPEC)
        == "AUTH_REFERENCE_AGENT_AGENT_IDENTITY_PROJECT_ROLES"
    )
    assert (
        agent_iam.agent_identity_storage_bucket_roles_env(SPEC)
        == "AUTH_REFERENCE_AGENT_AGENT_IDENTITY_STORAGE_BUCKET_ROLES"
    )


def test_no_agent_specific_configuration_skips_iam(monkeypatch):
    run = Mock()
    monkeypatch.setattr(agent_iam, "_run_gcloud", run)

    result = agent_iam.apply_agent_identity_iam(
        "auth_reference_agent",
        "test-project",
        RESOURCE_NAME,
        SPEC,
    )

    assert result is None
    run.assert_not_called()


def test_project_roles_are_deduplicated_and_validated(monkeypatch):
    monkeypatch.setenv(
        agent_iam.agent_identity_project_roles_env(SPEC),
        "roles/storage.objectViewer, roles/storage.objectViewer,roles/logging.logWriter",
    )

    assert agent_iam.requested_project_roles(SPEC) == (
        "roles/storage.objectViewer",
        "roles/logging.logWriter",
    )

    monkeypatch.setenv(
        agent_iam.agent_identity_project_roles_env(SPEC),
        "roles/owner",
    )
    with pytest.raises(SystemExit, match="broad basic IAM role"):
        agent_iam.requested_project_roles(SPEC)


def test_storage_bucket_bindings_are_resource_scoped(monkeypatch):
    monkeypatch.setenv(
        agent_iam.agent_identity_storage_bucket_roles_env(SPEC),
        (
            "gs://one=roles/storage.objectViewer|roles/storage.objectCreator;"
            "gs://two=roles/storage.objectViewer"
        ),
    )

    assert agent_iam.requested_storage_bucket_roles(SPEC) == {
        "gs://one": (
            "roles/storage.objectViewer",
            "roles/storage.objectCreator",
        ),
        "gs://two": ("roles/storage.objectViewer",),
    }


def test_agent_identity_principal_uses_organization_trust_domain(monkeypatch):
    def run(args):
        if args[:2] == ("projects", "describe"):
            return SimpleNamespace(stdout="123456789\n")
        if args[:2] == ("projects", "get-ancestors"):
            return SimpleNamespace(stdout="project,123456789\nfolder,555\norganization,999\n")
        raise AssertionError(args)

    monkeypatch.setattr(agent_iam, "_run_gcloud", run)
    client = Mock()
    client.agent_engines.get.return_value.api_resource.spec = SimpleNamespace(
        identity_type="AGENT_IDENTITY", effective_identity=PRINCIPAL
    )
    monkeypatch.setattr(agent_iam.vertexai, "Client", Mock(return_value=client))

    assert agent_iam.agent_identity_principal("test-project", RESOURCE_NAME) == PRINCIPAL


def test_agent_identity_principal_uses_orgless_trust_domain(monkeypatch):
    def run(args):
        if args[:2] == ("projects", "describe"):
            return SimpleNamespace(stdout="123456789\n")
        if args[:2] == ("projects", "get-ancestors"):
            return SimpleNamespace(stdout="project,123456789\n")
        raise AssertionError(args)

    monkeypatch.setattr(agent_iam, "_run_gcloud", run)
    client = Mock()
    client.agent_engines.get.return_value.api_resource.spec = SimpleNamespace(
        identity_type="AGENT_IDENTITY",
        effective_identity=PRINCIPAL.replace("org-999", "proj-123456789"),
    )
    monkeypatch.setattr(agent_iam.vertexai, "Client", Mock(return_value=client))

    assert agent_iam.agent_identity_principal("test-project", RESOURCE_NAME).startswith(
        "principal://agents.global.proj-123456789.system.id.goog/"
    )


def test_apply_agent_identity_iam_targets_exact_principal(monkeypatch):
    monkeypatch.setenv(
        agent_iam.agent_identity_project_roles_env(SPEC),
        "roles/logging.logWriter",
    )
    monkeypatch.setenv(
        agent_iam.agent_identity_storage_bucket_roles_env(SPEC),
        "gs://agent-bucket=roles/storage.objectViewer",
    )
    monkeypatch.setattr(
        agent_iam,
        "agent_identity_principal",
        lambda project_id, resource_name: PRINCIPAL,
    )
    run = Mock(return_value=SimpleNamespace(stdout=""))
    monkeypatch.setattr(agent_iam, "_run_gcloud", run)

    result = agent_iam.apply_agent_identity_iam(
        "auth_reference_agent",
        "test-project",
        RESOURCE_NAME,
        SPEC,
    )

    assert result == PRINCIPAL
    assert run.call_args_list == [
        call(
            (
                "projects",
                "add-iam-policy-binding",
                "test-project",
                f"--member={PRINCIPAL}",
                "--role=roles/logging.logWriter",
                "--condition=None",
                "--quiet",
            )
        ),
        call(
            (
                "storage",
                "buckets",
                "add-iam-policy-binding",
                "gs://agent-bucket",
                f"--member={PRINCIPAL}",
                "--role=roles/storage.objectViewer",
                "--condition=None",
                "--project=test-project",
                "--quiet",
            )
        ),
    ]


def test_configured_identity_is_an_assertion_not_an_override(monkeypatch):
    monkeypatch.setenv(
        agent_iam.agent_identity_id_env(SPEC),
        "principal://wrong",
    )
    monkeypatch.setattr(
        agent_iam,
        "agent_identity_principal",
        lambda project_id, resource_name: PRINCIPAL,
    )

    with pytest.raises(SystemExit, match="does not match"):
        agent_iam.apply_agent_identity_iam(
            "auth_reference_agent",
            "test-project",
            RESOURCE_NAME,
            SPEC,
        )


@pytest.mark.parametrize("role", sorted(agent_iam.UNSUPPORTED_BUCKET_ROLES))
def test_legacy_bucket_roles_are_rejected(role):
    with pytest.raises(SystemExit, match="does not support"):
        agent_iam._validate_role(role)


def test_identity_lookup_rejects_cross_project_runtime(monkeypatch):
    monkeypatch.setattr(agent_iam, "_project_number", lambda _: "987654321")
    client = Mock()
    monkeypatch.setattr(agent_iam.vertexai, "Client", client)
    with pytest.raises(SystemExit, match="different project"):
        agent_iam.agent_identity_principal("other-project", RESOURCE_NAME)
    client.assert_not_called()


@pytest.mark.parametrize(
    "identity_type, principal",
    [
        ("SERVICE_ACCOUNT", "runtime@example.iam.gserviceaccount.com"),
        ("AGENT_IDENTITY", ""),
        ("AGENT_IDENTITY", PRINCIPAL.replace("engine-123", "another-engine")),
    ],
)
def test_identity_lookup_rejects_wrong_effective_identity(monkeypatch, identity_type, principal):
    monkeypatch.setattr(agent_iam, "_project_number", lambda _: "123456789")
    client = Mock()
    client.agent_engines.get.return_value.api_resource.spec = SimpleNamespace(
        identity_type=identity_type, effective_identity=principal
    )
    monkeypatch.setattr(agent_iam.vertexai, "Client", Mock(return_value=client))
    with pytest.raises(SystemExit, match="no matching Agent Identity"):
        agent_iam.agent_identity_principal("test-project", RESOURCE_NAME)
