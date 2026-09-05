"""Template pro-code ADK agent demonstrating two authentication patterns.

Copy this repo as a starting point for a new pro-code agent. Each tool below
is a working, runnable example of one identity pattern; swap the body for
real logic and keep the auth wiring.

Patterns demonstrated:
- template_agent_identity_tool       Agent Identity (the runtime's own credentials)
- template_bigquery_query_tool       Gemini Enterprise's forwarded delegated token

Everything lives in this one file, including auth provider registration.
ADK's credential registry keys registered providers by Python class object
identity, and Agent Runtime's packaging makes it easy to end up importing
the same class through two different module paths if it lives in a
separate file — which silently breaks the registry lookup with a
"No auth provider registered for custom auth scheme" error that only
shows up on the deployed runtime, not locally. Keep it inline.
"""

import datetime
import decimal
import os

from google.adk.agents import Agent
from google.adk.agents.callback_context import CallbackContext
from google.adk.agents.readonly_context import ReadonlyContext
from google.adk.auth.auth_credential import AuthCredential
from google.adk.auth.auth_credential import AuthCredentialTypes
from google.adk.auth.auth_credential import OAuth2Auth
from google.adk.auth.auth_schemes import CustomAuthScheme
from google.adk.auth.auth_tool import AuthConfig
from google.adk.auth.base_auth_provider import BaseAuthProvider
from google.adk.auth.credential_manager import CredentialManager
from google.adk.models import Gemini
from google.adk.models.llm_request import LlmRequest
from google.adk.tools.authenticated_function_tool import AuthenticatedFunctionTool
from google.cloud import bigquery
from google.cloud import storage
from google.oauth2.credentials import Credentials as OAuth2Credentials
from pydantic import Field
from typing import Literal
from typing import Optional
from typing_extensions import override

from bootstrap import get_bootstrap_settings
from runtime_config import get_runtime_config
from runtime_config import get_runtime_config_status


BOOTSTRAP = get_bootstrap_settings()
PROJECT_ID = BOOTSTRAP.project_id
LOCATION = BOOTSTRAP.location
GEMINI_ENTERPRISE_AUTHORIZATION = BOOTSTRAP.gemini_enterprise_authorization_id


class GeminiEnterpriseDelegatedAuthProviderScheme(CustomAuthScheme):
    """Auth scheme for a token Gemini Enterprise forwards after its own
    front-door OAuth consent (agent registration `authorizationConfig`).

    Gemini Enterprise runs its own consent flow at the registration level
    and hands the resulting token to the agent through session state, so
    the tool never runs its own OAuth exchange.

    Adapted from Google's reference implementation:
    https://github.com/GoogleCloudPlatform/iam-federation-tools/blob/master/adk/geminienterprise_auth.py
    """

    type_: Literal["GeminiEnterpriseDelegatedAuthProviderScheme"] = Field(
        default="GeminiEnterpriseDelegatedAuthProviderScheme", alias="type"
    )
    name: Optional[str] = None


class GeminiEnterpriseDelegatedAuthProvider(BaseAuthProvider):
    """Reads the OAuth token Gemini Enterprise already forwarded via
    context.session.state, instead of running a second OAuth handshake.

    Requires the registered agent to declare authorizationConfig pointing
    at a Discovery Engine authorization resource with the same OAuth
    client. Without that, Gemini Enterprise never shows the consent prompt
    and this provider never receives a token."""

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
                "GeminiEnterpriseDelegatedAuthProviderScheme requires a context "
                "with a valid session."
            )
        if auth_scheme.name and auth_scheme.name in context.session.state:
            token = context.session.state[auth_scheme.name]
        elif len(context.session.state) == 1:
            token = list(context.session.state.values())[0]
        else:
            raise ValueError("No matching Gemini Enterprise authorization found in session.")
        return AuthCredential(
            auth_type=AuthCredentialTypes.OAUTH2,
            oauth2=OAuth2Auth(access_token=token),
        )


CredentialManager.register_auth_provider(GeminiEnterpriseDelegatedAuthProvider())


def _read_delegated_token(credential: AuthCredential) -> str | None:
    """Reads the delegated OAuth access token regardless of which of the
    two providers above supplied it — they store it in different places
    on the AuthCredential."""
    if credential.oauth2 and credential.oauth2.access_token:
        return credential.oauth2.access_token
    if credential.http and credential.http.credentials:
        return credential.http.credentials.token
    return None


# --- Pattern: Agent Identity ---


