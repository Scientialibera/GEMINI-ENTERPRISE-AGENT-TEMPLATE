"""Remote MCP servers reached over Streamable HTTP.

Tools come from the server rather than from this repository, so adding a server
adds capability without adding tool code.

Split so one server's details never leak into the plumbing:

- ``mcp_auth``          how to authenticate to any MCP server
- ``mcp_google_cloud``  Google's managed servers: endpoints, scopes, toolsets

Add a server by adding an ``mcp_<name>`` folder beside ``mcp_google_cloud``.
Import the sub-package you need; nothing is re-exported here, so a new server
never widens this import surface.
"""
