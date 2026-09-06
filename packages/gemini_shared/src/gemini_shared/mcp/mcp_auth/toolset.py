"""Connect an agent to a remote MCP server over Streamable HTTP.

The server URL is runtime configuration, so pointing an agent at a different
MCP server is a Terraform apply rather than a redeploy. Nothing here assumes a
self-hosted server: Google publishes managed endpoints such as
``https://bigquery.googleapis.com/mcp``.
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
        tool_filter: Tool names to expose. Omit to expose everything the server
            offers, which also means new server-side tools appear unannounced.
        tool_name_prefix: Prefix distinguishing these tools from local ones.
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
