from __future__ import annotations

import importlib.util
import sys
import tarfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEV_DIR = ROOT / "dev"
PACKAGE_MODULE_PATH = DEV_DIR / "package_agent.py"
EXPECTED_ARCHIVE_MEMBERS = {
    "requirements.txt",
    "basic_assistant",
    "basic_assistant/__init__.py",
    "basic_assistant/agent.py",
    "gemini_shared",
    "gemini_shared/__init__.py",
    "gemini_shared/bootstrap.py",
    "gemini_shared/runtime_config.py",
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


def test_package_is_deterministic_and_has_expected_layout(tmp_path: Path) -> None:
    module = _load_package_module()
    first = module.package_agent("basic_assistant", tmp_path / "first.tar.gz")
    second = module.package_agent("basic_assistant", tmp_path / "second.tar.gz")

    assert first.read_bytes() == second.read_bytes()

    with tarfile.open(first, mode="r:gz") as archive:
        members = {member.name for member in archive.getmembers()}

    assert EXPECTED_ARCHIVE_MEMBERS.issubset(members)
