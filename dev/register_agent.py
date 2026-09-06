"""Register a deployed Agent Engine as an agent in a Gemini Enterprise app.

Deployment and registration are separate. `deploy_dev.py` creates the Agent
Engine; registration publishes it into an app and enables the OAuth consent
flow that forwards a delegated user token to authenticated tools.

Idempotent: an agent with the same display name is patched, not duplicated.
"""

from __future__ import annotations

import argparse
import os
import urllib.parse

import google.auth
import google.auth.transport.requests
import requests
from common import (
    AUTHORIZATION_ID_ENV,
    OAUTH_CLIENTS_ENV,
    ROOT,
    AgentSpec,
    detect_delegated_auth,
    get_agent_spec,
    load_environment,
    load_resource_name,
    oauth_client_id_for,
    require_dev_environment,
)

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
REQUEST_TIMEOUT_SECONDS = 60

OAUTH_AUTHORIZATION_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
OAUTH_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
# Where Google returns the user after consent. Gemini Enterprise's own
# callbacks, so they are the same for every agent and every scope.
#
# The client must register BOTH. The authorization resource stores the first,
# but the live consent flow redirects to the second, and a client missing it
# fails with redirect_uri_mismatch once the user clicks Authorize.
OAUTH_REDIRECT_URI = "https://vertexaisearch.cloud.google.com/static/oauth/oauth.html"
OAUTH_CONSENT_REDIRECT_URI = "https://vertexaisearch.cloud.google.com/oauth-redirect"
OAUTH_REDIRECT_URIS = (OAUTH_REDIRECT_URI, OAUTH_CONSENT_REDIRECT_URI)


def _access_token() -> str:
    """Return an OAuth token for the developer's Application Default Credentials."""
    credentials, _ = google.auth.default(scopes=[CLOUD_PLATFORM_SCOPE])
    credentials.refresh(google.auth.transport.requests.Request())
    return credentials.token


def _request(
    method: str,
    url: str,
    project_id: str,
    payload: dict[str, object] | None = None,
) -> dict[str, object]:
    response = requests.request(
        method,
        url,
        json=payload,
        headers={
            "Authorization": f"Bearer {_access_token()}",
            # Discovery Engine rejects bare user ADC without an explicit quota project.
            "X-Goog-User-Project": project_id,
        },
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    if not response.ok:
        raise SystemExit(f"{method} {url} failed with HTTP {response.status_code}: {response.text}")
    return response.json() if response.content else {}


def _project_number(project_id: str) -> str:
    """Resolve a project id to its number, which authorization names require."""
    response = _request(
        "GET",
        f"https://cloudresourcemanager.googleapis.com/v1/projects/{project_id}",
        project_id,
    )
    number = response.get("projectNumber")
    if not number:
        raise SystemExit(f"Could not resolve the project number for '{project_id}'.")
    return str(number)


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
    """Return the OAuth client secret, preferring Secret Manager over the environment.

    Secret Manager keeps the payload off developer workstations. The agent's own
    secret name is used unless the environment overrides it for a single run.
    """
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

    # Not stored yet. A value supplied for this run is copied into Secret
    # Manager, so the workstation holds it only until the first registration.
    supplied = (
        os.getenv(spec.oauth_client_secret_env, "").strip()
        or os.getenv(OAUTH_CLIENT_SECRET_ENV, "").strip()
    )
    if not supplied:
        # The caller reports what to create, naming the client and this secret,
        # rather than surfacing a bare 404.
        return ""

    _store_client_secret(project_id, secret_name.rsplit("/", 1)[-1], supplied)
    return supplied


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
    listing = _request("GET", _authorizations_url(project_id), project_id)
    for authorization in listing.get("authorizations", []) or []:
        if str(authorization.get("name", "")).rsplit("/", 1)[-1] == authorization_id:
            return True
    return False


def ensure_authorization(
    project_id: str, authorization_id: str, agent_name: str, spec: AgentSpec
) -> None:
    """Create the Gemini Enterprise authorization when it does not exist.

    One authorization serves one agent, and one OAuth client backs one
    authorization: Gemini Enterprise caches the user's consent per OAuth
    client, so two agents sharing a client share a grant and the second never
    receives a token of its own.
    """
    if _authorization_exists(project_id, authorization_id):
        print(f"AUTHORIZATION_EXISTS={authorization_id}")
        return

    client_id = oauth_client_id_for(agent_name, spec) or os.getenv(
        OAUTH_CLIENT_ID_ENV, ""
    ).strip()
    client_secret = _resolve_client_secret(project_id, spec)
    if not client_id or not client_secret:
        raise SystemExit(
            f"{spec.display_name} needs its own OAuth client to create authorization "
            f"'{authorization_id}'. Gemini Enterprise caches the user's consent per OAuth "
            "client, so an agent sharing another agent's client never receives a token of its "
            "own.\n\n"
            "OAuth clients cannot be created from the CLI. In the Google Cloud console, under "
            "APIs & Services > Credentials, create an OAuth client with:\n"
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
    listing = _request("GET", _agents_url(project_id, app_id), project_id)
    for agent in listing.get("agents", []) or []:
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
    """Publish a deployed Reasoning Engine into a Gemini Enterprise app.

    Creates the delegated-auth authorization first when the agent needs one.
    """

    # The agent's source is the authority on whether it needs a delegated
    # token, so a tool added without updating the spec is caught here rather
    # than at the first user prompt.
    if detect_delegated_auth(spec) and not spec.uses_delegated_auth:
        raise SystemExit(
            f"{spec.display_name} uses delegated auth in its source but its AgentSpec does not "
            f"declare it. Add {AUTHORIZATION_ID_ENV} to required_remote_bootstrap_env in "
            "dev/common.py, so the agent is deployed with an authorization and its own OAuth "
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
    # Registration points Gemini Enterprise at an existing runtime and never
    # reads live configuration, so no config parameter is required here. The
    # spec still resolves the agent's own authorization.
    spec = get_agent_spec(args.agent)
    project_id, _, _ = require_dev_environment(require_parameter=False, spec=spec)

    app_id = (args.app_id or os.getenv(APP_ENGINE_ID_ENV, "")).strip()
    if not app_id:
        raise SystemExit(
            f"Set {APP_ENGINE_ID_ENV} in dev/.env.dev or pass --app-id. This is the Gemini "
            "Enterprise app id, not the web app client id in the console URL."
        )

    reasoning_engine = load_resource_name(args.agent)
    register_agent(args.agent, app_id, project_id, spec, reasoning_engine)
    print(f"REASONING_ENGINE={reasoning_engine}")


if __name__ == "__main__":
    main()
