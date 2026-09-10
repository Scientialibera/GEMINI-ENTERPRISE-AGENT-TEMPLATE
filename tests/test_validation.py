from __future__ import annotations

import asyncio
import datetime
import decimal
import importlib
import json
import logging
import os
import re
import secrets
import sys
import tarfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from gemini_shared.config.bootstrap import get_bootstrap_settings
from gemini_shared.config.runtime_config import RuntimeConfig, RuntimeConfigStore
from google.adk.auth.auth_credential import (
    AuthCredential,
    AuthCredentialTypes,
    OAuth2Auth,
)
from google.api_core.exceptions import NotFound
from google.cloud import bigquery

DEV = Path(__file__).resolve().parents[1] / "dev"
sys.path.insert(0, str(DEV))
bootstrap = importlib.import_module("config.bootstrap")
fixture = importlib.import_module("fixtures.bigquery_fixture")
registry = importlib.import_module("registry")
settings = importlib.import_module("config.settings")
sources = importlib.import_module("deploy.sources")
packaging = importlib.import_module("deploy.package_agent")
sys.path.remove(str(DEV))

# Cover newly registered agents automatically.
ALL_ENTRIES = sorted(registry.AGENTS)
# A workflow is deployed exactly like an agent but is composed rather than
# conversational: it has stages instead of tools, and each stage carries its own
# instruction rather than reading one from Parameter Manager. The checks that
# describe a conversational agent therefore run over the agents only.
ALL_AGENTS = [name for name in ALL_ENTRIES if registry.AGENTS[name].source_root == "agents"]
ALL_WORKFLOWS = [name for name in ALL_ENTRIES if registry.AGENTS[name].source_root == "workflows"]


@pytest.fixture(autouse=True)
def environment(monkeypatch):
    for name in list(os.environ):
        if name.startswith(("DEV_", "CONFIG_", "GEMINI_", "GOOGLE_CLOUD_")):
            monkeypatch.delenv(name)
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "test-project")
    monkeypatch.setenv("GEMINI_MODEL", "test-model")
    monkeypatch.setenv("AGENT_INSTRUCTION", "Test instruction")
    monkeypatch.setenv("GEMINI_ENTERPRISE_AUTHORIZATION_ID", "unit-test-authorization")


@pytest.mark.parametrize("environment", ["", "qa", "prod"])
def test_remote_boundary(monkeypatch, environment):
    monkeypatch.setenv("ENVIRONMENT", environment)
    with pytest.raises(SystemExit, match="Refusing remote"):
        settings.require_dev_environment()


def test_required_placeholder(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "REPLACE_WITH_PROJECT")
    with pytest.raises(RuntimeError, match="placeholder"):
        get_bootstrap_settings()


def test_project_creation_controls(monkeypatch):
    run = Mock()
    monkeypatch.setattr(bootstrap, "_run", run)
    monkeypatch.setattr(bootstrap, "_exists", lambda args: False)
    with pytest.raises(SystemExit, match="does not exist"):
        bootstrap.ensure_project("missing-project")
    run.assert_not_called()
    monkeypatch.setenv("DEV_CREATE_PROJECT_IF_MISSING", "true")
    with pytest.raises(SystemExit, match="DEV_BILLING_ACCOUNT_ID"):
        bootstrap.ensure_project("missing-project")
    monkeypatch.setenv("DEV_BILLING_ACCOUNT_ID", "test-billing")
    monkeypatch.setenv("DEV_PROJECT_FOLDER_ID", "123")
    monkeypatch.setenv("DEV_PROJECT_ORGANIZATION_ID", "456")
    with pytest.raises(SystemExit, match="at most one"):
        bootstrap.ensure_project("missing-project")
    run.assert_not_called()
    monkeypatch.delenv("DEV_PROJECT_ORGANIZATION_ID")
    bootstrap.ensure_project("missing-project")
    assert run.call_count == 2
    assert "--folder=123" in run.call_args_list[0].args[0]


def test_existing_project_and_bucket_are_reused(monkeypatch):
    run = Mock()
    monkeypatch.setattr(bootstrap, "_run", run)
    monkeypatch.setattr(bootstrap, "_exists", lambda args: True)
    bootstrap.ensure_project("test-project")
    bootstrap.ensure_staging_bucket("test-project", "us-central1", "gs://test-bucket")
    run.assert_not_called()


def test_missing_bucket_controls(monkeypatch):
    run = Mock()
    monkeypatch.setattr(bootstrap, "_run", run)
    monkeypatch.setattr(bootstrap, "_exists", lambda args: False)
    monkeypatch.setenv("DEV_CREATE_STAGING_BUCKET_IF_MISSING", "false")
    with pytest.raises(SystemExit, match="missing"):
        bootstrap.ensure_staging_bucket("test-project", "us-central1", "gs://test-bucket")
    run.assert_not_called()
    monkeypatch.setenv("DEV_CREATE_STAGING_BUCKET_IF_MISSING", "true")
    bootstrap.ensure_staging_bucket("test-project", "us-central1", "gs://test-bucket")
    assert "--uniform-bucket-level-access" in run.call_args.args[0]


