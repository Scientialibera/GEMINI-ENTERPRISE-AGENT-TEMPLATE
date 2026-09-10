"""Managed Google Cloud MCP endpoints, OAuth scopes and tool allowlists."""

from __future__ import annotations

# Endpoint constants do not imply a tested integration; verify service docs first.
BIGQUERY = "https://bigquery.googleapis.com/mcp"
CLOUD_LOGGING = "https://logging.googleapis.com/mcp"
CLOUD_MONITORING = "https://monitoring.googleapis.com/mcp"
CLOUD_RUN = "https://run.googleapis.com/mcp"
CLOUD_STORAGE = "https://storage.googleapis.com/storage/mcp"
COMPUTE_ENGINE = "https://compute.googleapis.com/mcp"

# Scope the delegated authorization must carry to reach the server above.
BIGQUERY_SCOPE = "https://www.googleapis.com/auth/bigquery"
CLOUD_PLATFORM_SCOPE = "https://www.googleapis.com/auth/cloud-platform"

# Exclude execute_sql; server-side IAM still controls access.
BIGQUERY_READONLY_TOOLS = [
    "list_dataset_ids",
    "get_dataset_info",
    "list_table_ids",
    "get_table_info",
    "execute_sql_readonly",
]
