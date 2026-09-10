"""Cloud Monitoring MCP agent: endpoint, allowlist, scopes and token routing.

The delegated-auth tests here cover the boundary the agent depends on rather
than the agent's own code: the header provider is shared, so a regression in it
would silently send one user's token for another's request.
"""

from __future__ import annotations

import importlib
import secrets
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from gemini_shared.mcp.mcp_auth import delegated_bearer_headers
from gemini_shared.mcp.mcp_google_cloud import (
    CLOUD_MONITORING,
    CLOUD_MONITORING_READONLY_SCOPE,
    CLOUD_MONITORING_READONLY_TOOLS,
)
from google.adk.tools.mcp_tool.mcp_session_manager import StreamableHTTPConnectionParams

DEV = Path(__file__).resolve().parents[1] / "dev"
sys.path.insert(0, str(DEV))
registry = importlib.import_module("registry")
sys.path.remove(str(DEV))

AGENT = "monitoring_mcp_agent"
AUTHORIZATION = "monitoring-mcp-agent-authz"

# Verified against Google's published MCP tool reference for this server. Every
# entry is annotated read-only there; nothing creates, edits or deletes.
DOCUMENTED_READONLY_TOOLS = {
    "list_timeseries",
    "query_range",
    "list_metric_descriptors",
    "list_alert_policies",
    "get_alert_policy",
    "list_alerts",
    "get_alert",
    "list_dashboards",
    "get_dashboard",
}


def _toolset():
    return importlib.import_module(f"{AGENT}.tools.monitoring_mcp").monitoring_mcp_toolset


def test_toolset_targets_the_managed_monitoring_endpoint():
    """The user's bearer token may only go to the operator-configured endpoint."""
    params = _toolset()._connection_params
    assert isinstance(params, StreamableHTTPConnectionParams)
    assert params.url == CLOUD_MONITORING == "https://monitoring.googleapis.com/mcp"
    assert params.url.startswith("https://")


def test_allowlist_is_explicit_and_read_only():
    """tool_filter=None would expose whatever the server adds later."""
    toolset = _toolset()
    assert set(toolset.tool_filter) == DOCUMENTED_READONLY_TOOLS
    assert set(CLOUD_MONITORING_READONLY_TOOLS) == DOCUMENTED_READONLY_TOOLS
    # A mutating verb reaching this list means the allowlist was widened.
    assert not [
        tool
        for tool in CLOUD_MONITORING_READONLY_TOOLS
        if tool.startswith(("create_", "update_", "delete_", "patch_", "write_"))
    ]


def test_tool_names_are_prefixed_apart_from_other_agents():
    """A shared prefix would let two MCP agents' tools collide in one model."""
    from gemini_shared.mcp.mcp_google_cloud import bigquery_readonly_toolset

    other = bigquery_readonly_toolset(authorization_id=AUTHORIZATION)
    assert _toolset().tool_name_prefix == "mon_mcp"
    assert _toolset().tool_name_prefix != other.tool_name_prefix


def test_spec_requests_the_read_only_scope():
    """Read-only tools must not consent the user to a write-capable scope."""
    spec = registry.get_agent_spec(AGENT)
    assert spec.delegated_oauth_scopes == (CLOUD_MONITORING_READONLY_SCOPE,)
    assert CLOUD_MONITORING_READONLY_SCOPE == "https://www.googleapis.com/auth/monitoring.read"
    # The read-write scope Google's MCP guide shows is deliberately not requested.
    assert "https://www.googleapis.com/auth/monitoring" not in spec.delegated_oauth_scopes
    assert registry.CLOUD_PLATFORM_SCOPE not in spec.delegated_oauth_scopes
    assert spec.uses_delegated_auth


def test_registry_metadata_is_distinct_and_delegated():
    """Sharing an authorization or client with another agent breaks consent."""
    spec = registry.get_agent_spec(AGENT)
    assert spec.authorization_id == AUTHORIZATION
    assert spec.package_name == "monitoring-mcp-agent"
    assert registry.detect_delegated_auth(spec)
    others = [s for name, s in registry.AGENTS.items() if name != AGENT and s.uses_delegated_auth]
    assert others
    for other in others:
        assert spec.authorization_id != other.authorization_id
        assert spec.default_oauth_secret_name != other.default_oauth_secret_name
        assert spec.config_parameter_id != other.config_parameter_id


def test_runtime_env_is_declared_per_agent(monkeypatch):
    """A runtime setting one agent needs must not reach the next one released.

    RUNTIME_ENV_KEYS is one shared value per key, so a flag left in the
    environment for this agent would be baked into whichever agent is deployed
    afterwards. Declaring it on the spec keeps it scoped and versioned.
    """
    import importlib
    import sys

    sys.path.insert(0, str(DEV))
    settings = importlib.import_module("config.settings")

    flag = "ADK_DISABLE_JSON_SCHEMA_FOR_FUNC_DECL"
    monkeypatch.delenv(flag, raising=False)
    monkeypatch.delenv("MCP_SERVER_URL", raising=False)

    mine = settings.runtime_env(registry.get_agent_spec(AGENT))
    assert mine[flag] == "true"

    # The shared forwarding list must not carry it, or every agent gets it.
    assert flag not in settings.RUNTIME_ENV_KEYS
    for name, spec in registry.AGENTS.items():
        if name != AGENT:
            assert flag not in settings.runtime_env(spec), f"{name} inherited {flag}"


