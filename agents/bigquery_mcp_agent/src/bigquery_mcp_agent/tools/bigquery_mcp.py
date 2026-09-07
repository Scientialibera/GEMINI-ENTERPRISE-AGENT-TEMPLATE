"""Configure read-only BigQuery MCP tools with delegated user authentication."""

from __future__ import annotations

from gemini_shared.mcp.mcp_google_cloud import bigquery_readonly_toolset

from ..config import GEMINI_ENTERPRISE_AUTHORIZATION_ID, MCP_SERVER_URL

bigquery_mcp_toolset = bigquery_readonly_toolset(
    authorization_id=GEMINI_ENTERPRISE_AUTHORIZATION_ID,
    server_url=MCP_SERVER_URL,
)
