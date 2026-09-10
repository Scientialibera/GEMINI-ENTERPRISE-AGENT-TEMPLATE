"""Keep unit tests independent of workstation credentials and cloud settings."""

import os
import tempfile
from pathlib import Path

import google.auth
import pytest
from google.auth.credentials import AnonymousCredentials


def _symlinks_available() -> bool:
    """Whether this machine lets an unprivileged process create a symlink.

    Windows refuses without Developer Mode or elevation, so a test that builds
    a symlink fixture fails there for a reason unrelated to what it asserts.
    """
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        target = root / "target.txt"
        target.write_text("x")
        try:
            (root / "link").symlink_to(target)
        except (OSError, NotImplementedError):
            return False
        return True


# The guard these tests cover is real, so they are skipped rather than removed:
# they still run wherever symlinks can be created, such as Linux CI.
requires_symlinks = pytest.mark.skipif(
    not _symlinks_available(),
    reason="This platform does not permit creating symbolic links.",
)


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
