"""Resolve the per-agent OAuth client selected by the developer."""

from __future__ import annotations

import os

from registry import AGENTS, AgentSpec

OAUTH_CLIENTS_ENV = "OAUTH_CLIENTS"


def oauth_client_id_for(agent_name: str, spec: AgentSpec) -> str:
    """Read the per-agent override, then the OAUTH_CLIENTS map."""
    override = os.getenv(spec.oauth_client_id_env, "").strip()
    if override:
        return override
    return _parse_oauth_clients().get(agent_name, "")


def _parse_oauth_clients() -> dict[str, str]:
    """Parse OAUTH_CLIENTS, a comma-separated list of agent=client_id pairs."""
    raw = os.getenv(OAUTH_CLIENTS_ENV, "").strip()
    if not raw:
        return {}

    clients: dict[str, str] = {}
    for entry in raw.split(","):
        entry = entry.strip()
        if not entry:
            continue
        if "=" not in entry:
            raise SystemExit(f"{OAUTH_CLIENTS_ENV} entry '{entry}' must use agent=client_id.")
        agent, _, client_id = entry.partition("=")
        agent, client_id = agent.strip(), client_id.strip()
        if agent in clients:
            raise SystemExit(f"{OAUTH_CLIENTS_ENV} lists '{agent}' more than once.")
        if agent not in AGENTS:
            raise SystemExit(
                f"{OAUTH_CLIENTS_ENV} names unknown agent '{agent}'. "
                f"Choose one of: {', '.join(sorted(AGENTS))}."
            )
        clients[agent] = client_id
    return clients
