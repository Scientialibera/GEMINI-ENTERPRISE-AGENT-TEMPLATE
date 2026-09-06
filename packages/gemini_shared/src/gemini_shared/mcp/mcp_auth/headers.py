"""Build the Authorization header an MCP server receives.

``McpToolset`` calls the header provider on every tool call, so the header is
built per request and a token is never cached across users.
"""

from __future__ import annotations

from collections.abc import Callable

from google.adk.agents.readonly_context import ReadonlyContext

from ...auth.delegated import read_session_token

AUTHORIZATION_HEADER = "Authorization"


def delegated_bearer_headers(
    authorization_id: str,
) -> Callable[[ReadonlyContext], dict[str, str]]:
    """Return a header provider that sends the signed-in user's token.

    The MCP server then applies that user's own permissions, so two users
    calling the same tool see only the data each is entitled to.
    """

    def provider(readonly_context: ReadonlyContext) -> dict[str, str]:
        token = read_session_token(readonly_context.state, authorization_id)
        if not token:
            raise ValueError(
                f"No delegated token for authorization '{authorization_id}'. Confirm the "
                "authorization is attached to the agent in Gemini Enterprise and that the "
                "user has completed consent."
            )
        return {AUTHORIZATION_HEADER: f"Bearer {token}"}

    return provider
