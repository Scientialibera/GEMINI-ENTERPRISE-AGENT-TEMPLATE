"""Runtime shared by every agent in the monorepo.

Organized by concern:

- ``auth``       identities: the runtime's own, and the signed-in user's
- ``config``     bootstrap environment and live runtime configuration
- ``connectors`` clients for Google Cloud services
- ``mcp``        remote MCP servers reached over Streamable HTTP

Only ``auth`` and ``config`` are re-exported here, because every agent needs
them. ``connectors`` and ``mcp`` each require a client library that not every
agent ships, so import those modules directly.
"""

from .auth import (
    GeminiEnterpriseDelegatedAuthProvider,
    GeminiEnterpriseDelegatedAuthProviderScheme,
    delegated_auth_config,
    read_delegated_token,
    read_session_token,
)
from .config import (
    BootstrapSettings,
    RuntimeConfig,
    apply_runtime_model,
    get_bootstrap_settings,
    get_runtime_config,
    get_runtime_config_status,
    runtime_instruction,
)

__all__ = [
    "BootstrapSettings",
    "GeminiEnterpriseDelegatedAuthProvider",
    "GeminiEnterpriseDelegatedAuthProviderScheme",
    "RuntimeConfig",
    "apply_runtime_model",
    "delegated_auth_config",
    "get_bootstrap_settings",
    "get_runtime_config",
    "get_runtime_config_status",
    "read_delegated_token",
    "read_session_token",
    "runtime_instruction",
]
