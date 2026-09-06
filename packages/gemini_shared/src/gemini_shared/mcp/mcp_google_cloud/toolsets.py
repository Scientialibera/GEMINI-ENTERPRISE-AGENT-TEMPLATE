"""Ready-made toolsets for Google's managed MCP servers."""

from __future__ import annotations

from google.adk.tools.mcp_tool.mcp_toolset import McpToolset

from ..mcp_auth import delegated_mcp_toolset
from .servers import BIGQUERY, BIGQUERY_READONLY_TOOLS


def bigquery_readonly_toolset(
    *,
    authorization_id: str,
    server_url: str = BIGQUERY,
    tool_name_prefix: str = "bq_mcp",
) -> McpToolset:
    """Return read-only BigQuery tools called as the signed-in user.

    Args:
        authorization_id: Gemini Enterprise authorization supplying the token.
            Its scopes must include ``BIGQUERY_SCOPE``.
        server_url: Override only to reach a different BigQuery MCP endpoint.
        tool_name_prefix: Keeps these names distinct from local tools.
    """
    return delegated_mcp_toolset(
        server_url=server_url,
        authorization_id=authorization_id,
        tool_filter=BIGQUERY_READONLY_TOOLS,
        tool_name_prefix=tool_name_prefix,
    )