def test_only_missing_services_enabled(monkeypatch):
    run = Mock(return_value=SimpleNamespace(stdout="\n".join(bootstrap.REQUIRED_DEV_SERVICES)))
    monkeypatch.setattr(bootstrap, "_run", run)
    bootstrap.ensure_required_services("test-project")
    assert run.call_count == 1
    bootstrap.ensure_required_services("test-project", (fixture.BIGQUERY_API_SERVICE,))
    assert run.call_args.args[0][2] == fixture.BIGQUERY_API_SERVICE
    monkeypatch.setenv("DEV_ENABLE_REQUIRED_APIS", "false")
    with pytest.raises(SystemExit, match="Required APIs are disabled"):
        bootstrap.ensure_required_services("test-project", (fixture.BIGQUERY_API_SERVICE,))


@pytest.mark.parametrize("agent", ALL_ENTRIES)
def test_packaging_excludes_cache_and_other_agent(tmp_path, monkeypatch, agent):
    source = tmp_path / agent
    source.mkdir()
    (source / "agent.py").write_text("x = 1\n")
    cache = source / "__pycache__"
    cache.mkdir()
    (cache / "agent.pyc").write_bytes(b"first")
    spec = SimpleNamespace(extra_packages=(agent,))
    monkeypatch.setattr(sources, "ROOT", tmp_path)
    monkeypatch.setattr(packaging, "export_requirements", lambda _: ("test==1",))
    monkeypatch.setattr(packaging, "ROOT", tmp_path)
    monkeypatch.setattr(packaging, "get_agent_spec", lambda name: spec)
    first = packaging.package_agent(agent, tmp_path / "one.tar.gz").read_bytes()
    (cache / "agent.pyc").write_bytes(b"changed cache")
    second = packaging.package_agent(agent, tmp_path / "different" / "two.tar.gz")
    assert first == second.read_bytes()
    with tarfile.open(second) as archive:
        assert set(archive.getnames()) == {"requirements.txt", agent, f"{agent}/agent.py"}


def test_fixture_creation_reuse_and_schema_guard(monkeypatch):
    client = Mock()
    monkeypatch.setattr(fixture.bigquery, "Client", lambda **kwargs: client)
    table = bigquery.Table("test-project.test_dataset.test_table", schema=fixture.FIXTURE_SCHEMA)
    client.get_dataset.side_effect = NotFound("missing")
    client.get_table.side_effect = NotFound("missing")
    client.create_table.return_value = table
    client.list_rows.return_value = []
    client.insert_rows_json.return_value = []
    result = fixture.prepare_bigquery_fixture("test-project", "us-central1")
    assert result.created_dataset and result.created_table and result.seeded_rows == 5
    client.reset_mock()
    client.get_dataset.side_effect = None
    client.get_table.side_effect = None
    client.get_table.return_value = table
    client.list_rows.return_value = [{"order_id": "existing"}]
    result = fixture.prepare_bigquery_fixture("test-project", "us-central1")
    assert not result.created_dataset and not result.created_table and result.seeded_rows == 0
    client.create_table.assert_not_called()
    client.insert_rows_json.assert_not_called()
    table.schema = [bigquery.SchemaField("wrong", "STRING")]
    with pytest.raises(SystemExit, match="different schema"):
        fixture.prepare_bigquery_fixture("test-project", "us-central1")
    client.insert_rows_json.assert_not_called()


def test_fixture_missing_creation_disabled(monkeypatch):
    client = Mock()
    monkeypatch.setattr(fixture.bigquery, "Client", lambda **kwargs: client)
    monkeypatch.setenv("DEV_CREATE_BIGQUERY_FIXTURE_IF_MISSING", "false")
    client.get_dataset.side_effect = NotFound("missing")
    with pytest.raises(SystemExit, match=r"dataset.*missing"):
        fixture.prepare_bigquery_fixture("test-project", "us-central1")
    client.create_dataset.assert_not_called()
    client.get_dataset.side_effect = None
    client.get_table.side_effect = NotFound("missing")
    with pytest.raises(SystemExit, match=r"table.*missing"):
        fixture.prepare_bigquery_fixture("test-project", "us-central1")
    client.create_table.assert_not_called()


def test_runtime_ttl_reload_and_last_good(monkeypatch, caplog):
    monkeypatch.setenv("CONFIG_PARAMETER", "test-parameter")
    monkeypatch.setenv("CONFIG_REFRESH_SECONDS", "5")
    clock = [0.0]
    monkeypatch.setattr("gemini_shared.config.runtime_config.time.monotonic", lambda: clock[0])
    store = RuntimeConfigStore()
    one = RuntimeConfig(config_revision="one", model="model-one", instruction="test")
    two = one.model_copy(update={"config_revision": "two", "log_level": "ERROR"})
    load = Mock(side_effect=[one, two, ValueError("payload-that-must-not-be-logged")])
    monkeypatch.setattr(store, "_load_remote", load)
    assert store.get() == one
    assert store.get() == one
    assert load.call_count == 1
    assert load.call_args.args[0].endswith("/versions/latest")
    clock[0] = 6
    assert store.get() == two
    assert logging.getLogger().level == logging.ERROR
    clock[0] = 12
    assert store.get() == two
    assert "payload-that-must-not-be-logged" not in caplog.text


