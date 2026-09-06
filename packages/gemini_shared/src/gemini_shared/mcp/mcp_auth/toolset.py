"""Connect an agent to a remote MCP server over Streamable HTTP.

The server supplies the tools, so none are defined here. Works against any
Streamable HTTP endpoint, including Google's managed servers such as
``https://bigquery.googleapis.com/mcp``.

The URL is bootstrap env: the toolset is built at construction, so changing it
needs a redeploy.
"""

from __future__ import annotations

from google.adk.tools.mcp_tool.mcp_session_manager import StreamableHTTPConnectionParams
from google.adk.tools.mcp_tool.mcp_toolset import McpToolset

from .headers import delegated_bearer_headers

DEFAULT_TIMEOUT_SECONDS = 30.0
# The server's tool list is stable; re-listing on every turn adds a round trip.
DEFAULT_TOOL_LIST_CACHE_SECONDS = 300.0


def delegated_mcp_toolset(
    *,
    server_url: str,
    authorization_id: str,
    tool_filter: list[str] | None = None,
    tool_name_prefix: str | None = None,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    tool_list_cache_ttl_seconds: float | None = DEFAULT_TOOL_LIST_CACHE_SECONDS,
) -> McpToolset:
    """Return a toolset that calls an MCP server as the signed-in user.

    Args:
        server_url: Streamable HTTP endpoint of the MCP server.
        authorization_id: Gemini Enterprise authorization supplying the token.
        tool_filter: Client-side allowlist of tool names. ADK discards the rest
            before the model sees them. Omit and every server tool is exposed,
            including ones the server adds later.
        tool_name_prefix: Prefix keeping these names distinct from local tools.
        timeout_seconds: Per-request timeout.
        tool_list_cache_ttl_seconds: How long to reuse the server's tool list.
    """
    return McpToolset(
        connection_params=StreamableHTTPConnectionParams(
            url=server_url,
            timeout=timeout_seconds,
        ),
        header_provider=delegated_bearer_headers(authorization_id),
        tool_filter=tool_filter,
        tool_name_prefix=tool_name_prefix,
        tool_list_cache_ttl_seconds=tool_list_cache_ttl_seconds,
    )
