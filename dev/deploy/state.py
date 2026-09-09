"""Project- and region-scoped deployment state and runtime validation."""

from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path

from gcp import project_number
from paths import STATE_DIR

DEV_REASONING_ENGINE_ENV = "DEV_REASONING_ENGINE"
RESOURCE_PATTERN = re.compile(
    r"^projects/(?P<project>[^/]+)/locations/(?P<location>[^/]+)/"
    r"reasoningEngines/(?P<engine>[^/]+)$"
)
COMPONENT_PATTERN = re.compile(r"[A-Za-z0-9_-]+")


@dataclass(frozen=True, slots=True)
class RuntimeResource:
    project: str
    location: str
    engine: str

    @classmethod
    def parse(cls, name: str) -> RuntimeResource:
        match = RESOURCE_PATTERN.fullmatch(name.strip())
        if match is None:
            raise SystemExit(
                "Expected projects/<project>/locations/<region>/reasoningEngines/<id>."
            )
        return cls(**match.groupdict())

    def matches(self, project_id: str, location: str) -> bool:
        if self.location != location:
            return False
        number = project_number(project_id)
        if self.project in (project_id, number):
            return True
        return project_id.isdigit() and project_number(self.project) == number


def validate_runtime_resource(name: str, project_id: str, location: str) -> str:
    """Reject an override or saved runtime outside the selected deployment scope."""
    resource = RuntimeResource.parse(name)
    if not resource.matches(project_id, location):
        raise SystemExit(
            f"Runtime '{name}' belongs to a different project or region; "
            f"the selected target is {project_id}/{location}. No update was made."
        )
    return name.strip()


def state_path(agent_name: str, project_id: str, location: str) -> Path:
    for component in (agent_name, location):
        if not COMPONENT_PATTERN.fullmatch(component):
            raise SystemExit("Agent and region names must be simple path components.")
    return STATE_DIR / project_number(project_id) / location / f"{agent_name}.json"


def _read_state(path: Path, agent_name: str) -> str:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload["agent"] != agent_name:
            raise ValueError("Agent does not match")
        name = payload["reasoning_engine"]
        if not isinstance(name, str) or not name.strip():
            raise ValueError("Missing runtime")
    except (ValueError, KeyError, TypeError) as exc:
        raise SystemExit(f"Invalid developer state file: {path}") from exc
    return name


def save_state(agent_name: str, resource_name: str, project_id: str, location: str) -> None:
    resource_name = validate_runtime_resource(resource_name, project_id, location)
    path = state_path(agent_name, project_id, location)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"agent": agent_name, "reasoning_engine": resource_name}
    with tempfile.NamedTemporaryFile(
        mode="w", dir=path.parent, delete=False, encoding="utf-8"
    ) as handle:
        temporary = Path(handle.name)
        json.dump(payload, handle, indent=2, sort_keys=True)
    try:
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def runtime_override(project_id: str, location: str) -> str | None:
    """Validate an explicit target before running deployment preflight."""
    explicit = os.getenv(DEV_REASONING_ENGINE_ENV, "").strip()
    return validate_runtime_resource(explicit, project_id, location) if explicit else None


def find_resource_name(agent_name: str, project_id: str, location: str) -> str | None:
    """Find a runtime, migrating a matching legacy state file without deleting it."""
    explicit = runtime_override(project_id, location)
    if explicit:
        return explicit
    path = state_path(agent_name, project_id, location)
    if path.exists():
        return validate_runtime_resource(_read_state(path, agent_name), project_id, location)

    legacy = STATE_DIR / f"{agent_name}.json"
    if legacy.exists():
        name = _read_state(legacy, agent_name)
        if RuntimeResource.parse(name).matches(project_id, location):
            save_state(agent_name, name, project_id, location)
            return name
    return None


def load_resource_name(agent_name: str, project_id: str, location: str) -> str:
    name = find_resource_name(agent_name, project_id, location)
    if name is None:
        raise SystemExit(
            f"No saved runtime for {agent_name} in {project_id}/{location}. "
            f"Deploy it first or set {DEV_REASONING_ENGINE_ENV}."
        )
    return name
