"""Deployment-only settings for per-agent access groups."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

PREFIX = "GEMINI_AGENT_GROUP_"


@dataclass(frozen=True)
class GroupConfig:
    customer: str
    email: str
    owner: str
    marker: str


def group_config(project: str, app: str, package: str) -> GroupConfig | None:
    enabled = os.getenv("GEMINI_AGENT_GROUPS_ENABLED", "false").strip().lower()
    if enabled not in {"true", "false"}:
        raise ValueError("GEMINI_AGENT_GROUPS_ENABLED must be true or false.")
    if enabled == "false":
        return None
    values = {
        key: os.getenv(PREFIX + key, "").strip()
        for key in ("CUSTOMER_ID", "DOMAIN", "OWNER_EMAIL", "PREFIX")
    }
    missing = [PREFIX + key for key, value in values.items() if not value]
    if missing or not app:
        raise ValueError("Group sharing requires an app ID and settings: " + ", ".join(missing))
    customer = values["CUSTOMER_ID"]
    domain = values["DOMAIN"].lower()
    owner = values["OWNER_EMAIL"].lower()
    local = f"{values['PREFIX']}-{package.replace('_', '-')}-users".lower()
    if not re.fullmatch(r"C[a-zA-Z0-9]+", customer):
        raise ValueError("Group CUSTOMER_ID must be a Workspace customer ID, such as C012abcde.")
    if not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?\.[a-z]{2,}", domain):
        raise ValueError("Group DOMAIN must be a managed domain name.")
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,63}", local):
        raise ValueError(
            "Generated group email local part must be valid and at most 64 characters."
        )
    if not re.fullmatch(r"[a-z0-9][a-z0-9._+-]*@" + re.escape(domain), owner):
        raise ValueError("Group OWNER_EMAIL must be a user in the configured managed domain.")
    return GroupConfig(
        f"customers/{customer}",
        f"{local}@{domain}",
        owner,
        f"Managed agent access group: {project}/{app}/{package}",
    )
