from __future__ import annotations

import os

from bigquery_fixture import prepare_bigquery_fixture
from bootstrap import ensure_runtime_parameter, prepare_dev_platform
from common import ROOT, load_environment, require_dev_environment


PLACEHOLDER_TOKEN = "REPLACE"


def _configured_value(name: str) -> bool:
    value = os.getenv(name, "").strip()
    return bool(value and PLACEHOLDER_TOKEN not in value and not value.startswith("<"))


def main() -> None:
    os.chdir(ROOT)
    load_environment(".env.dev")
    project_id, location, staging_bucket = require_dev_environment(
        require_parameter=False
    )
    prepare_dev_platform(project_id, location, staging_bucket)

    fixture = prepare_bigquery_fixture(project_id, location)
    if fixture is not None:
        print(f"BIGQUERY_FIXTURE_TABLE={fixture.table_id}")
        print(f"BIGQUERY_FIXTURE_DATASET_CREATED={str(fixture.created_dataset).lower()}")
        print(f"BIGQUERY_FIXTURE_TABLE_CREATED={str(fixture.created_table).lower()}")
        print(f"BIGQUERY_FIXTURE_ROWS_SEEDED={fixture.seeded_rows}")

    if _configured_value("CONFIG_PARAMETER"):
        ensure_runtime_parameter(project_id)
        print("DEV_PREREQUISITES=ready")
    else:
        print("DEV_PLATFORM_PREREQUISITES=ready")
        print(
            "NEXT_STEP=Apply the Terraform dev stack, then set CONFIG_PARAMETER "
            "to its runtime_config_parameter output."
        )


if __name__ == "__main__":
    main()
