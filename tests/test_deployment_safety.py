"""Regression coverage for deployment scope, source parity and API pagination."""

import json
import sys
import tarfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from urllib.parse import parse_qs, urlsplit

import pytest
import release_dev
from config import bootstrap
from conftest import requires_symlinks
from deploy import package_agent, runtime, sources, state, update_dev
from deploy.dependencies import export_requirements
from gemini_shared.config.runtime_config import RuntimeConfig
from iam import apply_agent_identity_iam as iam
from register import api_http as http
from register import register_agent
from registry import AGENTS

RESOURCE = "projects/123/locations/us-central1/reasoningEngines/engine"
SPEC = AGENTS["basic_assistant"]


@pytest.fixture
def scoped_state(monkeypatch, tmp_path):
    monkeypatch.setattr(state, "STATE_DIR", tmp_path)
    monkeypatch.setattr(
        state,
        "project_number",
        lambda name: {"test-project": "123", "other-project": "456"}.get(name, name),
    )
    return tmp_path


def test_saved_state_is_scoped_to_project_and_region(scoped_state):
    state.save_state("basic_assistant", RESOURCE, "test-project", "us-central1")
    assert state.load_resource_name("basic_assistant", "123", "us-central1") == RESOURCE
    assert state.find_resource_name("basic_assistant", "other-project", "us-central1") is None
    assert state.find_resource_name("basic_assistant", "test-project", "europe-west1") is None


def test_legacy_state_only_migrates_into_its_own_scope(scoped_state):
    legacy = scoped_state / "basic_assistant.json"
    legacy.write_text(json.dumps({"agent": "basic_assistant", "reasoning_engine": RESOURCE}))
    assert state.find_resource_name("basic_assistant", "other-project", "us-central1") is None
    assert state.load_resource_name("basic_assistant", "test-project", "us-central1") == RESOURCE
    assert state.state_path("basic_assistant", "123", "us-central1").exists()
    assert legacy.exists()


@pytest.mark.parametrize("target", ["other-project", "test-project"])
def test_wrong_runtime_is_rejected_before_update_client(monkeypatch, scoped_state, target):
    location = "us-central1" if target == "other-project" else "europe-west1"
    monkeypatch.setenv("DEV_REASONING_ENGINE", RESOURCE)
    client = Mock()
    monkeypatch.setattr(update_dev, "build_client", client)
    with pytest.raises(SystemExit, match="different project or region"):
        update_dev.update_agent("basic_assistant", target, location, "gs://staging", SPEC)
    client.assert_not_called()


def test_release_rejects_wrong_scope_before_preflight(monkeypatch, scoped_state):
    monkeypatch.setattr(sys, "argv", ["release_dev.py", "--agent", "basic_assistant"])
    monkeypatch.setattr(release_dev, "load_environment", lambda _: None)
    monkeypatch.setattr(
        release_dev,
        "require_dev_environment",
        lambda **kwargs: ("other-project", "us-central1", "gs://staging"),
    )
    monkeypatch.setenv("DEV_REASONING_ENGINE", RESOURCE)
    preflight = Mock()
    monkeypatch.setattr(release_dev, "ensure_dev_prerequisites", preflight)
    with pytest.raises(SystemExit, match="different project or region"):
        release_dev.main()
    preflight.assert_not_called()


def test_release_resolves_saved_state_after_new_project_preflight(monkeypatch, tmp_path):
    monkeypatch.setattr(
        sys, "argv", ["release_dev.py", "--agent", "basic_assistant", "--skip-register"]
    )
    monkeypatch.setattr(release_dev, "load_environment", lambda _: None)
    monkeypatch.setattr(
        release_dev,
        "require_dev_environment",
        lambda **kwargs: ("new-project", "us-central1", "gs://staging"),
    )
    preflight = Mock()
    monkeypatch.setattr(release_dev, "ensure_dev_prerequisites", preflight)

    def lookup(*args):
        preflight.assert_called_once()
        return None

    from deploy import deploy_dev

    deploy = Mock(return_value=RESOURCE)
    monkeypatch.setattr(release_dev, "find_resource_name", lookup)
    monkeypatch.setattr(
        release_dev, "package_agent", Mock(return_value=tmp_path / "archive.tar.gz")
    )
    monkeypatch.setattr(deploy_dev, "deploy_agent", deploy)
    release_dev.main()
    deploy.assert_called_once()


