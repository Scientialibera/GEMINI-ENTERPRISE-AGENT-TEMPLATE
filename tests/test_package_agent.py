from __future__ import annotations

import importlib.util
import sys
import tarfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DEV_DIR = ROOT / "dev"
PACKAGE_MODULE_PATH = DEV_DIR / "deploy" / "package_agent.py"
# Check that nested shared modules reach the archive.
EXPECTED_ARCHIVE_MEMBERS = {
    "requirements.txt",
    "basic_assistant",
    "basic_assistant/__init__.py",
    "basic_assistant/agent.py",
    "gemini_shared",
    "gemini_shared/__init__.py",
    "gemini_shared/auth/__init__.py",
    "gemini_shared/auth/delegated.py",
    "gemini_shared/config/__init__.py",
    "gemini_shared/config/bootstrap.py",
    "gemini_shared/config/runtime_config.py",
    "gemini_shared/config/tools.py",
    "gemini_shared/mcp/__init__.py",
    "gemini_shared/mcp/mcp_auth/__init__.py",
    "gemini_shared/mcp/mcp_auth/toolset.py",
    "gemini_shared/mcp/mcp_google_cloud/__init__.py",
    "gemini_shared/mcp/mcp_google_cloud/servers.py",
}


def _load_package_module():
    sys.path.insert(0, str(DEV_DIR))
    try:
        spec = importlib.util.spec_from_file_location("package_agent_for_test", PACKAGE_MODULE_PATH)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(DEV_DIR))


@pytest.mark.parametrize("agent", ["basic_assistant", "auth_reference_agent", "bigquery_mcp_agent"])
def test_package_is_deterministic_and_has_expected_layout(tmp_path: Path, agent: str) -> None:
    module = _load_package_module()
    first = module.package_agent(agent, tmp_path / "first.tar.gz")
    second = module.package_agent(agent, tmp_path / "second.tar.gz")

    assert first.read_bytes() == second.read_bytes()

    with tarfile.open(first, mode="r:gz") as archive:
        members = {member.name for member in archive.getmembers()}

    expected = {name.replace("basic_assistant", agent) for name in EXPECTED_ARCHIVE_MEMBERS}
    assert expected.issubset(members)
    assert {name.split("/")[0] for name in members} == {"requirements.txt", agent, "gemini_shared"}


@pytest.mark.parametrize("agent", ["recipe_card_agent", "recipe_card_workflow"])
def test_recipe_packages_include_shared_tools_and_style_plates(tmp_path, agent):
    module = _load_package_module()
    path = module.package_agent(agent, tmp_path / "recipe.tar.gz")
    with tarfile.open(path, "r:gz") as archive:
        members = {member.name for member in archive.getmembers()}
    assert {
        "recipe_cards/schema.py",
        "recipe_cards/rendering/assets.py",
        "recipe_cards/style/example_card_1.jpg",
        "recipe_cards/style/example_card_2.jpg",
    } <= members
    if agent == "recipe_card_workflow":
        assert not any(name.startswith("recipe_card_agent/") for name in members)
