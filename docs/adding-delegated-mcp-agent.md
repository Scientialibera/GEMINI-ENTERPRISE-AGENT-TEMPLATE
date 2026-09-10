# Add a Google-managed MCP agent with user authorization

Use this guide when the downstream service must act as the person using Gemini
Enterprise. This is delegated OAuth, not merely forwarding an SSO identity claim.
Start from `agents/bigquery_mcp_agent`, then change the service-specific pieces.
Do not implement a second token provider or deployment path.

## Establish the service contract

Read the service's current official MCP guide and tool reference. Record the endpoint,
transport, selected tool names, accepted OAuth scopes and required user permissions
in the new agent's README, with source links. Verify that the tools are read-only;
a name containing `get` or `list` alone is not sufficient evidence.

Use an explicit tool allowlist. An OAuth scope limits what a token can request;
it does not grant IAM permissions. The caller also needs the service permissions
and MCP invocation permission, commonly supplied by `roles/mcp.toolUser`.
Check the scope of each IAM grant against the selected tools' documentation.
Do not copy an administrator role from a quickstart when narrower permissions work.
Some MCP guides list scopes that include writes even for read-oriented tools.
Document that distinction instead of inventing an unsupported read-only scope.

Reference sources:

- [Google MCP authentication](https://docs.cloud.google.com/mcp/set-up-authentication-mcp-servers)
- [Cloud Monitoring MCP](https://docs.cloud.google.com/monitoring/docs/use-monitoring-mcp)
- [Cloud Logging MCP](https://docs.cloud.google.com/logging/docs/use-logging-mcp)

## Preserve the authentication boundary

Use `delegated_mcp_toolset` from `gemini_shared.mcp.mcp_auth`. Its header provider
reads the current session token for each request. Never capture a token at import
time, store one in a module global or fall back to developer ADC or Agent Identity
when user credentials are absent. Do not log tokens or session-state contents.

The MCP URL is trusted deployment configuration: the user's bearer token is sent
there. Never take it from a chat message, model output or arbitrary tool argument.
Tool discovery caching must not become a shared cache of user credentials or results.

The runtime still uses Agent Identity for its own platform needs, such as reading
configuration. Do not grant that identity access to the target service to work around
a failed delegated request. Service access belongs to the consenting user in this design.

Known limitation: `auth/delegated.py::read_session_token` accepts the sole session-state
value when the configured authorization key is absent. This legacy fallback does not
validate the key or token type. Reusing the helper does not prove strict token routing.
Before calling a new integration production-ready, add regression coverage for a
mismatched single-entry state and resolve this ambiguity explicitly, checking existing
Gemini Enterprise behavior. Do not copy the fallback into a new agent or hide the
problem by inserting an arbitrary state value. This documentation review has not
changed that runtime behavior.

## Add the package

1. Copy the BigQuery MCP agent structure. Rename its package, project, wheel path and
   ADK agent name. Replace the prompt and tool module; remove BigQuery-specific imports
   and registration text. Keep the `gemini-shared[mcp]` dependency.
2. Keep `runtime_instruction`, `apply_runtime_model`, `create_model` and `create_app`.
   They carry shared configuration, retry limits, the model-call ceiling and compaction.
   Do not reproduce these controls in the new agent.
3. Put service-specific tool construction under the agent's `tools/`. Use the shared
   delegated MCP helper with an explicit allowlist and a distinct tool-name prefix.
   Move reusable constants or factories into `gemini_shared/mcp/` only when needed.
4. Add an `AgentSpec` in `dev/registry.py`, including the package/import paths,
   `AUTHORIZATION_ID_ENV` in required remote bootstrap settings and service OAuth scopes.
   Preserve the source-level delegated-auth declaration used by registry validation.
5. Add its source directory to pytest's `pythonpath` in the root `pyproject.toml`.
   Update the lockfile through `uv sync --all-packages --group dev`. Do not hand-edit
   exported deployment requirements or introduce an independent deployment script.

Follow the existing typed Python style and Ruff configuration. Keep comments short
and explain constraints, not obvious operations. Do not copy unrelated sample tools,
add speculative abstractions or suppress lint/test failures to make the scaffold pass.

## Configure consent and deployment

Use a distinct per-agent authorization and OAuth client. `AgentSpec` derives their
names and environment keys. Add the client ID to `OAUTH_CLIENTS` as
`<agent_name>=<client_id>`, preserving other entries, or use the spec's per-agent
client ID override. Follow the root README for redirect URIs, consent setup and the
per-agent Secret Manager secret. Never commit client secrets or token files.

Check shell overrides as well as `dev/.env.dev` before releasing. In particular,
`MCP_SERVER_URL` is forwarded to remote agents: a leftover BigQuery endpoint overrides
the new agent's default. Check authorization, runtime and parameter overrides too.
Do not reuse another agent's authorization just because its ID is already configured.

`ensure_authorization` creates missing authorizations but does not reconcile existing
ones. Editing `delegated_oauth_scopes` does not update an existing authorization or
an already-consented token. Plan an explicit authorization update or a new authorization
and registration, then obtain fresh consent. Do not delete a working authorization
as an automatic migration step.

Document required API enablement and user IAM in the agent README. Check the current
`infrastructure/` and release preflight before assuming they provision the new service.
Release can mutate cloud resources and IAM; it is not a read-only validation command.
Obtain approval before deployment, consent configuration or permission changes.

## Verify the implementation

Run the repository checks from its root:

```powershell
uv sync --all-packages --group dev
uv run --group dev ruff check .
uv run --group dev ruff format --check .
uv run --group dev pytest
```

Add tests for the agent import, registry metadata, package contents, endpoint,
allowlist and requested scopes. Use fake tokens and mocked HTTP; tests must not need
a cloud login. Prove that two user contexts produce their own authorization headers,
that absent or invalid credentials fail before a tool call and that no ADC/runtime
credential fallback occurs. Cover multiple authorization entries and the legacy
single-entry ambiguity described above. Keep existing agent tests passing. If a new
service needs a scope prohibited by current tests, justify a service-specific exception
rather than weakening the rule for every agent.

Local execution with ADC and successful `tools/list` discovery do not establish
delegated authorization. Google's remote MCP discovery can be unauthenticated.
After approval, test a real tool call from Gemini Enterprise after user consent.
Confirm that an authorized user can read a known resource and a user without the
resource permission is denied. Confirm missing consent fails without switching
identities. Use redacted diagnostics or audit evidence where available; never record
the bearer token. If a second test account is unavailable, report that test as pending.

The handoff must distinguish unit tests, local API checks and deployed user-consent
tests. Include any remaining console steps and permission requirements. Do not claim
end-to-end success from mocked tests or tool discovery alone.
