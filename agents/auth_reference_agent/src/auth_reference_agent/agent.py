"""Reference ADK agent demonstrating Agent Identity and delegated user auth.

The custom delegated-auth scheme, provider class and provider registration
intentionally remain in this module. A deployed Agent Runtime previously failed
with ``No auth provider registered for custom auth scheme`` when the provider
class was imported through a separate module path. Keep this registration local
to the deployable agent until that runtime behavior is conclusively disproven.
"""

from __future__ import annotations

import datetime
import decimal
import os
from typing import Literal, override

from google.adk.agents import Agent
from google.adk.agents.callback_context import CallbackContext
from google.adk.agents.readonly_context import ReadonlyContext
from google.adk.auth.auth_credential import AuthCredential, AuthCredentialTypes, OAuth2Auth
from google.adk.auth.auth_schemes import CustomAuthScheme
from google.adk.auth.auth_tool import AuthConfig
from google.adk.auth.base_auth_provider import BaseAuthProvider
from google.adk.auth.credential_manager import CredentialManager
from google.adk.models import Gemini
from google.adk.models.llm_request import LlmRequest
from google.adk.tools.authenticated_function_tool import AuthenticatedFunctionTool
from google.cloud import bigquery, storage
from google.oauth2.credentials import Credentials as OAuth2Credentials
from pydantic import Field

from gemini_shared import get_bootstrap_settings, get_runtime_config, get_runtime_config_status


RUNTIME_ENGINE_ID_ENV = "GOOGLE_CLOUD_AGENT_ENGINE_ID"
AUTHENTICATION_MODE_AGENT_IDENTITY = "Agent Identity"
AUTHENTICATION_MODE_LOCAL_ADC = "local ADC"
EXECUTION_ENVIRONMENT_RUNTIME = "Agent Runtime"
EXECUTION_ENVIRONMENT_LOCAL = "local development"
LOCAL_ENGINE_ID = "not available locally"

BOOTSTRAP = get_bootstrap_settings(require_auth=True)
PROJECT_ID = BOOTSTRAP.project_id
GEMINI_ENTERPRISE_AUTHORIZATION_ID = BOOTSTRAP.gemini_enterprise_authorization_id
if GEMINI_ENTERPRISE_AUTHORIZATION_ID is None:
    raise RuntimeError("GEMINI_ENTERPRISE_AUTHORIZATION_ID is required for this agent.")


class GeminiEnterpriseDelegatedAuthProviderScheme(CustomAuthScheme):
    """Auth scheme for the token forwarded by Gemini Enterprise."""

    type_: Literal["GeminiEnterpriseDelegatedAuthProviderScheme"] = Field(
        default="GeminiEnterpriseDelegatedAuthProviderScheme",
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
            raise ValueError(
                "No matching Gemini Enterprise authorization found in session state."
            )

        return AuthCredential(
            auth_type=AuthCredentialTypes.OAUTH2,
            oauth2=OAuth2Auth(access_token=token),
        )


CredentialManager.register_auth_provider(GeminiEnterpriseDelegatedAuthProvider())


def _read_delegated_token(credential: AuthCredential) -> str | None:
    if credential.oauth2 and credential.oauth2.access_token:
        return credential.oauth2.access_token
    if credential.http and credential.http.credentials:
        return credential.http.credentials.token
    return None


def template_agent_identity_tool() -> dict[str, object]:
    """List a bounded number of objects using Agent Identity or local ADC."""
    runtime = get_runtime_config()
    bucket_name = runtime.agent_identity_bucket_name
    if not bucket_name:
        raise RuntimeError(
            "agent_identity_bucket_name is required to use the Agent Identity storage example."
        )

    client = storage.Client(project=PROJECT_ID)
    object_names = [
        blob.name
        for blob in client.list_blobs(
            bucket_name,
            max_results=runtime.storage_object_limit,
        )
    ]
    runtime_engine_id = os.getenv(RUNTIME_ENGINE_ID_ENV)
    running_on_runtime = bool(runtime_engine_id)
    return {
        "authentication_mode": (
            AUTHENTICATION_MODE_AGENT_IDENTITY
            if running_on_runtime
            else AUTHENTICATION_MODE_LOCAL_ADC
        ),
        "execution_environment": (
            EXECUTION_ENVIRONMENT_RUNTIME
            if running_on_runtime
            else EXECUTION_ENVIRONMENT_LOCAL
        ),
        "reasoning_engine_id": runtime_engine_id or LOCAL_ENGINE_ID,
        "bucket": bucket_name,
        "object_count_returned": len(object_names),
        "objects": object_names,
    }


def _delegated_bigquery_client(credential: AuthCredential) -> bigquery.Client:
    token = _read_delegated_token(credential)
    if not token:
        raise ValueError("No delegated OAuth token was supplied to the tool.")
    return bigquery.Client(
        project=PROJECT_ID,
        credentials=OAuth2Credentials(token),
    )


def _discover_bigquery(client: bigquery.Client) -> dict[str, object]:
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
    runtime = get_runtime_config()
    client = _delegated_bigquery_client(credential)
    if not sql:
        return _discover_bigquery(client)

    rows = [
        {key: _json_safe(value) for key, value in dict(row).items()}
        for row in client.query(sql).result(max_results=runtime.bigquery_query_row_limit)
    ]
    return {"row_count_returned": len(rows), "rows": rows}


template_bigquery_query_tool = AuthenticatedFunctionTool(
    func=_template_bigquery_query,
    auth_config=AuthConfig(
        auth_scheme=GeminiEnterpriseDelegatedAuthProviderScheme(
            name=GEMINI_ENTERPRISE_AUTHORIZATION_ID,
        )
    ),
)


def template_runtime_config_tool() -> dict[str, object]:
    """Return non-sensitive metadata about the active runtime configuration."""
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


root_agent = Agent(
    name="auth_reference_agent",
    model=Gemini(
        model=BOOTSTRAP.bootstrap_model,
        client_kwargs={"location": BOOTSTRAP.model_location},
    ),
    description=(
        "Reference agent demonstrating Agent Identity and Gemini Enterprise delegated auth."
    ),
    instruction=_runtime_instruction,
    before_model_callback=_apply_runtime_model,
    tools=[
        template_runtime_config_tool,
        template_agent_identity_tool,
        template_bigquery_query_tool,
    ],
)
