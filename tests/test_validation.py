from __future__ import annotations

import asyncio
import datetime
import decimal
import importlib
import json
import logging
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
bootstrap = importlib.import_module("bootstrap")
fixture = importlib.import_module("bigquery_fixture")
common = importlib.import_module("common")
packaging = importlib.import_module("package_agent")
sys.path.remove(str(DEV))

# Derived from the registry so an agent added to AGENTS is covered here without
# editing this file.
ALL_AGENTS = sorted(common.AGENTS)


@pytest.fixture(autouse=True)
def environment(monkeypatch):
    for name in list(__import__("os").environ):
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
        common.require_dev_environment()


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


@pytest.mark.parametrize("agent", ALL_AGENTS)
def test_packaging_excludes_cache_and_other_agent(tmp_path, monkeypatch, agent):
    source = tmp_path / agent
    source.mkdir()
    (source / "agent.py").write_text("x = 1\n")
    cache = source / "__pycache__"
    cache.mkdir()
    (cache / "agent.pyc").write_bytes(b"first")
    spec = SimpleNamespace(requirements=("test==1",), extra_packages=(agent,))
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
    """Both agents share one implementation, so exercise it directly."""
    from gemini_shared import apply_runtime_model

    request = SimpleNamespace(model="old")
    apply_runtime_model(None, request)
    assert request.model == "test-model"

    for agent in ALL_AGENTS:
        module = importlib.import_module(f"{agent}.agent")
        assert module.root_agent.before_model_callback is apply_runtime_model


@pytest.mark.parametrize("agent", ALL_AGENTS)
def test_every_tool_is_described_to_the_model(agent):
    """ADK builds the tool declaration from the function itself, so a tool
    without a docstring reaches the model with no description."""
    from google.adk.tools.base_toolset import BaseToolset
    from google.adk.tools.function_tool import FunctionTool

    module = importlib.import_module(f"{agent}.agent")
    undescribed = []
    for tool in module.root_agent.tools:
        # A toolset's descriptions come from the remote server at request time,
        # so there is nothing to assert offline.
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
    """Prompt text belongs in runtime configuration, not in the agent package."""
    module = importlib.import_module(f"{agent}.agent")
    assert callable(module.root_agent.instruction), (
        f"{agent} must resolve its instruction from runtime configuration"
    )


def test_delegated_scheme_rehydrates_from_shared_module():
    """A deployed scheme arrives as a base CustomAuthScheme and is rehydrated by
    matching type_ against CustomAuthScheme.__subclasses__(), so the provider
    resolves from gemini_shared without living beside the agent."""
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
    """Storage access uses the runtime's own identity, so importing it must not
    require a Gemini Enterprise authorization the way delegated auth does."""
    monkeypatch.delenv("GEMINI_ENTERPRISE_AUTHORIZATION_ID", raising=False)
    module = importlib.reload(importlib.import_module("gemini_shared.connectors.cloud_storage"))
    assert callable(module.list_bucket_objects)


def test_mcp_headers_carry_the_signed_in_users_token():
    """The MCP server applies the caller's own permissions, so the header must
    carry the delegated user token rather than the runtime's identity."""
    from gemini_shared.mcp.mcp_auth import delegated_bearer_headers

    token = secrets.token_urlsafe(16)
    provider = delegated_bearer_headers("unit-test-authorization")
    context = SimpleNamespace(state={"unit-test-authorization": token})
    assert provider(context) == {"Authorization": f"Bearer {token}"}


def test_mcp_headers_fail_loudly_without_a_token():
    """Sending no Authorization header would reach the server as an anonymous
    call, so an unresolved token must raise instead."""
    from gemini_shared.mcp.mcp_auth import delegated_bearer_headers

    provider = delegated_bearer_headers("unit-test-authorization")
    context = SimpleNamespace(state={"other-a": "1", "other-b": "2"})
    with pytest.raises(ValueError, match="No delegated token"):
        provider(context)


def test_mcp_toolset_is_wired_to_a_remote_server():
    """The MCP tools must come from a remote endpoint over Streamable HTTP, so
    the template needs no MCP server of its own."""
    from gemini_shared.mcp.mcp_google_cloud import BIGQUERY_READONLY_TOOLS
    from google.adk.tools.mcp_tool.mcp_session_manager import StreamableHTTPConnectionParams

    module = importlib.import_module("bigquery_mcp_agent.tools.bigquery_mcp")
    params = module.bigquery_mcp_toolset._connection_params
    assert isinstance(params, StreamableHTTPConnectionParams)
    assert params.url.startswith("https://")
    # execute_sql would let the MCP path mutate data.
    assert "execute_sql" not in BIGQUERY_READONLY_TOOLS
