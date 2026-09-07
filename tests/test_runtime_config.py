import pytest
from gemini_shared.config.runtime_config import get_runtime_config, reset_runtime_config_for_tests


def test_local_runtime_config(monkeypatch):
    monkeypatch.delenv("CONFIG_PARAMETER", raising=False)
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "test-project")
    monkeypatch.setenv("GOOGLE_CLOUD_LOCATION", "us-central1")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-test")
    monkeypatch.setenv("AGENT_INSTRUCTION", "test instruction")
    monkeypatch.setenv("ENVIRONMENT", "local")
    reset_runtime_config_for_tests()

    config = get_runtime_config()

    assert config.config_revision == "local"
    assert config.model == "gemini-test"
    assert config.instruction == "test instruction"
    assert config.environment == "local"


def test_local_runtime_config_requires_model(monkeypatch):
    monkeypatch.delenv("CONFIG_PARAMETER", raising=False)
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "test-project")
    monkeypatch.setenv("GOOGLE_CLOUD_LOCATION", "us-central1")
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    monkeypatch.setenv("AGENT_INSTRUCTION", "test instruction")
    reset_runtime_config_for_tests()

    with pytest.raises(RuntimeError, match="GEMINI_MODEL"):
        get_runtime_config()
