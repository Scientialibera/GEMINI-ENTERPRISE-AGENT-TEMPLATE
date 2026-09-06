"""Query BigQuery with the signed-in user's delegated credentials."""

from __future__ import annotations

import datetime
import decimal

from gemini_shared import delegated_auth_config, get_runtime_config, read_delegated_token
from google.adk.auth.auth_credential import AuthCredential
from google.adk.tools.authenticated_function_tool import AuthenticatedFunctionTool
from google.cloud import bigquery
from google.oauth2.credentials import Credentials as OAuth2Credentials

from ..config import GEMINI_ENTERPRISE_AUTHORIZATION_ID, PROJECT_ID


def _delegated_client(credential: AuthCredential) -> bigquery.Client:
    token = read_delegated_token(credential)
    if not token:
        raise ValueError("No delegated OAuth token was supplied to the tool.")
    return bigquery.Client(project=PROJECT_ID, credentials=OAuth2Credentials(token))


def _discover(client: bigquery.Client) -> dict[str, object]:
    datasets: list[dict[str, object]] = []
    for dataset in client.list_datasets():
        tables: list[dict[str, object]] = []
        for table_ref in client.list_tables(dataset.dataset_id):
            table = client.get_table(table_ref.reference)
            tables.append(
                {
                    "table": f"{PROJECT_ID}.{dataset.dataset_id}.{table_ref.table_id}",
                    "row_count": table.num_rows,
                    "columns": [
                        {"name": field.name, "type": field.field_type} for field in table.schema
                    ],
                }
            )
        datasets.append({"dataset": dataset.dataset_id, "tables": tables})
    return {"project": PROJECT_ID, "datasets": datasets}


def _json_safe(value: object) -> object:
    """Convert BigQuery values the tool protocol cannot serialize."""
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_json_safe(item) for item in value]
    if isinstance(value, datetime.date | datetime.datetime | datetime.time):
        return value.isoformat()
    if isinstance(value, decimal.Decimal):
        return float(value)
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


async def query_bigquery(
    credential: AuthCredential,
    sql: str | None = None,
) -> dict[str, object]:
    """Query BigQuery as the signed-in user, using their delegated credentials.

    Call without `sql` first to discover the datasets, tables and columns that
    the user is authorized to see, then call again with a SQL statement built
    from that schema. Results are truncated to the configured row limit.

    Args:
        sql: BigQuery Standard SQL to run. Omit to return the schema instead.
    """
    runtime = get_runtime_config()
    client = _delegated_client(credential)
    if not sql:
        return _discover(client)

    rows = [
        {key: _json_safe(value) for key, value in dict(row).items()}
        for row in client.query(sql).result(max_results=runtime.bigquery_query_row_limit)
    ]
    return {"row_count_returned": len(rows), "rows": rows}


bigquery_query_tool = AuthenticatedFunctionTool(
    func=query_bigquery,
    auth_config=delegated_auth_config(GEMINI_ENTERPRISE_AUTHORIZATION_ID),
)
