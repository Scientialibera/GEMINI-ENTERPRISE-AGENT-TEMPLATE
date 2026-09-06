"""How an agent authenticates to any MCP server.

Server-agnostic: nothing here names a particular server. A folder per server
sits alongside this one and supplies the endpoint and tool list.
"""

from .headers import delegated_bearer_headers
from .toolset import delegated_mcp_toolset

__all__ = ["delegated_bearer_headers", "delegated_mcp_toolset"]
