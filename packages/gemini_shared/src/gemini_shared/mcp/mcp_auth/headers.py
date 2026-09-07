"""Build MCP headers per request to keep tokens scoped to the current user."""

from __future__ import annotations

from collections.abc import Callable

from google.adk.agents.readonly_context import ReadonlyContext

from ...auth.delegated import read_session_token

AUTHORIZATION_HEADER = "Authorization"


def delegated_bearer_headers(
    authorization_id: str,
) -> Callable[[ReadonlyContext], dict[str, str]]:
    """Build a header provider using the current user's session token."""

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
