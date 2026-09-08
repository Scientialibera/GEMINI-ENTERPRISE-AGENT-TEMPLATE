from __future__ import annotations

import sys
from pathlib import Path

# Runnable directly as well as imported by release_dev.py, so dev/ has to be
# on sys.path either way: running this file puts only its own folder there.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import os

from common import ROOT, load_environment, require_dev_environment
from fixtures.bigquery_fixture import (
    BIGQUERY_API_SERVICE,
    bigquery_fixture_enabled,
    prepare_bigquery_fixture,
)

from config.bootstrap import ensure_runtime_parameter, prepare_dev_platform
from config.environment import configured_value


def main() -> None:
    os.chdir(ROOT)
    load_environment(".env.dev")
    project_id, location, staging_bucket = require_dev_environment(require_parameter=False)

    fixture_enabled = bigquery_fixture_enabled()
    additional_services = (BIGQUERY_API_SERVICE,) if fixture_enabled else ()
    prepare_dev_platform(
        project_id,
        location,
        staging_bucket,
        additional_services=additional_services,
    )

    fixture = prepare_bigquery_fixture(project_id, location) if fixture_enabled else None
    if fixture is not None:
        print(f"BIGQUERY_FIXTURE_TABLE={fixture.table_id}")
        print(f"BIGQUERY_FIXTURE_DATASET_CREATED={str(fixture.created_dataset).lower()}")
        print(f"BIGQUERY_FIXTURE_TABLE_CREATED={str(fixture.created_table).lower()}")
        print(f"BIGQUERY_FIXTURE_ROWS_SEEDED={fixture.seeded_rows}")

    # Per-agent parameters are resolved during deployment.
    if configured_value("CONFIG_PARAMETER"):
        ensure_runtime_parameter(project_id)
    # A sandbox with no platform stack needs the roles every Agent Identity
    # reads its own configuration with, or its agents deploy and then fail on
    # the first request. Off unless asked for, so a managed project is never
    # granted IAM behind Terraform's back.
    from iam.apply_agent_identity_iam import ensure_baseline_roles

    granted = ensure_baseline_roles(project_id)
    if granted:
        print(f"AGENT_IDENTITY_BASELINE_GRANTED={len(granted)}")

    print("DEV_PREREQUISITES=ready")
    print("NEXT_STEP=Run deploy/deploy_dev.py --agent <name>; it creates that agent's parameter.")


if __name__ == "__main__":
    main()
