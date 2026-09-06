"""Authentication patterns shared by every agent.

Two identities are available. Agent Identity is the runtime's own service
account, used for infrastructure the agent owns. Delegated auth carries the
signed-in user's token, so a downstream service applies that user's permissions.
"""

from .delegated import (
    GeminiEnterpriseDelegatedAuthProvider,
    GeminiEnterpriseDelegatedAuthProviderScheme,
    delegated_auth_config,
    read_session_token,
)
from .tokens import read_delegated_token

__all__ = [
    "GeminiEnterpriseDelegatedAuthProvider",
    "GeminiEnterpriseDelegatedAuthProviderScheme",
    "delegated_auth_config",
    "read_delegated_token",
    "read_session_token",
]
