"""Add agent-use permission without replacing existing IAM bindings."""

from __future__ import annotations

from copy import deepcopy

from register.api_http import request

AGENT_USER_ROLE = "roles/discoveryengine.agentUser"


def check_sharing(url: str, project: str, *, require_enabled: bool = False) -> dict:
    agent = request("GET", url, project)
    if agent.get("sharingConfig", {}).get("scope") == "ALL_USERS":
        raise ValueError(
            "Agent is shared with ALL_USERS. Restrict it in the console before retrying."
        )
    if agent.get("state") in {"DISABLED", "SUSPENDED"}:
        raise ValueError("Existing agent is not enabled. Review its state in the console first.")
    if require_enabled and agent.get("state") != "ENABLED":
        raise RuntimeError(
            "Group sharing was requested but the agent is not enabled. "
            "Review/publish it in Gemini Enterprise, then rerun registration."
        )
    policy = request("GET", url + ":getIamPolicy?options.requestedPolicyVersion=3", project)
    if any(
        member in {"allUsers", "allAuthenticatedUsers"}
        for binding in policy.get("bindings", [])
        for member in binding.get("members", [])
    ):
        raise ValueError(
            "Agent IAM contains a public grant. Remove it before enabling group sharing."
        )
    if not policy.get("etag"):
        raise ValueError("Agent IAM has no etag; refusing an unconditional policy overwrite.")
    return policy


def _has_member(policy: dict, member: str) -> bool:
    return any(
        b.get("role") == AGENT_USER_ROLE
        and not b.get("condition")
        and member in b.get("members", [])
        for b in policy.get("bindings", [])
    )


def share_agent(url: str, project: str, group_email: str) -> None:
    policy = check_sharing(url, project)
    member = "group:" + group_email
    if not _has_member(policy, member):
        updated = deepcopy(policy)
        bindings = updated.setdefault("bindings", [])
        binding = next(
            (b for b in bindings if b.get("role") == AGENT_USER_ROLE and not b.get("condition")),
            None,
        )
        if binding is None:
            binding = {"role": AGENT_USER_ROLE, "members": []}
            bindings.append(binding)
        binding.setdefault("members", []).append(member)
        request("POST", url + ":setIamPolicy", project, {"policy": updated})
    verified = check_sharing(url, project, require_enabled=True)
    if not _has_member(verified, member):
        raise RuntimeError("Agent group binding was not confirmed; registration is incomplete.")
    print(f"AGENT_SHARED_WITH={group_email}")