def test_nested_bigquery_serialization_and_delegated_client(monkeypatch):
    module = importlib.import_module("auth_reference_agent.tools.bigquery_query")
    value = {"nested": [{"date": datetime.date(2026, 1, 1), "amount": decimal.Decimal("2.5")}]}
    assert json.loads(json.dumps(module._json_safe(value)))["nested"][0]["date"] == "2026-01-01"
    client = Mock()
    monkeypatch.setattr(module.bigquery, "Client", client)
    credential = AuthCredential(
        auth_type=AuthCredentialTypes.OAUTH2,
        oauth2=OAuth2Auth(access_token=secrets.token_urlsafe(16)),
    )
    module._delegated_client(credential)
    assert isinstance(client.call_args.kwargs["credentials"], module.OAuth2Credentials)
    client.return_value.query.return_value.result.return_value = [
        {"amount": decimal.Decimal("2.5")}
    ]
    result = asyncio.run(module.query_bigquery(credential, "SELECT 2.5 AS amount"))
    assert result["rows"] == [{"amount": 2.5}]
    client.return_value.query.return_value.result.assert_called_once_with(max_results=100)


def test_model_callback(monkeypatch):
    """All agents use the shared model callback."""
    from gemini_shared import apply_runtime_model

    request = SimpleNamespace(model="old")
    apply_runtime_model(None, request)
    assert request.model == "test-model"

    for agent in ALL_AGENTS:
        module = importlib.import_module(f"{agent}.agent")
        assert module.root_agent.before_model_callback is apply_runtime_model


@pytest.mark.parametrize("agent", ALL_AGENTS)
def test_every_tool_is_described_to_the_model(agent):
    """Each local tool must expose a description to ADK."""
    from google.adk.tools.base_toolset import BaseToolset
    from google.adk.tools.function_tool import FunctionTool

    module = importlib.import_module(f"{agent}.agent")
    undescribed = []
    for tool in module.root_agent.tools:
        # Remote tool descriptions require a server connection.
        if isinstance(tool, BaseToolset):
            continue
        declaration = (
            tool._get_declaration()
            if hasattr(tool, "_get_declaration")
            else FunctionTool(tool)._get_declaration()
        )
        description = getattr(declaration, "description", None)
        if not (description and description.strip()):
            undescribed.append(getattr(declaration, "name", str(tool)))
    assert not undescribed, f"tools advertised to the model without a description: {undescribed}"


@pytest.mark.parametrize("agent", ALL_AGENTS)
def test_instruction_resolves_from_runtime_configuration(agent):
    """Each agent resolves its instruction through a callback."""
    module = importlib.import_module(f"{agent}.agent")
    assert callable(module.root_agent.instruction), (
        f"{agent} must resolve its instruction from runtime configuration"
    )


def test_delegated_scheme_rehydrates_from_shared_module():
    """ADK must rehydrate the shared scheme by its type_ default."""
    from google.adk.auth.auth_schemes import CustomAuthScheme
    from google.adk.auth.auth_tool import AuthConfig
    from google.adk.auth.credential_manager import CredentialManager

    importlib.import_module("gemini_shared.auth.delegated")

    deserialized = CustomAuthScheme.model_validate(
        {"type": "GeminiEnterpriseDelegatedAuthProviderScheme", "name": "unit-test-authorization"}
    )
    assert type(deserialized) is CustomAuthScheme

    manager = CredentialManager(auth_config=AuthConfig(auth_scheme=deserialized))
    token = secrets.token_urlsafe(16)
    session = SimpleNamespace(state={"unit-test-authorization": token})
    credential = asyncio.run(manager.get_auth_credential(SimpleNamespace(session=session)))
    assert credential.oauth2.access_token == token


def test_agent_identity_tooling_has_no_delegated_auth_prerequisite(monkeypatch):
    """Storage tooling imports without a delegated authorization ID."""
    monkeypatch.delenv("GEMINI_ENTERPRISE_AUTHORIZATION_ID", raising=False)
    module = importlib.reload(importlib.import_module("gemini_shared.connectors.cloud_storage"))
    assert callable(module.list_bucket_objects)


def test_mcp_headers_carry_the_signed_in_users_token():
    """MCP requests carry the current user's delegated token."""
    from gemini_shared.mcp.mcp_auth import delegated_bearer_headers

    token = secrets.token_urlsafe(16)
    provider = delegated_bearer_headers("unit-test-authorization")
    context = SimpleNamespace(state={"unit-test-authorization": token})
    assert provider(context) == {"Authorization": f"Bearer {token}"}


