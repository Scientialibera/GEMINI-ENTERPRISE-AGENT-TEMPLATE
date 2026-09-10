"""Register a deployed runtime in Gemini Enterprise and configure delegated authorization."""

from __future__ import annotations

import sys
from pathlib import Path

# Runnable directly as well as imported by release_dev.py, so dev/ has to be
# on sys.path either way: running this file puts only its own folder there.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import argparse
import os
import urllib.parse

import requests
from config.settings import load_environment, require_dev_environment
from deploy.state import load_resource_name
from gcp import project_number as _project_number
from gemini_shared.config.bootstrap import AUTHORIZATION_ID_ENV
from paths import ROOT
from registry import AgentSpec, detect_delegated_auth, get_agent_spec

from register.http import REQUEST_TIMEOUT_SECONDS, iter_resources
from register.http import request as _request
from register.oauth import OAUTH_CLIENTS_ENV, oauth_client_id_for

DISCOVERY_ENGINE_HOST = "https://discoveryengine.googleapis.com"
DISCOVERY_ENGINE_VERSION = "v1alpha"
DISCOVERY_ENGINE_LOCATION = "global"
DEFAULT_COLLECTION = "default_collection"
DEFAULT_ASSISTANT = "default_assistant"

APP_ENGINE_ID_ENV = "GEMINI_ENTERPRISE_APP_ID"
OAUTH_CLIENT_ID_ENV = "GEMINI_ENTERPRISE_OAUTH_CLIENT_ID"
OAUTH_CLIENT_SECRET_ENV = "GEMINI_ENTERPRISE_OAUTH_CLIENT_SECRET"
OAUTH_CLIENT_SECRET_NAME_ENV = "GEMINI_ENTERPRISE_OAUTH_CLIENT_SECRET_NAME"
AGENT_STATE_ENABLED = "ENABLED"
CLOUD_PLATFORM_SCOPE = "https://www.googleapis.com/auth/cloud-platform"

OAUTH_AUTHORIZATION_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
OAUTH_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
# Register both callbacks: the authorization and consent flow use different URIs.
OAUTH_REDIRECT_URI = "https://vertexaisearch.cloud.google.com/static/oauth/oauth.html"
OAUTH_CONSENT_REDIRECT_URI = "https://vertexaisearch.cloud.google.com/oauth-redirect"
OAUTH_REDIRECT_URIS = (OAUTH_REDIRECT_URI, OAUTH_CONSENT_REDIRECT_URI)


def _assistant_path(project_id: str, app_id: str) -> str:
    return (
        f"projects/{project_id}/locations/{DISCOVERY_ENGINE_LOCATION}"
        f"/collections/{DEFAULT_COLLECTION}/engines/{app_id}"
        f"/assistants/{DEFAULT_ASSISTANT}"
    )


def _agents_url(project_id: str, app_id: str) -> str:
    return (
        f"{DISCOVERY_ENGINE_HOST}/{DISCOVERY_ENGINE_VERSION}/"
        f"{_assistant_path(project_id, app_id)}/agents"
    )


def _build_agent(spec: AgentSpec, reasoning_engine: str, project_id: str) -> dict[str, object]:
    agent: dict[str, object] = {
        "displayName": spec.display_name,
        "description": spec.registration_description,
        "adkAgentDefinition": {
            "provisionedReasoningEngine": {"reasoningEngine": reasoning_engine},
            "toolSettings": {},
        },
        "state": AGENT_STATE_ENABLED,
    }
    if spec.starter_prompts:
        agent["starterPrompts"] = [{"text": prompt} for prompt in spec.starter_prompts]
    if spec.invocation_description:
        agent["agentInvocationSpec"] = {"description": spec.invocation_description}

    authorization_id = os.getenv(AUTHORIZATION_ID_ENV, "").strip()
    if AUTHORIZATION_ID_ENV in spec.required_remote_bootstrap_env:
        if not authorization_id:
            raise SystemExit(
                f"{spec.display_name} requires {AUTHORIZATION_ID_ENV}. Its delegated tools "
                "cannot receive a user token without a Gemini Enterprise authorization."
            )
        # Authorization names must use the project number, not the project id.
        agent["authorizationConfig"] = {
            "toolAuthorizations": [
                f"projects/{_project_number(project_id)}/locations/{DISCOVERY_ENGINE_LOCATION}"
                f"/authorizations/{authorization_id}"
            ]
        }
    return agent


