"""Keep unit tests independent of workstation credentials and cloud settings."""

import os

import google.auth
import pytest
from google.auth.credentials import AnonymousCredentials


@pytest.fixture(autouse=True)
def offline_environment(monkeypatch):
    for name in list(os.environ):
        if name.startswith(("DEV_", "CONFIG_", "GEMINI_", "GOOGLE_CLOUD_")):
            monkeypatch.delenv(name)
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "test-project")
    monkeypatch.setenv("GOOGLE_CLOUD_LOCATION", "us-central1")
    monkeypatch.setenv("GEMINI_MODEL", "test-model")
    monkeypatch.setenv("AGENT_INSTRUCTION", "Test instruction")
    monkeypatch.setenv("GEMINI_ENTERPRISE_AUTHORIZATION_ID", "unit-test-authorization")
    monkeypatch.setattr(
        google.auth, "default", lambda *args, **kwargs: (AnonymousCredentials(), "test-project")
    )
