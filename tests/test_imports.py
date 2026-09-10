import importlib


def _base_env(monkeypatch):
    monkeypatch.delenv("CONFIG_PARAMETER", raising=False)
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "test-project")
    monkeypatch.setenv("GOOGLE_CLOUD_LOCATION", "us-central1")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-test")
    monkeypatch.setenv("AGENT_INSTRUCTION", "test instruction")
    monkeypatch.setenv("GEMINI_ENTERPRISE_AUTHORIZATION_ID", "test-authz")


def test_basic_assistant_imports(monkeypatch):
    _base_env(monkeypatch)
    module = importlib.import_module("basic_assistant.agent")
    assert module.root_agent.name == "basic_assistant"


def test_auth_reference_agent_imports(monkeypatch):
    _base_env(monkeypatch)
    module = importlib.import_module("auth_reference_agent.agent")
    assert module.root_agent.name == "auth_reference_agent"


def test_bigquery_mcp_agent_imports(monkeypatch):
    _base_env(monkeypatch)
    module = importlib.import_module("bigquery_mcp_agent.agent")
    assert module.root_agent.name == "bigquery_mcp_agent"


def test_monitoring_mcp_agent_imports(monkeypatch):
    _base_env(monkeypatch)
    module = importlib.import_module("monitoring_mcp_agent.agent")
    assert module.root_agent.name == "monitoring_mcp_agent"