def _resolve_client_secret(project_id: str, spec: AgentSpec) -> str:
    """Read Secret Manager first; import an environment secret if missing."""
    secret_name = (
        os.getenv(spec.oauth_client_secret_name_env, "").strip()
        or os.getenv(OAUTH_CLIENT_SECRET_NAME_ENV, "").strip()
    )
    if not secret_name:
        secret_name = spec.default_oauth_secret_name

    resource = (
        secret_name
        if secret_name.startswith("projects/")
        else f"projects/{project_id}/secrets/{secret_name}/versions/latest"
    )
    if "/versions/" not in resource:
        resource = f"{resource}/versions/latest"

    from google.api_core.exceptions import NotFound
    from google.cloud import secretmanager

    client = secretmanager.SecretManagerServiceClient()
    try:
        return client.access_secret_version(name=resource).payload.data.decode("utf-8").strip()
    except NotFound:
        pass

    # Import the initial secret from the environment.
    supplied = (
        os.getenv(spec.oauth_client_secret_env, "").strip()
        or os.getenv(OAUTH_CLIENT_SECRET_ENV, "").strip()
    )
    if not supplied:
        # Let the caller print the setup instructions.
        return ""

    _store_client_secret(project_id, secret_name.rsplit("/", 1)[-1], supplied)
    return supplied


def _verify_client_credentials(client_id: str, client_secret: str, spec: AgentSpec) -> None:
    """Probe for invalid_client using a deliberately invalid authorization code."""
    response = requests.post(
        OAUTH_TOKEN_ENDPOINT,
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "grant_type": "authorization_code",
            "code": "credential-pair-probe",
            "redirect_uri": OAUTH_CONSENT_REDIRECT_URI,
        },
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    if response.json().get("error") != "invalid_client":
        return

    raise SystemExit(
        f"The OAuth client secret configured for {spec.display_name} does not belong to its "
        f"client id.\n\n"
        f"  client id: {client_id}\n"
        f"  secret   : Secret Manager '{spec.default_oauth_secret_name}'\n\n"
        "Update the configured Secret Manager secret with the matching client secret, "
        "then rerun registration. Stored secrets take precedence over environment values.\n"
    )


def _store_client_secret(project_id: str, secret_id: str, value: str) -> None:
    """Create the Secret Manager secret holding an OAuth client secret."""
    import contextlib

    from google.api_core.exceptions import AlreadyExists
    from google.cloud import secretmanager

    client = secretmanager.SecretManagerServiceClient()
    parent = f"projects/{project_id}"
    # A rotated secret reuses the existing container and adds a version.
    with contextlib.suppress(AlreadyExists):
        client.create_secret(
            parent=parent,
            secret_id=secret_id,
            secret={"replication": {"automatic": {}}},
        )
    client.add_secret_version(
        parent=f"{parent}/secrets/{secret_id}",
        payload={"data": value.encode("utf-8")},
    )
    print(f"OAUTH_CLIENT_SECRET_STORED={secret_id}")


def _authorizations_url(project_id: str) -> str:
    return (
        f"{DISCOVERY_ENGINE_HOST}/{DISCOVERY_ENGINE_VERSION}/projects/{project_id}"
        f"/locations/{DISCOVERY_ENGINE_LOCATION}/authorizations"
    )


def _authorization_exists(project_id: str, authorization_id: str) -> bool:
    for authorization in iter_resources(
        _authorizations_url(project_id), project_id, "authorizations"
    ):
        if str(authorization.get("name", "")).rsplit("/", 1)[-1] == authorization_id:
            return True
    return False


