from __future__ import annotations

import os

from bigquery_fixture import (
    BIGQUERY_API_SERVICE,
    bigquery_fixture_enabled,
    prepare_bigquery_fixture,
)
from bootstrap import ensure_runtime_parameter, prepare_dev_platform
from common import ROOT, load_environment, require_dev_environment

PLACEHOLDER_MARKER = "REPLACE"


def _configured_value(name: str) -> bool:
    value = os.getenv(name, "").strip()
    return bool(value and PLACEHOLDER_MARKER not in value and not value.startswith("<"))


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

    # Only a pinned override is checked here. Each agent otherwise reads its own
    # parameter, which deploy_dev.py creates on first deployment.
    if _configured_value("CONFIG_PARAMETER"):
        ensure_runtime_parameter(project_id)
    print("DEV_PREREQUISITES=ready")
    print("NEXT_STEP=Run deploy_dev.py --agent <name>; it creates that agent's parameter.")


if __name__ == "__main__":
    main()