@requires_symlinks
@pytest.mark.parametrize("kind", ["file", "directory", "parent"])
def test_archive_and_sdk_staging_reject_the_same_symlinks(monkeypatch, tmp_path, kind):
    source = tmp_path / "src" / "agent"
    source.mkdir(parents=True)
    external = tmp_path / "external"
    external.mkdir()
    (external / "private.txt").write_text("must not be packaged")
    if kind == "parent":
        (tmp_path / "linked").symlink_to(source.parent, target_is_directory=True)
        relative = "linked/agent"
    else:
        target = external if kind == "directory" else external / "private.txt"
        (source / "linked").symlink_to(target, target_is_directory=kind == "directory")
        relative = "src/agent"
    spec = SimpleNamespace(extra_packages=(relative,))
    monkeypatch.setattr(sources, "ROOT", tmp_path)
    monkeypatch.setattr(package_agent, "get_agent_spec", lambda _: spec)
    with pytest.raises(ValueError, match="symbolic links"):
        package_agent.package_agent("agent", tmp_path / "out.tar.gz")
    with pytest.raises(ValueError, match="symbolic links"), sources.staged_extra_packages(spec):
        pytest.fail("Unsafe sources were staged")
    assert not (tmp_path / "out.tar.gz").exists()


def test_archive_and_sdk_staging_have_identical_sources(monkeypatch, tmp_path):
    # Written and asserted as bytes: text mode rewrites newlines on Windows, so
    # a hardcoded "\n" would disagree with the file on disk even though the
    # archive and the staged copy match each other, which is what is under test.
    contents = b"value = 1\n"
    source = tmp_path / "src" / "agent"
    source.mkdir(parents=True)
    (source / "agent.py").write_bytes(contents)
    (source / "cache.pyc").write_bytes(b"bytecode")
    (source / "__pycache__").mkdir()
    (source / "__pycache__/agent.pyc").write_bytes(b"cached")
    spec = SimpleNamespace(extra_packages=("src/agent",))
    monkeypatch.setattr(sources, "ROOT", tmp_path)
    monkeypatch.setattr(package_agent, "get_agent_spec", lambda _: spec)
    monkeypatch.setattr(package_agent, "export_requirements", lambda _: ("test==1",))
    archive_path = package_agent.package_agent("agent", tmp_path / "out.tar.gz")
    with tarfile.open(archive_path) as archive:
        archived = {
            entry.name: archive.extractfile(entry).read()
            for entry in archive
            if entry.isfile() and entry.name != "requirements.txt"
        }
    original_cwd = Path.cwd()
    with sources.staged_extra_packages(spec) as roots:
        staged = {
            path.as_posix(): path.read_bytes()
            for root in roots
            for path in Path(root).rglob("*")
            if path.is_file()
        }
    assert Path.cwd() == original_cwd
    assert archived == staged == {"agent/agent.py": contents}


def test_every_agent_stages_under_its_own_prefix():
    """Two agents sharing one prefix overwrite each other's pickle.

    The SDK stages every deployment under a single ``agent_engine/`` directory
    unless told otherwise, so the last agent deployed was served for all of
    them. Each spec must resolve to a distinct directory, and none may be the
    bare default.
    """
    prefixes = {name: runtime.staging_prefix(spec) for name, spec in AGENTS.items()}
    assert len(set(prefixes.values())) == len(AGENTS), prefixes
    assert all(prefix != runtime._STAGING_ROOT for prefix in prefixes.values())


def test_deployment_config_carries_the_scoped_prefix(monkeypatch):
    """A dropped key silently reverts to the shared default."""
    monkeypatch.setattr(runtime, "export_requirements", lambda _: ("test==1",))
    config = runtime.deployment_config(SPEC, "gs://staging", ())
    assert config["gcs_dir_name"] == runtime.staging_prefix(SPEC)
    assert config["staging_bucket"] == "gs://staging"


