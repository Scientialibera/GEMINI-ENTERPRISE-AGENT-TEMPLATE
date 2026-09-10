# Monitoring MCP Agent

Inspects Cloud Monitoring through Google's managed remote MCP server, calling it
with the **signed-in Gemini Enterprise user's delegated OAuth token**. The agent
never substitutes developer ADC or the runtime's Agent Identity for that token:
when delegated authentication is missing, the request fails.

## Service contract

Verified against Google's current documentation:

| Item | Value | Source |
|---|---|---|
| Endpoint | `https://monitoring.googleapis.com/mcp` | [Use the Cloud Monitoring MCP server](https://docs.cloud.google.com/monitoring/docs/use-monitoring-mcp) |
| Transport | Streamable HTTP | same |
| Tools | the nine below | [MCP reference](https://docs.cloud.google.com/monitoring/api/ref_v3_mcp/mcp) |
| Delegated scope | `https://www.googleapis.com/auth/monitoring.read` | [OAuth scopes](https://developers.google.com/identity/protocols/oauth2/scopes) |
| MCP invocation | `roles/mcp.toolUser` (`mcp.tools.call`) | [MCP access control](https://docs.cloud.google.com/mcp/access-control) |
| Service access | `roles/monitoring.viewer` | [Monitoring roles](https://docs.cloud.google.com/monitoring/access-control) |
| API | Cloud Monitoring API (`monitoring.googleapis.com`) | [Use the Cloud Monitoring MCP server](https://docs.cloud.google.com/monitoring/docs/use-monitoring-mcp) |

The allowlist is the server's full published tool set, each annotated read-only
in the reference. `execute`/`create`/`update`/`delete` equivalents do not exist
on this server, so nothing is excluded to make it read-only:

`list_timeseries`, `query_range`, `list_metric_descriptors`,
`list_alert_policies`, `get_alert_policy`, `list_alerts`, `get_alert`,
`list_dashboards`, `get_dashboard`

Tools are exposed to the model as `mon_mcp_*`.

### Two documented divergences

**Scope.** The MCP page lists `.../auth/monitoring` (read *and* write) and
`.../auth/monitoring.write`. The Monitoring API's own scope list defines
`.../auth/monitoring.read`, described as "View monitoring data", which covers
every selected tool. This agent requests the read-only scope. If a tool call is
rejected for insufficient scope, treat that as a finding to record here — do not
widen the scope silently. An OAuth scope bounds what the token may request; it
grants no IAM permission on its own.

**Role.** The MCP page names `roles/monitoring.admin` ("Use Monitoring MCP
tools"), which grants create, update and delete. `roles/monitoring.viewer`
contains the read permissions all nine tools need
(`monitoring.timeSeries.list`, `monitoring.metricDescriptors.list/get`,
`monitoring.alertPolicies.list/get`, `monitoring.alerts.list/get`,
`monitoring.dashboards.list/get`). Grant the viewer role; the admin role is a
quickstart convenience, not a requirement.

## Permissions the test user needs

Granted to the **signed-in user**, not to the Agent Identity:

- `roles/mcp.toolUser` on the project whose MCP server is called
- `roles/monitoring.viewer` on each project to be inspected
- The Cloud Monitoring API enabled on that project

The agent cannot elevate the user's access. A user without
`monitoring.viewer` on a project gets a permission error, which is the intended
boundary. The runtime's Agent Identity is used only for its own platform needs
(reading configuration from Parameter Manager) and is deliberately **not**
granted monitoring access.

## Configuration

Registry defaults: parameter `monitoring-mcp-agent-config`, authorization
`monitoring-mcp-agent-authz`, secret `monitoring-mcp-agent-oauth-client-secret`.

~~~text
OAUTH_CLIENTS=...,monitoring_mcp_agent=<client-id>
MONITORING_MCP_AGENT_OAUTH_CLIENT_SECRET=<initial-secret>
~~~

This agent declares its own `MCP_SERVER_URL` and
`ADK_DISABLE_JSON_SCHEMA_FOR_FUNC_DECL` in `AgentSpec.runtime_env`. Neither name
is in `RUNTIME_ENV_KEYS`, so a shell or `dev/.env.dev` value is **not** forwarded
to a deployed runtime: the spec's value always wins remotely, and no leftover
from another agent can retarget this one. Those variables still affect a local
run, where the agent reads them directly.

Check for stale `GEMINI_ENTERPRISE_AUTHORIZATION_ID`, `CONFIG_PARAMETER` and
`DEV_REASONING_ENGINE` overrides before releasing; those *are* forwarded.

## Consent

Create a dedicated Web application OAuth client (never reuse another agent's —
consent is cached per client) with both redirect URIs from the root README, add
the test users to the consent screen, then:

Before registering, add `https://www.googleapis.com/auth/monitoring.read` to
**Google Auth Platform → Data Access**. Enable the Cloud Monitoring API first so
the scope appears in the picker; otherwise paste it under *Manually add scopes*.
The consent screen is per-project and console-only — no API sets it, and an
organisation may require an administrator to allow the client or its scopes.
Do this **before** the first registration: an authorization created against a
consent screen missing this scope is not repaired by fixing the screen
afterwards.

~~~bash
uv run --group dev python dev/release_dev.py --agent monitoring_mcp_agent --skip-register
# finish the consent screen, then register:
uv run --group dev python -c "import sys; sys.path.insert(0,'dev'); \
from register.register_agent import main; \
sys.argv=['register_agent.py','--agent','monitoring_mcp_agent']; main()"
~~~

Deployment alone touches no OAuth resource, and the runtime stays invisible in
Gemini Enterprise until registration creates its listing. `register_agent.py` is
run as a module above because executing it as a file shadows the standard
library's `http` package; see [dev/README](../../dev/README.md#running-a-step-script-directly).

Confirm the authorization requests the read-only scope before asking a user to
consent — it records its scopes when created:

~~~bash
TOKEN=$(gcloud auth print-access-token)
curl -s -H "Authorization: Bearer $TOKEN" \
  -H "X-Goog-User-Project: <project-id>" \
  "https://discoveryengine.googleapis.com/v1alpha/projects/<project-number>/locations/global/authorizations/monitoring-mcp-agent-authz"
~~~

The `authorizationUri` should carry `openid email profile` plus
`https://www.googleapis.com/auth/monitoring.read` and nothing wider.

`ensure_authorization` creates a missing authorization but does not reconcile an
existing one. Changing `delegated_oauth_scopes` later requires an explicit
authorization update or a new authorization plus fresh user consent; an
already-consented token keeps its original scopes.

## Token routing

`gemini_shared.auth.delegated.read_session_token` matches a known authorization
ID exactly. A session carrying only another agent's authorization returns
nothing and the request fails closed, so this agent cannot be handed a token the
user never consented to give it. The single-entry fallback that previously
returned any lone session value now applies only when no authorization ID is
known, which is the legacy case it was written for.

`tests/test_monitoring_mcp.py` covers this: a foreign authorization yields no
token, several entries fail closed, exact-key routing is asserted among multiple
authorizations, and two user contexts produce their own headers.

This is a change to the shared helper, so it applies to every delegated agent.
Unit tests use fake tokens; the isolation it enforces should still be confirmed
against real Gemini Enterprise sessions with two accounts.

## Testing

Unit tests need no cloud login:

~~~bash
uv run --group dev pytest tests/test_monitoring_mcp.py
~~~

They cover the endpoint, the read-only allowlist, the requested scope, registry
metadata, per-user header isolation, failure without consent, and absence of any
ADC fallback — all with fake tokens and no network.

**These tests do not prove delegated authentication works.** Neither does a
successful `tools/list`: discovery against Google's remote MCP servers can
succeed without user authorization, and a local run uses workstation ADC, which
is a different credential entirely. Only a tool call from Gemini Enterprise
after user consent demonstrates the delegated path.
