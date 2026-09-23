"""Parameter Manager access under the runtime's own Agent Identity.

Only the calls the tools need: list, render, list versions and create a
version. Nothing here deletes, disables or edits an existing version, and the
identity is granted no role that could, so a mistaken publish is undone by
publishing again rather than by rewriting history.
"""

from __future__ import annotations

import functools
from dataclasses import dataclass

from gemini_shared import get_bootstrap_settings
from gemini_shared.config.bootstrap import DEFAULT_PARAMETER_LOCATION
from google.cloud import parametermanager_v1

MAX_PARAMETERS = 50
MAX_VERSIONS = 200


@dataclass(frozen=True, slots=True)
class Rendered:
    """One rendered version: its short ID and its payload text."""

    version: str
    payload: str


@functools.cache
def _client(location: str) -> parametermanager_v1.ParameterManagerClient:
    # The global location uses the default host; a regional one has its own.
    if location == DEFAULT_PARAMETER_LOCATION:
        return parametermanager_v1.ParameterManagerClient()
    return parametermanager_v1.ParameterManagerClient(
        client_options={"api_endpoint": f"parametermanager.{location}.rep.googleapis.com"}
    )


def _location() -> str:
    return get_bootstrap_settings().parameter_location


def _parent(project: str) -> str:
    return f"projects/{project}/locations/{_location()}"


def parameter_path(project: str, parameter: str) -> str:
    return f"{_parent(project)}/parameters/{parameter}"


def _short(name: str) -> str:
    return name.rsplit("/", 1)[-1]


def list_parameter_ids(project: str) -> list[str]:
    """Parameter IDs in the project, capped so a large project stays readable."""
    ids = []
    for parameter in _client(_location()).list_parameters(parent=_parent(project)):
        ids.append(_short(parameter.name))
        if len(ids) >= MAX_PARAMETERS:
            break
    return sorted(ids)


def render(project: str, parameter: str, version: str = "latest") -> Rendered:
    """Render one version; "latest" resolves to the version agents actually load."""
    response = _client(_location()).render_parameter_version(
        name=f"{parameter_path(project, parameter)}/versions/{version}"
    )
    return Rendered(_short(response.parameter_version), response.rendered_payload.decode("utf-8"))


def list_versions(project: str, parameter: str, limit: int) -> list[dict[str, object]]:
    """The newest versions first, with when each was created and whether it is live."""
    versions = []
    for version in _client(_location()).list_parameter_versions(
        parent=parameter_path(project, parameter)
    ):
        versions.append(version)
        if len(versions) >= MAX_VERSIONS:
            break
    versions.sort(key=lambda v: v.create_time, reverse=True)
    return [
        {
            "version": _short(v.name),
            "created": v.create_time.isoformat() if v.create_time else None,
            "disabled": v.disabled,
        }
        for v in versions[:limit]
    ]


def create_version(project: str, parameter: str, version: str, payload: str) -> str:
    """Publish a new version, which becomes "latest" for every reader."""
    created = _client(_location()).create_parameter_version(
        parent=parameter_path(project, parameter),
        parameter_version_id=version,
        parameter_version=parametermanager_v1.ParameterVersion(
            payload=parametermanager_v1.ParameterVersionPayload(data=payload.encode("utf-8"))
        ),
    )
    return _short(created.name)
