from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
DEV_DIR = ROOT / "dev"
MODULE_PATH = DEV_DIR / "bigquery_fixture.py"


def _load_module():
    sys.path.insert(0, str(DEV_DIR))
    try:
        spec = importlib.util.spec_from_file_location("bigquery_fixture_for_test", MODULE_PATH)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(DEV_DIR))


def test_fixture_can_be_disabled_without_cloud_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_module()
    monkeypatch.setenv(module.PREPARE_FIXTURE_ENV, "false")

    assert module.prepare_bigquery_fixture("example-project", "us-central1") is None


def test_invalid_dataset_id_fails_before_cloud_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_module()
    monkeypatch.setenv(module.PREPARE_FIXTURE_ENV, "true")
    monkeypatch.setenv(module.DATASET_ID_ENV, "invalid-dataset-id")

    with pytest.raises(SystemExit, match=module.DATASET_ID_ENV):
        module.prepare_bigquery_fixture("example-project", "us-central1")
