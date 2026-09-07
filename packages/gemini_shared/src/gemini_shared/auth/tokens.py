"""Read access tokens from ADK credentials."""

from __future__ import annotations

from google.adk.auth.auth_credential import AuthCredential


def read_delegated_token(credential: AuthCredential) -> str | None:
    """Return the access token carried by a delegated credential."""
    if credential.oauth2 and credential.oauth2.access_token:
        return credential.oauth2.access_token
    if credential.http and credential.http.credentials:
        return credential.http.credentials.token
    return None
