"""Register native wrappers using the API shape verified in Workflow Builder."""

from __future__ import annotations

from register.api_http import iter_resources, request

MANAGED_MARKER = "Managed native workflow wrapper: "
DEFAULT_PROMPT = (
    "Run the complete workflow for the user's request. Ask for any missing inputs "
    "before starting. Return the result only after the workflow succeeds; if it "
    "fails, explain what remains and preserve any recovery identifiers."
)


def runtime_name(agent: dict) -> str | None:
    return (
        agent.get("adkAgentDefinition", {})
        .get("provisionedReasoningEngine", {})
        .get("reasoningEngine")
    )


def find_backend(agents: list[dict], display_name: str, reasoning_engine: str) -> str | None:
    """Reuse a legacy registration without changing its resource ID."""
    names = {display_name, f"{display_name} Backend"}
    candidates = []
    for agent in agents:
        if "adkAgentDefinition" not in agent:
            if agent.get("displayName") == f"{display_name} Backend":
                raise ValueError("Workflow backend name belongs to a non-ADK resource.")
            continue
        if runtime_name(agent) == reasoning_engine:
            candidates.append(agent)
        elif agent.get("displayName") in names:
            raise ValueError("Workflow backend name belongs to a different runtime.")
    if len(candidates) > 1:
        raise ValueError("Multiple ADK registrations reference this workflow runtime.")
    return candidates[0]["name"] if candidates else None


def wrapper_payload(package_name: str, display_name: str, backend: str) -> dict:
    return {
        "displayName": display_name,
        "description": MANAGED_MARKER + package_name,
        "state": "ENABLED",
        "sharingConfig": {"scope": "RESTRICTED"},
        "workflowAgentDefinition": {
            "agentFlow": {
                "nodes": [
                    {
                        "id": "start",
                        "displayName": "Manual start",
                        "nodeType": "MANUAL_TRIGGER",
                        "manualTrigger": {},
                    },
                    {
                        "id": "pipeline",
                        "displayName": display_name,
                        "nodeType": "AGENT_REFERENCE_NODE",
                        "agentReferenceNode": {
                            "agent": backend,
                            "agentReferenceType": "ADK_AGENT",
                            "inputParameters": {"prompt": DEFAULT_PROMPT},
                        },
                    },
                ],
                "edges": [{"sourceNodeId": "start", "targetNodeId": "pipeline"}],
            }
        },
    }


def find_wrapper(agents: list[dict], package_name: str, display_name: str) -> dict | None:
    marker = MANAGED_MARKER + package_name
    matches = [a for a in agents if a.get("description") == marker]
    if len(matches) > 1:
        raise ValueError("Multiple managed native wrappers found; resolve duplicates first.")
    for agent in agents:
        if (
            agent.get("displayName") == display_name
            and "workflowAgentDefinition" in agent
            and agent.get("description") != marker
        ):
            raise ValueError("An unmanaged native workflow already uses this name.")
    if matches and "workflowAgentDefinition" not in matches[0]:
        raise ValueError("Native workflow marker belongs to a different agent type.")
    return matches[0] if matches else None


def ensure_wrapper(url: str, project: str, package: str, display: str, backend: str) -> str:
    """Create once; preserve the existing graph and sharing on later releases."""
    agents = list(iter_resources(url, project, "agents"))
    existing = find_wrapper(agents, package, display)
    if existing:
        references = [
            n.get("agentReferenceNode", {}).get("agent")
            for n in existing["workflowAgentDefinition"].get("agentFlow", {}).get("nodes", [])
        ]
        if backend not in references:
            raise ValueError(
                "Existing wrapper no longer references this backend; review it manually."
            )
        name = existing["name"]
        print(f"REUSED_NATIVE_WORKFLOW={name}")
    else:
        result = request("POST", url, project, wrapper_payload(package, display, backend))
        name = result.get("name")
        if not isinstance(name, str) or "/agents/" not in name:
            raise ValueError(
                "Native workflow create returned no agent resource; inspect before retrying."
            )
        print(f"REGISTERED_NATIVE_WORKFLOW={name}")
    resource_url = url.split("/projects/", 1)[0] + "/" + name
    verified = request("GET", resource_url, project)
    references = [
        n.get("agentReferenceNode", {}).get("agent")
        for n in verified.get("workflowAgentDefinition", {}).get("agentFlow", {}).get("nodes", [])
    ]
    if backend not in references:
        raise ValueError(
            "Native workflow read-back did not contain the expected backend reference."
        )
    return name
