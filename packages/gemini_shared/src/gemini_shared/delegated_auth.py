"""Gemini Enterprise delegated user authentication.

Gemini Enterprise runs the OAuth consent flow and forwards the resulting user
token in ADK session state. This scheme and provider read that token so a tool
can call a downstream service with the signed-in user's own permissions.

Importing this module registers the provider. ADK rehydrates a deployed scheme
by matching ``type_`` against ``CustomAuthScheme.__subclasses__()``, so the
module must be imported before a tool using the scheme runs. Agents get that by
importing ``delegated_auth_config`` from ``gemini_shared``.
"""

from __future__ import annotations

from typing import Literal, override

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

        state = context.session.state
        if auth_scheme.name and auth_scheme.name in state:
            token = state[auth_scheme.name]
        elif len(state) == 1:
            token = next(iter(state.values()))
        else:
            raise ValueError("No matching Gemini Enterprise authorization found in session state.")

        return AuthCredential(
            auth_type=AuthCredentialTypes.OAUTH2,
            oauth2=OAuth2Auth(access_token=token),
        )


def read_delegated_token(credential: AuthCredential) -> str | None:
    """Return the access token carried by a delegated credential."""
    if credential.oauth2 and credential.oauth2.access_token:
        return credential.oauth2.access_token
    if credential.http and credential.http.credentials:
        return credential.http.credentials.token
    return None


def delegated_auth_config(authorization_id: str) -> AuthConfig:
    """Return the AuthConfig for a tool using the delegated user token."""
    return AuthConfig(
        auth_scheme=GeminiEnterpriseDelegatedAuthProviderScheme(name=authorization_id)
    )


CredentialManager.register_auth_provider(GeminiEnterpriseDelegatedAuthProvider())
