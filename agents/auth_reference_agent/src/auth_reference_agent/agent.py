"""Reference agent for the two supported authentication patterns.

Agent Identity reads Cloud Storage with the runtime's own identity. Delegated
auth queries BigQuery with the signed-in user's forwarded token.
"""

from __future__ import annotations

import datetime
import decimal

from gemini_shared import (
    apply_runtime_model,
    delegated_auth_config,
    get_bootstrap_settings,
    get_runtime_config,
    get_runtime_config_status,
    read_delegated_token,
    runtime_instruction,
)
from gemini_shared.agent_identity import list_bucket_objects
from google.adk.agents import Agent
from google.adk.auth.auth_credential import AuthCredential
from google.adk.models import Gemini
from google.adk.tools.authenticated_function_tool import AuthenticatedFunctionTool
from google.cloud import bigquery
from google.oauth2.credentials import Credentials as OAuth2Credentials
from vertexai.agent_engines import AdkApp

BOOTSTRAP = get_bootstrap_settings(require_auth=True)
PROJECT_ID = BOOTSTRAP.project_id
GEMINI_ENTERPRISE_AUTHORIZATION_ID = BOOTSTRAP.gemini_enterprise_authorization_id
if GEMINI_ENTERPRISE_AUTHORIZATION_ID is None:
    raise RuntimeError("GEMINI_ENTERPRISE_AUTHORIZATION_ID is required for this agent.")


def template_agent_identity_tool() -> dict[str, object]:
    """List objects in the configured bucket using the agent's own identity."""
    return list_bucket_objects(PROJECT_ID)


def _delegated_bigquery_client(credential: AuthCredential) -> bigquery.Client:
    token = read_delegated_token(credential)
    if not token:
        raise ValueError("No delegated OAuth token was supplied to the tool.")
    return bigquery.Client(
        project=PROJECT_ID,
        credentials=OAuth2Credentials(token),
    )


def _discover_bigquery(client: bigquery.Client) -> dict[str, object]:
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


async def _template_bigquery_query(
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
    client = _delegated_bigquery_client(credential)
    if not sql:
        return _discover_bigquery(client)

    rows = [
        {key: _json_safe(value) for key, value in dict(row).items()}
        for row in client.query(sql).result(max_results=runtime.bigquery_query_row_limit)
    ]
    return {"row_count_returned": len(rows), "rows": rows}


template_bigquery_query_tool = AuthenticatedFunctionTool(
    func=_template_bigquery_query,
    auth_config=delegated_auth_config(GEMINI_ENTERPRISE_AUTHORIZATION_ID),
)


def template_runtime_config_tool() -> dict[str, object]:
    """Return non-sensitive metadata about the active runtime configuration."""
    return get_runtime_config_status()


root_agent = Agent(
    name="auth_reference_agent",
    model=Gemini(
        model=BOOTSTRAP.bootstrap_model,
        client_kwargs={"location": BOOTSTRAP.model_location},
    ),
    description=(
        "Reference agent demonstrating Agent Identity and Gemini Enterprise delegated auth."
    ),
    instruction=runtime_instruction,
    before_model_callback=apply_runtime_model,
    tools=[
        template_runtime_config_tool,
        template_agent_identity_tool,
        template_bigquery_query_tool,
    ],
)

# Agent Runtime serves the AdkApp wrapper; a bare Agent exposes none of the
# declared class methods. root_agent stays exported for local `adk` runs.
app = AdkApp(agent=root_agent, enable_tracing=True)