def template_agent_identity_tool() -> dict[str, object]:
    """Calls Cloud Storage with the deployed agent's own credentials. Every
    authorized user shares this same backend capability; use it when the
    downstream service does not need to distinguish between callers.
    """
    runtime_config = get_runtime_config()
    client = storage.Client(project=PROJECT_ID)
    object_names = [
        blob.name
        for blob in client.list_blobs(
            runtime_config.agent_identity_bucket_name,
            max_results=runtime_config.storage_object_limit,
        )
    ]
    runtime_engine_id = os.getenv("GOOGLE_CLOUD_AGENT_ENGINE_ID")
    running_on_agent_runtime = bool(runtime_engine_id)
    return {
        "authentication_mode": (
            "Agent Identity" if running_on_agent_runtime else "local ADC"
        ),
        "execution_environment": (
            "Agent Runtime" if running_on_agent_runtime else "local development"
        ),
        "reasoning_engine_id": runtime_engine_id or "not available locally",
        "bucket": runtime_config.agent_identity_bucket_name,
        "object_count_returned": len(object_names),
        "objects": object_names,
        "explanation": (
            "The Cloud Storage client used Application Default Credentials. "
            "On Agent Runtime those credentials belong to this reasoning "
            "engine's unique Agent Identity; locally they belong to the "
            "developer's ADC identity."
        ),
    }


# --- Pattern: Gemini Enterprise's forwarded delegated token ---


def _gemini_enterprise_delegated_bigquery_client(
    credential: AuthCredential,
) -> bigquery.Client:
    token = _read_delegated_token(credential)
    if not token:
        raise ValueError("No delegated OAuth token was supplied to the tool.")
    return bigquery.Client(
        project=PROJECT_ID,
        credentials=OAuth2Credentials(token),
    )


def _template_bigquery_discover(client: bigquery.Client) -> dict[str, object]:
    """Lists every dataset the caller can see and describes each one's
    tables and columns, so the model can write SQL without guessing names."""
    datasets: list[dict[str, object]] = []
    for dataset in client.list_datasets():
        tables: list[dict[str, object]] = []
        for table_ref in client.list_tables(dataset.dataset_id):
            table = client.get_table(table_ref.reference)
            tables.append(
                {
                    "table": f"{PROJECT_ID}.{dataset.dataset_id}.{table_ref.table_id}",
                    "row_count": table.num_rows,
                    "columns": [
                        {"name": field.name, "type": field.field_type}
                        for field in table.schema
                    ],
                }
            )
        datasets.append({"dataset": dataset.dataset_id, "tables": tables})
    return {"project": PROJECT_ID, "datasets": datasets}


def _json_safe(value: object) -> object:
    """Converts BigQuery row values (date, datetime, Decimal, bytes, ...) into
    types the ADK event stream can JSON-serialize back to the model."""
    if isinstance(value, (datetime.date, datetime.datetime, datetime.time)):
        return value.isoformat()
    if isinstance(value, decimal.Decimal):
        return float(value)
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


async def _template_bigquery_query(
    credential: AuthCredential,
    sql: str | None = None,
) -> dict[str, object]:
    """Call with no sql first to discover the caller's BigQuery datasets,
    tables and columns. Call again with sql — using the fully-qualified
    table names from that discovery — to run the query. The query executes
    with the signed-in user's own BigQuery permissions. Results are capped;
    add your own LIMIT for smaller result sets.
    """
    runtime_config = get_runtime_config()
    client = _gemini_enterprise_delegated_bigquery_client(credential)
    if not sql:
        return _template_bigquery_discover(client)
    job = client.query(sql)
    rows = [
        {key: _json_safe(value) for key, value in dict(row).items()}
        for row in job.result(max_results=runtime_config.bigquery_query_row_limit)
    ]
    return {"row_count_returned": len(rows), "rows": rows}


template_bigquery_query_tool = AuthenticatedFunctionTool(
    func=_template_bigquery_query,
    auth_config=AuthConfig(
        auth_scheme=GeminiEnterpriseDelegatedAuthProviderScheme(
            name=GEMINI_ENTERPRISE_AUTHORIZATION,
        )
    ),
)


# --- Runtime configuration from Parameter Manager ---


def template_runtime_config_tool() -> dict[str, object]:
    """Returns non-sensitive metadata about the active Parameter Manager
    configuration. Use it to verify configuration access and refresh behavior.
    """
    return get_runtime_config_status()


def _runtime_instruction(readonly_context: ReadonlyContext) -> str:
    del readonly_context
    return get_runtime_config().instruction


def _apply_runtime_model(
    callback_context: CallbackContext,
    llm_request: LlmRequest,
) -> None:
    del callback_context
    llm_request.model = get_runtime_config().model


# Some models only serve from the global Vertex AI endpoint, not the
# region the reasoning engine deploys to. Route the model call to global
# explicitly rather than assume the deployment region matches.
template_model = Gemini(
    model="gemini-3.7-flash",
    client_kwargs={"location": "global"},
)


root_agent = Agent(
    name="template_pro_code_agent",
    model=template_model,
    description=(
        "Template pro-code agent demonstrating Agent Identity and Gemini "
        "Enterprise delegated auth."
    ),
    instruction=_runtime_instruction,
    before_model_callback=_apply_runtime_model,
    tools=[
        template_runtime_config_tool,
        template_agent_identity_tool,
        template_bigquery_query_tool,
    ],
)