def test_each_mcp_agent_declares_its_own_endpoint(monkeypatch):
    """A shared endpoint variable silently retargets one agent at another's server.

    The user's bearer token is sent to this URL, so it must come from the
    agent's own spec rather than whatever was last left in the environment.
    """
    import importlib
    import sys

    sys.path.insert(0, str(DEV))
    settings = importlib.import_module("config.settings")

    monkeypatch.delenv("MCP_SERVER_URL", raising=False)
    assert "MCP_SERVER_URL" not in settings.RUNTIME_ENV_KEYS

    mine = settings.runtime_env(registry.get_agent_spec(AGENT))["MCP_SERVER_URL"]
    other = settings.runtime_env(registry.get_agent_spec("bigquery_mcp_agent"))["MCP_SERVER_URL"]
    assert mine == CLOUD_MONITORING
    assert other != mine
    # A non-MCP agent must not be given an endpoint at all.
    assert "MCP_SERVER_URL" not in settings.runtime_env(registry.get_agent_spec("basic_assistant"))


def test_environment_still_overrides_a_declared_runtime_value(monkeypatch):
    """A single run can override a declared setting without editing the spec."""
    import importlib
    import sys

    sys.path.insert(0, str(DEV))
    settings = importlib.import_module("config.settings")

    flag = "ADK_DISABLE_JSON_SCHEMA_FOR_FUNC_DECL"
    monkeypatch.setattr(settings, "RUNTIME_ENV_KEYS", (*settings.RUNTIME_ENV_KEYS, flag))
    monkeypatch.setenv(flag, "false")
    assert settings.runtime_env(registry.get_agent_spec(AGENT))[flag] == "false"


def test_package_ships_without_the_other_mcp_agent():
    """Each archive carries one entry point plus the shared package."""
    spec = registry.get_agent_spec(AGENT)
    assert f"agents/{AGENT}/src/{AGENT}" in spec.extra_packages
    assert not [path for path in spec.extra_packages if "bigquery_mcp_agent" in path]


def test_each_user_gets_their_own_authorization_header():
    """Two sessions must produce two tokens; a cached header would cross users."""
    provider = delegated_bearer_headers(AUTHORIZATION)
    first, second = secrets.token_urlsafe(16), secrets.token_urlsafe(16)
    alice = provider(SimpleNamespace(state={AUTHORIZATION: first}))
    bob = provider(SimpleNamespace(state={AUTHORIZATION: second}))
    assert alice == {"Authorization": f"Bearer {first}"}
    assert bob == {"Authorization": f"Bearer {second}"}
    assert alice != bob


def test_missing_consent_fails_before_any_request():
    """No token must raise rather than fall back to ADC or Agent Identity."""
    provider = delegated_bearer_headers(AUTHORIZATION)
    with pytest.raises(ValueError, match="No delegated token"):
        provider(SimpleNamespace(state={}))


def test_no_runtime_credential_substitution(monkeypatch):
    """Google ADC must never stand in for absent user credentials."""
    import google.auth

    def fail(*args, **kwargs):
        raise AssertionError("delegated auth must not fall back to ADC")

    monkeypatch.setattr(google.auth, "default", fail)
    provider = delegated_bearer_headers(AUTHORIZATION)
    with pytest.raises(ValueError, match="No delegated token"):
        provider(SimpleNamespace(state={"unrelated-a": "x", "unrelated-b": "y"}))


def test_the_right_token_is_chosen_among_several_authorizations():
    """A session holding several authorizations must route by exact key."""
    provider = delegated_bearer_headers(AUTHORIZATION)
    mine, theirs = secrets.token_urlsafe(16), secrets.token_urlsafe(16)
    state = {AUTHORIZATION: mine, "bigquery-mcp-agent-authz": theirs}
    headers = provider(SimpleNamespace(state=state))
    assert headers == {"Authorization": f"Bearer {mine}"}
    assert theirs not in headers["Authorization"]


def test_a_foreign_authorization_never_supplies_this_agents_token():
    """A known authorization ID must be matched exactly, failing closed.

    A session carrying only another agent's authorization previously returned
    that token through a single-entry fallback, so this agent could be handed
    credentials the user never consented to give it.
    """
    from gemini_shared.auth.delegated import read_session_token

    foreign = secrets.token_urlsafe(16)
    state = {"bigquery-mcp-agent-authz": foreign}

    assert read_session_token(state, AUTHORIZATION) is None
    with pytest.raises(ValueError, match="No delegated token"):
        delegated_bearer_headers(AUTHORIZATION)(SimpleNamespace(state=state))

    # Several entries fail closed for the same reason.
    state["another-authz"] = secrets.token_urlsafe(16)
    assert read_session_token(state, AUTHORIZATION) is None

    # The legacy fallback survives only where no authorization ID is known.
    lone = secrets.token_urlsafe(16)
    assert read_session_token({"whatever": lone}, None) == lone


def test_agent_exposes_only_its_own_tools(monkeypatch):
    """The agent must not gain a tool that bypasses delegated auth."""
    from google.adk.tools.base_toolset import BaseToolset

    module = importlib.import_module(f"{AGENT}.agent")
    toolsets = [tool for tool in module.root_agent.tools if isinstance(tool, BaseToolset)]
    assert len(toolsets) == 1
    assert toolsets[0] is _toolset()