@pytest.mark.parametrize("name", sorted(AGENTS))
def test_runtime_dependencies_are_exported_from_lock(name):
    requirements = export_requirements(AGENTS[name])
    assert "google-adk==2.7.1" in requirements
    assert "google-cloud-agentidentitycredentials==0.1.1" in requirements
    assert not any(
        line.startswith(("-e ", "file:", "gemini-shared", "recipe-cards")) for line in requirements
    )
    assert all("==" in line for line in requirements)


def test_restoring_prompt_keeps_settings_and_publishes_a_fresh_version(monkeypatch):
    client = Mock()
    published = {}

    def create_version(**kwargs):
        version = kwargs["parameter_version_id"]
        assert version not in published, "Parameter Manager version IDs cannot be reused"
        published[version] = json.loads(kwargs["parameter_version"].payload.data)

    client.create_parameter_version.side_effect = create_version
    monkeypatch.setattr(bootstrap, "_parameter_client", lambda _: client)
    current = RuntimeConfig(
        config_revision="initial", model="test-model", instruction="A", environment="dev"
    )
    for prompt in ("B", "C", "B"):
        bootstrap._publish_instruction("test-project", "config", "global", current, prompt)
        current = RuntimeConfig(**list(published.values())[-1])
    assert len(published) == 3
    assert current.instruction == "B"
    assert current.model == "test-model"
    assert current.environment == "dev"


def test_registration_updates_an_agent_found_on_the_second_page(monkeypatch):
    pages = Mock(
        side_effect=[
            {"agents": [{"displayName": "Unrelated"}], "nextPageToken": "next/+="},
            {
                "agents": [
                    {"displayName": SPEC.display_name, "name": "projects/123/agents/existing"}
                ]
            },
        ]
    )
    monkeypatch.setattr(http, "request", pages)
    write = Mock(return_value={"name": "projects/123/agents/existing"})
    monkeypatch.setattr(register_agent, "_request", write)
    register_agent.register_agent("basic_assistant", "app", "test-project", SPEC, RESOURCE)
    assert write.call_args.args[0] == "PATCH"
    assert write.call_args.args[1].endswith("/agents/existing")
    assert parse_qs(urlsplit(pages.call_args.args[1]).query)["pageToken"] == ["next/+="]


def test_authorization_on_second_page_is_reused(monkeypatch):
    monkeypatch.setattr(
        http,
        "request",
        Mock(
            side_effect=[
                {"nextPageToken": "next"},
                {"authorizations": [{"name": "projects/123/authorizations/auth"}]},
            ]
        ),
    )
    secret = Mock()
    monkeypatch.setattr(register_agent, "_resolve_client_secret", secret)
    register_agent.ensure_authorization(
        "test-project", "auth", "auth_reference_agent", AGENTS["auth_reference_agent"]
    )
    secret.assert_not_called()


def test_pagination_preserves_filters_and_stops_repeated_tokens(monkeypatch):
    request = Mock(return_value={"nextPageToken": "same"})
    monkeypatch.setattr(http, "request", request)
    with pytest.raises(RuntimeError, match="continuation token"):
        list(http.iter_resources("https://example.test/agents?pageSize=100", "test", "agents"))
    assert request.call_count == 2
    assert parse_qs(urlsplit(request.call_args.args[1]).query) == {
        "pageSize": ["100"],
        "pageToken": ["same"],
    }


def test_baseline_storage_access_is_limited_to_the_staging_bucket(monkeypatch):
    monkeypatch.setenv("DEV_GRANT_AGENT_IDENTITY_BASELINE", "true")
    monkeypatch.setattr(iam, "agent_identity_principal_set", lambda _: "principalSet://test")
    commands = Mock()
    monkeypatch.setattr(iam, "_run_gcloud", commands)
    iam.ensure_baseline_roles("test-project", "gs://staging")
    calls = [call.args[0] for call in commands.call_args_list]
    storage = [args for args in calls if "--role=roles/storage.objectViewer" in args]
    assert len(storage) == 1
    assert storage[0][:4] == ("storage", "buckets", "add-iam-policy-binding", "gs://staging")
    assert all(
        "--role=roles/storage.objectViewer" not in args for args in calls if args[0] == "projects"
    )
