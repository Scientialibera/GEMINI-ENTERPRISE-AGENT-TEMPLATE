"""Bootstrap values this agent resolves once at import."""

from __future__ import annotations

import os

from gemini_shared import get_bootstrap_settings
from gemini_shared.mcp import mcp_google_cloud

BOOTSTRAP = get_bootstrap_settings(require_auth=True)
PROJECT_ID = BOOTSTRAP.project_id
GEMINI_ENTERPRISE_AUTHORIZATION_ID = BOOTSTRAP.gemini_enterprise_authorization_id

if GEMINI_ENTERPRISE_AUTHORIZATION_ID is None:
    raise RuntimeError("GEMINI_ENTERPRISE_AUTHORIZATION_ID is required for this agent.")

# Changing the MCP endpoint requires redeployment. A deployed runtime receives
# this from AgentSpec.runtime_env; the environment is read only for local runs.
MCP_SERVER_URL = os.getenv("MCP_SERVER_URL", "").strip() or mcp_google_cloud.CLOUD_MONITORING
