"""Create or validate the optional BigQuery fixture used for developer testing.

The fixture is application-test support only. It does not grant IAM and it is not
part of the Terraform/shared-infrastructure ownership boundary.
"""

from __future__ import annotations

import os
import re
from collections.abc import Sequence
from dataclasses import dataclass

from google.api_core.exceptions import NotFound
from google.cloud import bigquery


PREPARE_FIXTURE_ENV = "DEV_PREPARE_BIGQUERY_FIXTURE"
CREATE_FIXTURE_ENV = "DEV_CREATE_BIGQUERY_FIXTURE_IF_MISSING"
DATASET_ID_ENV = "DEV_BIGQUERY_DATASET_ID"
TABLE_ID_ENV = "DEV_BIGQUERY_TABLE_ID"
LOCATION_ENV = "DEV_BIGQUERY_LOCATION"
BIGQUERY_API_SERVICE = "bigquery.googleapis.com"

DEFAULT_DATASET_ID = "gemini_agent_template_dev"
DEFAULT_TABLE_ID = "sample_orders"
FIXTURE_DESCRIPTION = "Gemini Enterprise agent template developer fixture."
RESOURCE_ID_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,1023}$")
TRUE_VALUES = frozenset({"1", "true", "yes", "on"})
FALSE_VALUES = frozenset({"0", "false", "no", "off"})

FIXTURE_SCHEMA = (
    bigquery.SchemaField("order_id", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("customer_name", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("product", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("quantity", "INTEGER", mode="REQUIRED"),
    bigquery.SchemaField("unit_price", "FLOAT", mode="REQUIRED"),
    bigquery.SchemaField("order_date", "DATE", mode="REQUIRED"),
    bigquery.SchemaField("region", "STRING", mode="REQUIRED"),
)

FIXTURE_ROWS = (
    {
        "order_id": "ORD-1001",
        "customer_name": "Northwind Foods",
        "product": "Sensor Kit",
        "quantity": 4,
        "unit_price": 129.5,
        "order_date": "2026-08-28",
        "region": "Ontario",
    },
    {
        "order_id": "ORD-1002",
        "customer_name": "Maple Retail",
        "product": "Gateway",
        "quantity": 2,
        "unit_price": 399.0,
        "order_date": "2026-08-30",
        "region": "Ontario",
    },
    {
        "order_id": "ORD-1003",
        "customer_name": "Pacific Distribution",
        "product": "Sensor Kit",
        "quantity": 8,
        "unit_price": 129.5,
        "order_date": "2026-09-01",
        "region": "British Columbia",
    },
    {
        "order_id": "ORD-1004",
        "customer_name": "Prairie Industrial",
        "product": "Edge Controller",
        "quantity": 3,
        "unit_price": 249.0,
        "order_date": "2026-09-02",
        "region": "Alberta",
    },
    {
        "order_id": "ORD-1005",
        "customer_name": "Atlantic Services",
        "product": "Gateway",
        "quantity": 1,
        "unit_price": 399.0,
        "order_date": "2026-09-04",
        "region": "Nova Scotia",
    },
)


@dataclass(frozen=True, slots=True)
class BigQueryFixtureResult:
    """Result of preparing the optional developer fixture."""

    table_id: str
    created_dataset: bool
    created_table: bool
    seeded_rows: int


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    value = raw.strip().lower()
    if value in TRUE_VALUES:
        return True
    if value in FALSE_VALUES:
        return False
    raise SystemExit(f"{name} must be true or false.")


def bigquery_fixture_enabled() -> bool:
    """Return whether developer bootstrap should prepare the BigQuery fixture."""
    return _env_bool(PREPARE_FIXTURE_ENV, True)


def _resource_id(name: str, default: str) -> str:
    value = os.getenv(name, default).strip() or default
    if not RESOURCE_ID_PATTERN.fullmatch(value):
        raise SystemExit(
            f"{name} must start with a letter or underscore and contain only letters, "
            "numbers or underscores."
        )
    return value


def _schema_signature(
    schema: Sequence[bigquery.SchemaField],
) -> tuple[tuple[str, str, str], ...]:
    return tuple((field.name, field.field_type, field.mode) for field in schema)


def _validate_existing_table(table: bigquery.Table) -> None:
    expected = _schema_signature(FIXTURE_SCHEMA)
    actual = _schema_signature(table.schema)
    if actual != expected:
        raise SystemExit(
            f"BigQuery fixture table '{table.full_table_id}' already exists with a different "
            "schema. Use another DEV_BIGQUERY_DATASET_ID/DEV_BIGQUERY_TABLE_ID or disable "
            f"{PREPARE_FIXTURE_ENV}."
        )


def prepare_bigquery_fixture(
    project_id: str,
    default_location: str,
) -> BigQueryFixtureResult | None:
    """Create or reuse a small deterministic BigQuery fixture for dev testing.

    Existing non-empty fixture tables are never modified. IAM is intentionally out
    of scope; the caller and delegated Gemini Enterprise test user must already have
    the required BigQuery permissions.
    """
    if not bigquery_fixture_enabled():
        return None

    allow_create = _env_bool(CREATE_FIXTURE_ENV, True)
    dataset_id = _resource_id(DATASET_ID_ENV, DEFAULT_DATASET_ID)
    table_id = _resource_id(TABLE_ID_ENV, DEFAULT_TABLE_ID)
    location = os.getenv(LOCATION_ENV, "").strip() or default_location

    client = bigquery.Client(project=project_id)
    dataset_ref = f"{project_id}.{dataset_id}"
    table_ref = f"{dataset_ref}.{table_id}"

    created_dataset = False
    try:
        client.get_dataset(dataset_ref)
    except NotFound:
        if not allow_create:
            raise SystemExit(
                f"BigQuery dataset '{dataset_ref}' is missing. Create it, point the fixture "
                f"to an existing dataset, or set {CREATE_FIXTURE_ENV}=true."
            ) from None
        dataset = bigquery.Dataset(dataset_ref)
        dataset.location = location
        dataset.description = FIXTURE_DESCRIPTION
        dataset.labels = {
            "managed_by": "gemini-agent-template",
            "purpose": "dev-fixture",
        }
        client.create_dataset(dataset)
        created_dataset = True

    created_table = False
    try:
        table = client.get_table(table_ref)
        _validate_existing_table(table)
    except NotFound:
        if not allow_create:
            raise SystemExit(
                f"BigQuery table '{table_ref}' is missing. Create it, point the fixture to an "
                f"existing table with the fixture schema, or set {CREATE_FIXTURE_ENV}=true."
            ) from None
        table = bigquery.Table(table_ref, schema=FIXTURE_SCHEMA)
        table.description = FIXTURE_DESCRIPTION
        table = client.create_table(table)
        created_table = True

    seeded_rows = 0
    first_row = next(iter(client.list_rows(table, max_results=1)), None)
    if first_row is None:
        errors = client.insert_rows_json(table, list(FIXTURE_ROWS))
        if errors:
            raise RuntimeError(
                f"Failed to seed BigQuery fixture table '{table_ref}': {errors}"
            )
        seeded_rows = len(FIXTURE_ROWS)

    return BigQueryFixtureResult(
        table_id=table_ref,
        created_dataset=created_dataset,
        created_table=created_table,
        seeded_rows=seeded_rows,
    )
