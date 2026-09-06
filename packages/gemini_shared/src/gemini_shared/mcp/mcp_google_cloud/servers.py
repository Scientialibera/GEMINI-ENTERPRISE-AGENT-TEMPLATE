"""Google's managed remote MCP servers.

Google hosts these, so an agent gets the tools without deploying anything. The
full list is at https://docs.cloud.google.com/mcp/supported-products.

Each server authenticates the caller per tool call with OAuth 2.0 and IAM, so
the delegated user token decides what a tool can reach. ``tools/list`` is not
authenticated; a missing or unscoped token fails at the call instead.
"""

from __future__ import annotations

BIGQUERY = "https://bigquery.googleapis.com/mcp"
CLOUD_LOGGING = "https://logging.googleapis.com/mcp"
CLOUD_MONITORING = "https://monitoring.googleapis.com/mcp"
CLOUD_RUN = "https://run.googleapis.com/mcp"
CLOUD_STORAGE = "https://storage.googleapis.com/storage/mcp"
COMPUTE_ENGINE = "https://compute.googleapis.com/mcp"

# Scope the delegated authorization must carry to reach the server above.
BIGQUERY_SCOPE = "https://www.googleapis.com/auth/bigquery"
CLOUD_PLATFORM_SCOPE = "https://www.googleapis.com/auth/cloud-platform"

# Read-only subset of the BigQuery server's tools. execute_sql is withheld so
# the MCP path cannot mutate data; the user's own IAM still applies on top.
BIGQUERY_READONLY_TOOLS = [
    "list_dataset_ids",
    "get_dataset_info",
    "list_table_ids",
    "get_table_info",
    "execute_sql_readonly",
]
