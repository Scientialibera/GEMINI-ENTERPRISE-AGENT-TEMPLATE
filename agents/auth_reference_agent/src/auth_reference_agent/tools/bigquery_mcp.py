"""BigQuery tools from Google's managed remote MCP server.

The same delegated user token as ``bigquery_query``, reaching the same service,
but the tools are defined by the server rather than by this repository. The
endpoint and read-only tool list are a shared asset in
``gemini_shared.mcp.mcp_google_cloud``.
"""

from __future__ import annotations

from gemini_shared.mcp.mcp_google_cloud import bigquery_readonly_toolset

from ..config import GEMINI_ENTERPRISE_AUTHORIZATION_ID, MCP_SERVER_URL

bigquery_mcp_toolset = bigquery_readonly_toolset(
    authorization_id=GEMINI_ENTERPRISE_AUTHORIZATION_ID,
    server_url=MCP_SERVER_URL,
)
