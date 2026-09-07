"""Read Gemini Enterprise user tokens from ADK session state.

Importing this module registers the provider needed to rehydrate deployed auth schemes."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal, override

from google.adk.agents.callback_context import CallbackContext
from google.adk.auth.auth_credential import AuthCredential, AuthCredentialTypes, OAuth2Auth
from google.adk.auth.auth_schemes import CustomAuthScheme
from google.adk.auth.auth_tool import AuthConfig
from google.adk.auth.base_auth_provider import BaseAuthProvider
from google.adk.auth.credential_manager import CredentialManager
from pydantic import Field

SCHEME_TYPE = "GeminiEnterpriseDelegatedAuthProviderScheme"


class GeminiEnterpriseDelegatedAuthProviderScheme(CustomAuthScheme):
    """Auth scheme for the token forwarded by Gemini Enterprise."""

    type_: Literal["GeminiEnterpriseDelegatedAuthProviderScheme"] = Field(
        default=SCHEME_TYPE,
        alias="type",
    )
    name: str | None = None


class GeminiEnterpriseDelegatedAuthProvider(BaseAuthProvider):
    """Read a delegated OAuth token from the ADK session state."""

    @property
    @override
    def supported_auth_schemes(
        self,
    ) -> tuple[type[GeminiEnterpriseDelegatedAuthProviderScheme], ...]:
        return (GeminiEnterpriseDelegatedAuthProviderScheme,)

    @override
    async def get_auth_credential(
        self,
        auth_config: AuthConfig,
        context: CallbackContext | None,
    ) -> AuthCredential:
        auth_scheme = auth_config.auth_scheme
        if not isinstance(auth_scheme, GeminiEnterpriseDelegatedAuthProviderScheme):
            raise ValueError(
                f"Expected GeminiEnterpriseDelegatedAuthProviderScheme, got {type(auth_scheme)}"
            )
        if context is None or context.session is None:
            raise ValueError(
                "Gemini Enterprise delegated auth requires a context with a valid session."
            )

        token = read_session_token(context.session.state, auth_scheme.name)
        if token is None:
            raise ValueError("No matching Gemini Enterprise authorization found in session state.")

        return AuthCredential(
            auth_type=AuthCredentialTypes.OAUTH2,
            oauth2=OAuth2Auth(access_token=token),
        )


def read_session_token(state: Mapping[str, Any], authorization_id: str | None) -> str | None:
    """Read the named authorization token, with a single-entry session fallback."""
    if authorization_id and authorization_id in state:
        return state[authorization_id]
    if len(state) == 1:
        return next(iter(state.values()))
    return None


def delegated_auth_config(authorization_id: str) -> AuthConfig:
    """Return the AuthConfig for a tool using the delegated user token."""
    return AuthConfig(
        auth_scheme=GeminiEnterpriseDelegatedAuthProviderScheme(name=authorization_id)
    )


CredentialManager.register_auth_provider(GeminiEnterpriseDelegatedAuthProvider())