def test_mcp_headers_fail_loudly_without_a_token():
    """Missing tokens must fail before an MCP request."""
    from gemini_shared.mcp.mcp_auth import delegated_bearer_headers

    provider = delegated_bearer_headers("unit-test-authorization")
    context = SimpleNamespace(state={"other-a": "1", "other-b": "2"})
    with pytest.raises(ValueError, match="No delegated token"):
        provider(context)


def test_mcp_toolset_is_wired_to_a_remote_server():
    """The MCP agent uses HTTPS and excludes the write-capable SQL tool."""
    from gemini_shared.mcp.mcp_google_cloud import BIGQUERY_READONLY_TOOLS
    from google.adk.tools.mcp_tool.mcp_session_manager import StreamableHTTPConnectionParams

    module = importlib.import_module("bigquery_mcp_agent.tools.bigquery_mcp")
    params = module.bigquery_mcp_toolset._connection_params
    assert isinstance(params, StreamableHTTPConnectionParams)
    assert params.url.startswith("https://")
    # execute_sql would let the MCP path mutate data.
    assert "execute_sql" not in BIGQUERY_READONLY_TOOLS


@pytest.mark.parametrize("agent", ALL_ENTRIES)
def test_delegated_auth_detection_matches_the_spec(agent):
    """The source marker and declared auth requirements must agree."""
    spec = registry.get_agent_spec(agent)
    assert registry.detect_delegated_auth(spec) == spec.uses_delegated_auth


@pytest.mark.parametrize("agent", ALL_ENTRIES)
def test_delegated_agents_name_their_own_oauth_client(agent):
    """Delegated agents have distinct client, secret and authorization names."""
    spec = registry.get_agent_spec(agent)
    if not spec.uses_delegated_auth:
        return
    others = [s for name, s in registry.AGENTS.items() if name != agent and s.uses_delegated_auth]
    for other in others:
        assert spec.oauth_client_id_env != other.oauth_client_id_env
        assert spec.default_oauth_secret_name != other.default_oauth_secret_name
        assert spec.authorization_id != other.authorization_id


@pytest.mark.parametrize("agent", ALL_ENTRIES)
def test_oauth_scopes_cover_only_delegated_services(agent):
    """Each agent requests scopes only for its delegated tools."""
    spec = registry.get_agent_spec(agent)
    if not spec.uses_delegated_auth:
        assert spec.delegated_oauth_scopes == ()
        return
    assert spec.delegated_oauth_scopes, f"{agent} takes a user token but requests no scope"
    for scope in registry.IDENTITY_OAUTH_SCOPES:
        assert scope in spec.oauth_scopes
    # cloud-platform would grant far more than any one tool needs.
    assert registry.CLOUD_PLATFORM_SCOPE not in spec.delegated_oauth_scopes


@pytest.mark.parametrize("agent", ALL_AGENTS)
def test_every_agent_has_a_prompt(agent):
    """Each registered agent has a source prompt."""
    spec = registry.get_agent_spec(agent)
    prompt = spec.read_prompt()
    assert prompt, f"{agent} has no prompt.md at {spec.prompt_path}"
    assert len(prompt) > 40, f"{agent} prompt is too short to be a real instruction"