def ensure_authorization(
    project_id: str, authorization_id: str, agent_name: str, spec: AgentSpec
) -> None:
    """Create the agent's authorization if it is missing."""
    if _authorization_exists(project_id, authorization_id):
        print(f"AUTHORIZATION_EXISTS={authorization_id}")
        return

    client_id = oauth_client_id_for(agent_name, spec) or os.getenv(OAUTH_CLIENT_ID_ENV, "").strip()
    client_secret = _resolve_client_secret(project_id, spec)
    if not client_id or not client_secret:
        raise SystemExit(
            f"{spec.display_name} needs its own OAuth client to create authorization "
            f"'{authorization_id}'.\n\n"
            "In the Google Cloud console, create an OAuth client with:\n"
            "  Application type: Web application\n"
            f"  Name: {spec.oauth_client_name}\n"
            "  Authorized redirect URIs (add both; the consent flow uses the second):\n"
            + "".join(f"    {uri}\n" for uri in OAUTH_REDIRECT_URIS)
            + "\n"
            "The consent screen must allow the scopes this agent requests:\n"
            + "".join(f"  {scope}\n" for scope in spec.oauth_scopes)
            + "\n"
            "Then put its id and secret in dev/.env.dev and run this again:\n"
            f"  {OAUTH_CLIENTS_ENV}={agent_name}=<the new client id>"
            "   (comma-separated; keep any existing entries)\n"
            f"  {spec.oauth_client_secret_env}=<the new client secret>\n\n"
            f"The secret is copied into Secret Manager as "
            f"'{spec.default_oauth_secret_name}' on that run and read from there afterwards, so "
            "it can then be removed from dev/.env.dev.\n"
        )

    _verify_client_credentials(client_id, client_secret, spec)

    scope_value = urllib.parse.quote(" ".join(spec.oauth_scopes))
    redirect_value = urllib.parse.quote(OAUTH_REDIRECT_URI, safe="")
    authorization_uri = (
        f"{OAUTH_AUTHORIZATION_ENDPOINT}?client_id={client_id}"
        f"&redirect_uri={redirect_value}&scope={scope_value}"
        "&include_granted_scopes=true&response_type=code&access_type=offline&prompt=consent"
    )

    url = f"{_authorizations_url(project_id)}?authorizationId={authorization_id}"
    _request(
        "POST",
        url,
        project_id,
        {
            "name": (
                f"projects/{_project_number(project_id)}/locations/"
                f"{DISCOVERY_ENGINE_LOCATION}/authorizations/{authorization_id}"
            ),
            "serverSideOauth2": {
                "clientId": client_id,
                "clientSecret": client_secret,
                "authorizationUri": authorization_uri,
                "tokenUri": OAUTH_TOKEN_ENDPOINT,
            },
        },
    )
    print(f"AUTHORIZATION_CREATED={authorization_id}")


def _find_existing(project_id: str, app_id: str, display_name: str) -> str | None:
    for agent in iter_resources(_agents_url(project_id, app_id), project_id, "agents"):
        if agent.get("displayName") == display_name:
            return str(agent.get("name"))
    return None


def register_agent(
    agent_name: str,
    app_id: str,
    project_id: str,
    spec: AgentSpec,
    reasoning_engine: str,
) -> str:
    """Create or update the app registration for this runtime."""

    # Catch undeclared delegated tools before registration.
    if detect_delegated_auth(spec) and not spec.uses_delegated_auth:
        raise SystemExit(
            f"{spec.display_name} uses delegated auth in its source but its AgentSpec does not "
            f"declare it. Add {AUTHORIZATION_ID_ENV} to required_remote_bootstrap_env in "
            "dev/registry.py, so the agent is deployed with an authorization and its own OAuth "
            "client."
        )

    authorization_id = os.getenv(AUTHORIZATION_ID_ENV, "").strip()
    if spec.uses_delegated_auth and authorization_id:
        ensure_authorization(project_id, authorization_id, agent_name, spec)

    agent = _build_agent(spec, reasoning_engine, project_id)

    existing = _find_existing(project_id, app_id, spec.display_name)
    if existing:
        url = f"{DISCOVERY_ENGINE_HOST}/{DISCOVERY_ENGINE_VERSION}/{existing}"
        result = _request("PATCH", url, project_id, agent)
        print(f"UPDATED_AGENT={result.get('name')}")
    else:
        result = _request("POST", _agents_url(project_id, app_id), project_id, agent)
        print(f"REGISTERED_AGENT={result.get('name')}")
    return str(result.get("name"))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Register a deployed Agent Engine in a Gemini Enterprise app."
    )
    parser.add_argument("--agent", required=True)
    parser.add_argument(
        "--app-id",
        default=None,
        help=f"Gemini Enterprise app (engine) id. Defaults to ${APP_ENGINE_ID_ENV}.",
    )
    args = parser.parse_args()

    os.chdir(ROOT)
    load_environment(".env.dev")
    # Resolve the authorization ID; registration does not read runtime settings.
    spec = get_agent_spec(args.agent)
    project_id, location, _ = require_dev_environment(require_parameter=False, spec=spec)

    app_id = (args.app_id or os.getenv(APP_ENGINE_ID_ENV, "")).strip()
    if not app_id:
        raise SystemExit(
            f"Set {APP_ENGINE_ID_ENV} in dev/.env.dev or pass --app-id. This is the Gemini "
            "Enterprise app id, not the web app client id in the console URL."
        )

    reasoning_engine = load_resource_name(args.agent, project_id, location)
    register_agent(args.agent, app_id, project_id, spec, reasoning_engine)
    print(f"REASONING_ENGINE={reasoning_engine}")


if __name__ == "__main__":
    main()
