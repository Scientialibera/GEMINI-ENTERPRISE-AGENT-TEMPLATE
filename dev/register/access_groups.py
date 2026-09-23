"""Create security groups and retain manually managed memberships."""

from __future__ import annotations

import re
import time
from urllib.parse import urlencode

from register.api_http import ApiError, request
from register.group_config import GroupConfig, group_config

IDENTITY_URL = "https://cloudidentity.googleapis.com/v1"
SECURITY_LABEL = "cloudidentity.googleapis.com/groups.security"


def _wait(operation: dict, project: str) -> dict:
    deadline = time.monotonic() + 120
    for _ in range(60):
        if operation.get("done"):
            if operation.get("error"):
                raise RuntimeError(f"Cloud Identity operation failed: {operation['error']}")
            return operation.get("response", {})
        name = operation.get("name", "")
        if not re.fullmatch(r"(?:operations|groups)/[a-zA-Z0-9_/-]+", name):
            raise ValueError("Cloud Identity returned an invalid operation name.")
        if time.monotonic() >= deadline:
            break
        time.sleep(2)
        operation = request("GET", f"{IDENTITY_URL}/{name}", project)
    raise TimeoutError("Cloud Identity operation is still pending. Inspect it before retrying.")


def _lookup(config: GroupConfig, project: str) -> dict | None:
    url = f"{IDENTITY_URL}/groups:lookup?{urlencode({'groupKey.id': config.email})}"
    try:
        result = request("GET", url, project)
    except ApiError as exc:
        if exc.status == 404:
            return None
        raise
    name = result.get("name", "")
    if not re.fullmatch(r"groups/[a-zA-Z0-9_-]+", name):
        raise ValueError("Cloud Identity lookup returned an invalid group name.")
    return request("GET", f"{IDENTITY_URL}/{name}", project)


def _membership(group: dict, config: GroupConfig, project: str) -> dict | None:
    url = f"{IDENTITY_URL}/{group['name']}/memberships"
    try:
        found = request(
            "GET", url + ":lookup?" + urlencode({"memberKey.id": config.owner}), project
        )
    except ApiError as exc:
        if exc.status == 404:
            return None
        raise
    name = found.get("name", "")
    if not re.fullmatch(re.escape(group["name"]) + r"/memberships/[a-zA-Z0-9_-]+", name):
        raise ValueError("Cloud Identity returned an invalid membership name.")
    member = request("GET", f"{IDENTITY_URL}/{name}", project)
    if (
        member.get("preferredMemberKey", {}).get("id", "").lower() != config.owner
        or member.get("type") != "USER"
    ):
        raise ValueError("Configured group owner did not resolve to the expected user.")
    return member


def _is_owner(member: dict | None) -> bool:
    return bool(member) and any(role.get("name") == "OWNER" for role in member.get("roles", []))


def _owner(group: dict, config: GroupConfig, project: str) -> None:
    url = f"{IDENTITY_URL}/{group['name']}/memberships"
    existing = _membership(group, config, project)
    if existing:
        if _is_owner(existing):
            return
        request(
            "POST",
            f"{IDENTITY_URL}/{existing['name']}:modifyMembershipRoles",
            project,
            {"addRoles": [{"name": "OWNER"}]},
        )
    else:
        _wait(
            request(
                "POST",
                url,
                project,
                {
                    "preferredMemberKey": {"id": config.owner},
                    "roles": [{"name": "MEMBER"}, {"name": "OWNER"}],
                },
            ),
            project,
        )
    if not _is_owner(_membership(group, config, project)):
        raise RuntimeError("Group owner was not confirmed. Rerun after directory propagation.")


def ensure_group(config: GroupConfig, project: str) -> str:
    group = _lookup(config, project)
    if group is None:
        try:
            _wait(
                request(
                    "POST",
                    f"{IDENTITY_URL}/groups?initialGroupConfig=EMPTY",
                    project,
                    {
                        "parent": config.customer,
                        "groupKey": {"id": config.email},
                        "displayName": config.email.split("@", 1)[0],
                        "description": config.marker,
                        "labels": {
                            SECURITY_LABEL: "",
                            "cloudidentity.googleapis.com/groups.discussion_forum": "",
                        },
                    },
                ),
                project,
            )
        except ApiError as exc:
            if exc.status != 409:
                raise
        group = _lookup(config, project)
    if not group or (
        group.get("parent") != config.customer
        or group.get("groupKey", {}).get("id", "").lower() != config.email
        or group.get("description") != config.marker
        or SECURITY_LABEL not in group.get("labels", {})
    ):
        raise ValueError("Group identity or management marker differs; refusing to adopt it.")
    _owner(group, config, project)
    print(f"AGENT_ACCESS_GROUP={config.email}")
    local, domain = config.email.split("@", 1)
    print(f"MANAGE_GROUP=https://groups.google.com/a/{domain}/g/{local}/members")
    return config.email


def prepare_access_group(project: str, app: str, package: str) -> str | None:
    config = group_config(project, app, package)
    return ensure_group(config, project) if config else None