@pytest.mark.parametrize("agent", ALL_ENTRIES)
@pytest.mark.parametrize("already_deployed", [False, True])
def test_release_resolves_agent_defaults(monkeypatch, tmp_path, agent, already_deployed):
    monkeypatch.syspath_prepend(str(DEV))
    release = importlib.import_module("release_dev")
    deploy = importlib.import_module("deploy.deploy_dev")
    update = importlib.import_module("deploy.update_dev")
    spec = registry.get_agent_spec(agent)
    monkeypatch.setenv("ENVIRONMENT", "dev")
    monkeypatch.setenv("GOOGLE_CLOUD_LOCATION", "us-central1")
    monkeypatch.setenv("DEV_STAGING_BUCKET", "gs://test-bucket")
    monkeypatch.setenv("GEMINI_ENTERPRISE_APP_ID", "test-app")
    monkeypatch.delenv(settings.AUTHORIZATION_ID_ENV)
    monkeypatch.setattr(sys, "argv", ["release_dev.py", "--agent", agent])
    monkeypatch.setattr(release, "ROOT", tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(release, "load_environment", Mock())
    monkeypatch.setattr(release, "ensure_dev_prerequisites", Mock())
    monkeypatch.setattr(release, "package_agent", Mock(return_value=tmp_path / "agent.tar.gz"))
    monkeypatch.setattr(
        release,
        "find_resource_name",
        lambda *args: (
            "projects/123/locations/us-central1/reasoningEngines/test" if already_deployed else None
        ),
    )
    create = Mock(return_value="new-runtime")
    change = Mock(return_value="existing-runtime")
    register = Mock()
    monkeypatch.setattr(deploy, "deploy_agent", create)
    monkeypatch.setattr(update, "update_agent", change)
    monkeypatch.setattr(release, "register_agent", register)

    release.main()

    assert os.environ[settings.CONFIG_PARAMETER_ENV] == spec.config_parameter_id
    if spec.uses_delegated_auth:
        assert os.environ[settings.AUTHORIZATION_ID_ENV] == spec.authorization_id
    else:
        assert settings.AUTHORIZATION_ID_ENV not in os.environ
    called, unused = (change, create) if already_deployed else (create, change)
    called.assert_called_once_with(agent, "test-project", "us-central1", "gs://test-bucket", spec)
    unused.assert_not_called()
    register.assert_called_once_with(agent, "test-app", "test-project", spec, called.return_value)


def test_runtime_cache_is_scoped_to_parameter(monkeypatch):
    monkeypatch.setenv("CONFIG_PARAMETER", "first")
    store = RuntimeConfigStore()
    first = RuntimeConfig(config_revision="one", model="model-one", instruction="first")
    second = first.model_copy(update={"config_revision": "two", "instruction": "second"})
    load = Mock(side_effect=[first, second])
    monkeypatch.setattr(store, "_load_remote", load)
    assert store.get() == first

    monkeypatch.setenv("CONFIG_PARAMETER", "second")
    assert store.get() == second
    assert load.call_count == 2
    assert load.call_args.args[0].endswith("/parameters/second/versions/latest")


def test_runtime_cache_does_not_mask_new_parameter_failure(monkeypatch):
    monkeypatch.setenv("CONFIG_PARAMETER", "first")
    store = RuntimeConfigStore()
    config = RuntimeConfig(config_revision="one", model="model-one", instruction="first")
    monkeypatch.setattr(store, "_load_remote", Mock(side_effect=[config, ValueError("unreadable")]))
    assert store.get() == config

    monkeypatch.setenv("CONFIG_PARAMETER", "second")
    with pytest.raises(ValueError, match="unreadable"):
        store.get()


def test_runtime_status_resets_when_switching_to_local(monkeypatch):
    monkeypatch.setenv("CONFIG_PARAMETER", "remote")
    store = RuntimeConfigStore()
    config = RuntimeConfig(config_revision="remote", model="model-one", instruction="remote")
    monkeypatch.setattr(store, "_load_remote", Mock(return_value=config))
    assert store.status()["source"] == "Google Cloud Parameter Manager"

    monkeypatch.delenv("CONFIG_PARAMETER")
    status = store.status()
    assert status["source"] == "local environment"
    assert status["resource"] is None
    assert status["loaded_at"] is None
    assert status["config_revision"] == "local"


@pytest.mark.parametrize("raw", ["true", "1", " YES ", "on", "false", "0", " NO ", "off"])
def test_dev_boolean_parsing(monkeypatch, raw):
    from config.environment import env_bool

    monkeypatch.setenv("DEV_TEST_FLAG", raw)
    expected = raw.strip().lower() in {"true", "1", "yes", "on"}
    assert env_bool("DEV_TEST_FLAG", not expected) is expected


def test_dev_boolean_defaults_and_invalid_values(monkeypatch):
    from config.environment import env_bool

    assert env_bool("DEV_TEST_FLAG", True) is True
    assert env_bool("DEV_TEST_FLAG", False) is False
    for raw in ("", "perhaps"):
        monkeypatch.setenv("DEV_TEST_FLAG", raw)
        with pytest.raises(SystemExit, match="DEV_TEST_FLAG must be true or false"):
            env_bool("DEV_TEST_FLAG", False)


@pytest.mark.parametrize("raw", ["", " ", "REPLACE_WITH_ID", "<project>"])
def test_dev_placeholder_parsing(monkeypatch, raw):
    from config.environment import configured_value

    monkeypatch.setenv("DEV_TEST_VALUE", raw)
    assert configured_value("DEV_TEST_VALUE") == ""
    assert settings.is_missing_or_placeholder("DEV_TEST_VALUE")


def test_dev_configured_value_is_stripped(monkeypatch):
    from config.environment import configured_value

    monkeypatch.setenv("DEV_TEST_VALUE", " real-value ")
    assert configured_value("DEV_TEST_VALUE") == "real-value"
    assert not settings.is_missing_or_placeholder("DEV_TEST_VALUE")


@pytest.mark.parametrize("agent", ALL_AGENTS)
def test_config_status_tool_is_shared(agent):
    from gemini_shared.config.tools import report_runtime_config

    module = importlib.import_module(f"{agent}.tools.runtime_config_status")
    assert module.report_runtime_config is report_runtime_config


def test_ensure_bucket_tolerates_a_writer_only_identity(monkeypatch):
    """A least-privilege runtime holds object access on one bucket and nothing
    at the project level, so it cannot call storage.buckets.get. Treating that
    refusal as "missing" would send it on to create a bucket it cannot create,
    which is what failed the first deployed run."""
    from gemini_shared.connectors import cloud_storage
    from google.api_core import exceptions

    client = Mock()
    bucket = Mock()
    bucket.exists.side_effect = exceptions.Forbidden("storage.buckets.get denied")
    client.bucket.return_value = bucket
    monkeypatch.setattr(cloud_storage.storage, "Client", lambda **kwargs: client)

    assert cloud_storage.ensure_bucket("test-project", "test-bucket", "us-central1") is False
    client.create_bucket.assert_not_called()


def test_ensure_bucket_creates_a_missing_bucket(monkeypatch):
    from gemini_shared.connectors import cloud_storage

    client = Mock()
    bucket = Mock()
    bucket.exists.return_value = False
    client.bucket.return_value = bucket
    monkeypatch.setattr(cloud_storage.storage, "Client", lambda **kwargs: client)

    assert cloud_storage.ensure_bucket("test-project", "test-bucket", "us-central1") is True
    assert bucket.iam_configuration.uniform_bucket_level_access_enabled is True
    client.create_bucket.assert_called_once()


def test_concurrent_cards_for_one_dish_do_not_overwrite_each_other():
    """Two people asking for the same dish must not share a storage prefix.

    Without a per-run segment both requests write to <slug>/images/hero.png and
    the second silently replaces the first part-way through the card.
    """
    from recipe_cards.images import _object_name, new_run_id

    first, second = new_run_id(), new_run_id()
    assert first != second
    assert _object_name("beef-chili", first, "hero") != _object_name("beef-chili", second, "hero")
    # The dish still groups its runs together.
    assert _object_name("beef-chili", first, "hero").startswith("beef-chili/")


def test_run_id_is_reused_so_one_card_stays_together():
    """Every image in a card shares the prefix its first call created."""
    from recipe_cards.images import _object_name, new_run_id

    run = new_run_id()
    prefixes = {
        _object_name("beef-chili", run, name).rsplit("/", 1)[0]
        for name in ("hero", "step-1", "ingredient-garlic")
    }
    assert len(prefixes) == 1


@pytest.mark.parametrize("count", [4, 6, 8, 10, 12, 16])
def test_ingredient_panel_fits_its_rows(count):
    """The panel is drawn to the list, so a short list gives a short panel.

    Rows keep one pitch until the list would run past the footer; only then do
    they compress, and never below the readable floor.
    """
    from recipe_cards.rendering import theme as ct

    rows = min(count, ct.INGREDIENT_MAX_ROWS)
    available = ct.INGREDIENT_PANEL_MAX_BOTTOM - ct.INGREDIENT_PANEL_TOP
    usable = available - 2 * ct.INGREDIENT_PANEL_PADDING
    row_h = max(min(ct.INGREDIENT_ROW_MAX_HEIGHT, usable / rows), ct.INGREDIENT_ROW_MIN_HEIGHT)
    panel_h = min(available, row_h * rows + 2 * ct.INGREDIENT_PANEL_PADDING)

    assert row_h >= ct.INGREDIENT_ROW_MIN_HEIGHT
    # The panel never runs past the space reserved for it.
    assert ct.INGREDIENT_PANEL_TOP + panel_h <= ct.INGREDIENT_PANEL_MAX_BOTTOM + 1e-6
    # Rows fit inside the panel they are drawn in.
    assert row_h * rows <= panel_h - 2 * ct.INGREDIENT_PANEL_PADDING + 1e-6
    # A list short enough to keep full pitch leaves no empty lower half.
    if rows * ct.INGREDIENT_ROW_MAX_HEIGHT + 2 * ct.INGREDIENT_PANEL_PADDING <= available:
        assert row_h == ct.INGREDIENT_ROW_MAX_HEIGHT
        assert abs(panel_h - (row_h * rows + 2 * ct.INGREDIENT_PANEL_PADDING)) < 1e-6


@pytest.mark.parametrize("workflow", ALL_WORKFLOWS)
def test_workflow_stages_are_ordered_and_chained(workflow):
    """A workflow's value is that its order is fixed, so assert the chain.

    Each stage must publish its result under an output_key, because that is how
    the next stage receives it. A stage without one silently produces nothing
    for its successor to read.
    """
    spec = registry.get_agent_spec(workflow)
    module = importlib.import_module(spec.module)
    stages = module.root_agent.sub_agents

    assert len(stages) >= 2, "a workflow with one stage is just an agent"
    keys = [stage.output_key for stage in stages]
    assert all(keys), f"every stage needs an output_key, got {keys}"
    assert len(set(keys)) == len(keys), f"stages overwrite each other: {keys}"


@pytest.mark.parametrize("workflow", ALL_WORKFLOWS)
def test_workflow_reuses_agent_tools(workflow):
    """A workflow changes when tools run, not what they do.

    Duplicating a tool would let the two entry points drift apart, so every
    tool a stage uses must be the very object the agent exposes.
    """
    from recipe_card_agent.tools import generate_recipe_images, render_recipe_card

    spec = registry.get_agent_spec(workflow)
    module = importlib.import_module(spec.module)

    shared = {generate_recipe_images, render_recipe_card}
    used = {
        tool
        for stage in module.root_agent.sub_agents
        for tool in (stage.tools or [])
        if callable(tool)
    }
    assert used, "no stage calls a tool"
    assert used <= shared, "a workflow stage defines its own copy of a tool"


def test_cooking_tip_is_per_step_page():
    """Steps paginate in fours, so a long recipe carries one tip per page.

    Repeating a single tip above every page reads as a rendering fault, and a
    tip about the opening steps is noise above the closing ones.
    """
    from recipe_cards.rendering.content import cooking_tip_for_page

    recipe = {"cooking_tip": ["Tip for steps 1-4.", "Tip for steps 5-8."]}
    assert cooking_tip_for_page(recipe, 0) == "Tip for steps 1-4."
    assert cooking_tip_for_page(recipe, 1) == "Tip for steps 5-8."
    # A page beyond the supplied tips shows none rather than repeating one.
    assert cooking_tip_for_page(recipe, 2) == ""


def test_single_cooking_tip_appears_once():
    """A plain string stays supported, but only on the first page."""
    from recipe_cards.rendering.content import cooking_tip_for_page

    recipe = {"cooking_tip": "Reserve some pasta water."}
    assert cooking_tip_for_page(recipe, 0) == "Reserve some pasta water."
    assert cooking_tip_for_page(recipe, 1) == ""
    assert cooking_tip_for_page({}, 0) == ""


@pytest.mark.parametrize("agent", ALL_ENTRIES)
def test_identity_roles_are_declared_in_the_spec(agent, monkeypatch):
    """IAM an agent needs is versioned, so a fresh clone deploys with it.

    Kept only in the environment, the grants that make an agent work would not
    survive a clone, and a deployment would come up unable to reach its own
    resources.
    """
    import sys

    sys.path.insert(0, str(DEV))
    from iam.apply_agent_identity_iam import requested_storage_bucket_roles

    monkeypatch.setenv("RECIPE_CARD_BUCKET", "unit-test-bucket")
    spec = registry.get_agent_spec(agent)
    for binding in spec.agent_identity_bucket_roles:
        assert binding.roles, f"{agent} names a bucket with no roles"
        assert binding.resolved_bucket().startswith("gs://")

    # An agent that publishes to a bucket must say so.
    if "recipe_card" in agent:
        assert requested_storage_bucket_roles(spec), f"{agent} publishes but declares no access"


def test_bucket_placeholder_resolves_from_the_environment(monkeypatch):
    """A spec names its bucket by variable, so no project's bucket is committed."""
    monkeypatch.setenv("RECIPE_CARD_BUCKET", "some-bucket")
    binding = registry.BucketRoles("${RECIPE_CARD_BUCKET}", (registry.STORAGE_OBJECT_ADMIN,))
    assert binding.resolved_bucket() == "gs://some-bucket"

    # Unset resolves to nothing rather than to a guessed name.
    monkeypatch.delenv("RECIPE_CARD_BUCKET", raising=False)
    assert binding.resolved_bucket() == ""


def test_environment_overrides_the_declared_roles(monkeypatch):
    """An environment can still grant something the repository should not name."""
    import sys

    sys.path.insert(0, str(DEV))
    from iam.apply_agent_identity_iam import requested_project_roles

    spec = registry.get_agent_spec("recipe_card_agent")
    monkeypatch.setenv(f"{spec.env_prefix}_AGENT_IDENTITY_PROJECT_ROLES", "roles/logging.logWriter")
    assert requested_project_roles(spec) == ("roles/logging.logWriter",)


def test_every_environment_variable_is_documented():
    """A setting the code reads but no example mentions cannot be configured.

    Someone deploying from a clean clone has only the example files to work
    from, so an undocumented variable is a silent gap in the setup.
    """

    repo = DEV.parent
    roots = [repo / d for d in ("dev", "packages", "agents", "workflows")]
    pattern = re.compile(r'os\.(?:getenv|environ)(?:\.get)?\(\s*"([A-Z][A-Z0-9_]+)"')
    used: set[str] = set()
    for root in roots:
        for path in root.rglob("*.py"):
            used.update(pattern.findall(path.read_text(encoding="utf-8")))

    documented: set[str] = set()
    for name in (".env.dev.example", ".env.local.example"):
        text = (DEV / name).read_text(encoding="utf-8")
        documented.update(re.findall(r"^#?\s*([A-Z][A-Z0-9_]+)=", text, re.MULTILINE))
        # Names shown inside prose, such as the <AGENT>_ prefixed families.
        documented.update(re.findall(r"\b([A-Z][A-Z0-9_]{3,})\b", text))

    # Supplied by Agent Runtime rather than by the operator.
    supplied_by_platform = {"GOOGLE_CLOUD_AGENT_ENGINE_ID"}
    # Per-agent variables are derived from a package name at runtime.
    derived = {name for name in used if name.startswith(("RECIPE_CARD_", "DEV_"))}

    missing = used - documented - supplied_by_platform - derived
    assert not missing, f"environment variables the code reads but no example documents: {missing}"


def test_baseline_roles_match_the_platform_stack():
    from iam.apply_agent_identity_iam import BASELINE_AGENT_IDENTITY_ROLES

    policy = json.loads((DEV.parent / "infrastructure/runtime_iam_policy.json").read_text())
    assert set(BASELINE_AGENT_IDENTITY_ROLES) == set(policy["baseline_project_roles"])
    assert "roles/storage.objectViewer" not in BASELINE_AGENT_IDENTITY_ROLES


def test_baseline_grant_is_off_unless_requested(monkeypatch):
    """A managed project must never be granted IAM behind Terraform's back."""
    import sys

    sys.path.insert(0, str(DEV))
    import iam.apply_agent_identity_iam as agent_iam

    monkeypatch.delenv(agent_iam.BASELINE_ROLES_ENV, raising=False)
    calls = Mock()
    monkeypatch.setattr(agent_iam, "_run_gcloud", calls)
    assert agent_iam.ensure_baseline_roles("test-project") == ()
    calls.assert_not_called()


def test_baseline_grant_targets_every_agent_identity(monkeypatch):
    """The grant must reach runtimes that do not exist yet.

    Granting to one runtime's identity would mean every new agent needed an IAM
    change, which is the coupling the principal set exists to avoid.
    """
    import sys

    sys.path.insert(0, str(DEV))
    import iam.apply_agent_identity_iam as agent_iam

    monkeypatch.setattr(agent_iam, "_project_number", lambda project: "123456789")
    monkeypatch.setattr(agent_iam, "_organization_id", lambda project: None)
    principal_set = agent_iam.agent_identity_principal_set("test-project")

    assert principal_set.startswith("principalSet://")
    # Orgless uses "proj-": IAM rejects the documented "project-" spelling.
    assert "agents.global.proj-123456789.system.id.goog" in principal_set
    assert "attribute.platformContainer" in principal_set


def test_overlong_step_is_returned_for_correction(monkeypatch):
    """A recipe the model can fix comes back as a result, not an exception.

    Raising reaches the model as a generic tool failure with nothing to act on,
    so a card that only needs a shorter step would be abandoned instead of
    corrected.
    """
    import sys

    sys.path.insert(0, str(DEV.parent / "packages" / "recipe_cards" / "src"))
    from recipe_cards import publish
    from recipe_cards.errors import ContentTooLong

    monkeypatch.setattr(publish, "OUTPUT_BUCKET", "test-bucket")
    monkeypatch.setattr(
        publish,
        "render_deck",
        Mock(side_effect=ContentTooLong("steps[0].body", "too long", "remove 20 words")),
    )
    context = SimpleNamespace(state={})
    payload = '{"slug": "x", "title": "X", "servings": "4", "steps": [], "ingredients": []}'
    monkeypatch.setattr(publish, "load_recipes", lambda _: {"recipes": [{"slug": "x"}]})

    result = publish.render_recipe_card(payload, context)

    assert result["status"] == "needs_correction"
    assert result["field"] == "steps[0].body"
    assert "remove 20 words" in result["fix"]
    assert result["attempts_remaining"] >= 1
    # The model is told what to do next, not merely that something failed.
    assert "render_recipe_card again" in result["next_step"]


def test_correction_attempts_are_bounded(monkeypatch):
    """A recipe that cannot be shortened enough stops rather than looping."""
    import sys

    sys.path.insert(0, str(DEV.parent / "packages" / "recipe_cards" / "src"))
    from recipe_cards import publish
    from recipe_cards.errors import ContentTooLong

    monkeypatch.setattr(publish, "OUTPUT_BUCKET", "test-bucket")
    monkeypatch.setattr(
        publish,
        "render_deck",
        Mock(side_effect=ContentTooLong("steps[0].body", "too long", "shorten it")),
    )
    monkeypatch.setattr(publish, "load_recipes", lambda _: {"recipes": [{"slug": "x"}]})
    payload = "{}"

    context = SimpleNamespace(state={})
    run_id = ""
    for _ in range(publish.get_runtime_config().max_attempts - 1):
        result = publish.render_recipe_card(payload, context, run_id)
        assert result["status"] == "needs_correction"
        run_id = result["run_id"]

    # Exhaustion is a tool response, not an exception terminating the turn.
    result = publish.render_recipe_card(payload, context, run_id)
    assert result["status"] == "failed"
    assert result["retryable"] is False
    assert result["attempts_remaining"] == 0
    assert "deck_url" not in result
    calls = publish.render_deck.call_count
    assert publish.render_recipe_card(payload, context, run_id) == result
    assert publish.render_deck.call_count == calls

    # A new recipe run in the same session receives its own correction budget.
    result = publish.render_recipe_card(payload, context)
    assert result["run_id"] != run_id
    assert result["attempts_remaining"] == publish.get_runtime_config().max_attempts - 1
