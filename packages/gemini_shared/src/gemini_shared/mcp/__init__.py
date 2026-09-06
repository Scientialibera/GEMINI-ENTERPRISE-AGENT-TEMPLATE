"""Remote MCP servers reached over Streamable HTTP.

The server supplies the tools, so capability is added without writing tool code.

- ``mcp_auth``          authenticates to any MCP server; names none
- ``mcp_google_cloud``  Google's endpoints, scopes and toolsets

Add a server as an ``mcp_<name>`` folder. Import the sub-package directly;
nothing is re-exported here.
"""
