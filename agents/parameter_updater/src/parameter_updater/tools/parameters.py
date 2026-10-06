"""Inspect agents' runtime parameters and publish reviewed changes to them.

Every agent in this repository renders its parameter's ``latest`` version and
refreshes on a short cache, so a new version changes a running agent's model,
prompt or limits without a redeploy. That makes a publish here a production
change, and the tools are shaped around it:

- A change is previewed first and applied only by the ID the preview returned,
  so the model cannot publish without having shown the user the diff.
- The merged payload is validated against ``RuntimeConfig`` before anything is
  written. An invalid ``latest`` would not be caught by the target's
  last-known-good cache on a cold start, which has nothing to fall back to.
- Applying re-checks that ``latest`` is still the version the preview was based
  on, so two editors cannot silently overwrite each other.

Calls run as this runtime's own Agent Identity, not the signed-in user.
"""

from __future__ import annotations

import difflib
import json
import logging
import re
import time
from uuid import uuid4

from gemini_shared import RuntimeConfig, get_bootstrap_settings, get_runtime_config
from google.adk.tools import ToolContext
from google.api_core import exceptions
from pydantic import ValidationError

from .. import manager
from ..config import PROJECT_ID

LOGGER = logging.getLogger(__name__)

PENDING_PREFIX = "parameter_updater:pending:"
PARAMETER_ID = re.compile(r"^[A-Za-z0-9_-]{1,63}$")
VERSION_ID = re.compile(r"^[A-Za-z0-9_-]{1,63}$")
# Set by the tools, never by a request: the revision identifies the publish,
# and managed_project decides what this agent may edit.
PROTECTED_FIELDS = frozenset({"config_revision", "managed_project"})
# Parameter Manager substitutes __REF__(...) with a Secret Manager payload when
# the version is rendered, so accepting it would let a chat pull a secret into
# a prompt an agent could then be asked to repeat.
SECRET_REFERENCE = "__REF__"  # noqa: S105 - a syntax marker, not a credential
DIFF_LIMIT = 6000
APPROVAL_TEXT_LIMIT = 3000
HISTORY = 10
RELEASE_NOTE = (
    "A release of that agent from the repository republishes its prompt.md when it "
    "differs from the live instruction, replacing this edit. Copy the change into "
    "prompt.md to keep it."
)


def _target_project() -> str:
    return get_runtime_config().managed_project or PROJECT_ID


def _own_parameter() -> str:
    """This agent's own parameter ID, which it must never edit."""
    configured = get_bootstrap_settings().config_parameter or ""
    return configured.split("/parameters/", 1)[-1].split("/", 1)[0]


def _is_self(project: str, parameter: str) -> bool:
    return project == PROJECT_ID and parameter == _own_parameter()


def _error(error: Exception) -> dict[str, object]:
    """A Google API failure as a result the model can explain, not a traceback."""
    message = getattr(error, "message", None) or str(error)
    return {"status": "error", "error_type": type(error).__name__, "error": message}


def _check_parameter(parameter: str) -> str | None:
    if not PARAMETER_ID.match(parameter):
        return "Parameter IDs contain only letters, digits, hyphens and underscores."
    return None


def _as_runtime_config(payload: str) -> dict[str, object] | None:
    """The payload as a validated runtime config, or None if it is not one."""
    try:
        return RuntimeConfig.model_validate(json.loads(payload)).model_dump(exclude_none=True)
    except (ValueError, ValidationError):
        return None


def list_runtime_parameters() -> dict[str, object]:
    """List the parameters in the managed project and summarise each one.

    Reports, per parameter, whether it is an agent runtime configuration, its
    live version and revision, model and instruction length. Parameters that
    are not runtime configurations are listed but cannot be edited here.
    """
    project = _target_project()
    try:
        ids = manager.list_parameter_ids(project)
    except exceptions.GoogleAPICallError as error:
        return {**_error(error), "project": project}

    parameters = []
    for parameter in ids:
        entry: dict[str, object] = {"parameter": parameter}
        try:
            rendered = manager.render(project, parameter)
        except exceptions.NotFound:
            parameters.append({**entry, "runtime_config": False, "note": "no versions"})
            continue
        except exceptions.GoogleAPICallError as error:
            parameters.append({**entry, **_error(error)})
            continue
        config = _as_runtime_config(rendered.payload)
        entry["live_version"] = rendered.version
        entry["runtime_config"] = config is not None
        if config is not None:
            entry["config_revision"] = config["config_revision"]
            entry["model"] = config["model"]
            entry["instruction_chars"] = len(str(config["instruction"]))
        entry["editable"] = config is not None and not _is_self(project, parameter)
        parameters.append(entry)
    return {"status": "ok", "project": project, "parameters": parameters}


def read_runtime_parameter(parameter: str, version: str = "latest") -> dict[str, object]:
    """Return one parameter's full payload and its recent version history.

    Args:
        parameter: The parameter ID, for example `basic-assistant-config`.
        version: A version ID from the history, or `latest` for the live one.
            Read an older version to see what a rollback would restore.
    """
    project = _target_project()
    problem = _check_parameter(parameter) or (
        None if version == "latest" or VERSION_ID.match(version) else "Invalid version ID."
    )
    if problem:
        return {"status": "error", "error": problem}
    try:
        rendered = manager.render(project, parameter, version)
        history = manager.list_versions(project, parameter, HISTORY)
    except exceptions.GoogleAPICallError as error:
        return {**_error(error), "project": project, "parameter": parameter}

    config = _as_runtime_config(rendered.payload)
    return {
        "status": "ok",
        "project": project,
        "parameter": parameter,
        "version": rendered.version,
        "runtime_config": config is not None,
        "editable": config is not None and not _is_self(project, parameter),
        "payload": config if config is not None else rendered.payload,
        "recent_versions": history,
    }


def _diff(before: dict[str, object], after: dict[str, object]) -> list[dict[str, object]]:
    """Field-by-field changes, with long text shown as a unified diff."""
    changes = []
    for field in sorted((before.keys() | after.keys()) - {"config_revision"}):
        old, new = before.get(field), after.get(field)
        if old == new:
            continue
        if isinstance(old, str) and isinstance(new, str) and "\n" in old + new:
            lines = difflib.unified_diff(
                old.splitlines(), new.splitlines(), "live", "proposed", n=1, lineterm=""
            )
            text = "\n".join(lines)
            if len(text) > DIFF_LIMIT:
                text = text[:DIFF_LIMIT] + "\n... (diff truncated)"
            changes.append({"field": field, "diff": text})
        else:
            changes.append({"field": field, "before": old, "after": new})
    return changes


def _approval_text(
    project: str, parameter: str, live_version: str, changes: list[dict[str, object]]
) -> str:
    """Summarize the stored preview for the approval card."""
    sections = [f"Parameter: {parameter}\nProject: {project}\nLive version: {live_version}"]
    for change in changes:
        field = change["field"]
        if "diff" in change:
            detail = change["diff"]
        else:
            before = json.dumps(change["before"], ensure_ascii=False)
            after = json.dumps(change["after"], ensure_ascii=False)
            detail = f"{before} → {after}"
        sections.append(f"{field}:\n{detail}")
    summary = "\n\n".join(sections)
    if len(summary) > APPROVAL_TEXT_LIMIT:
        summary = (
            summary[: APPROVAL_TEXT_LIMIT - 48]
            + "\n... (shortened; review the full diff in chat)"
        )
    return summary


def preview_parameter_update(
    parameter: str, changes_json: str, tool_context: ToolContext
) -> dict[str, object]:
    """Validate a change to one runtime parameter and show what it would do.

    Nothing is published. Show the returned changes to the user and call
    apply_parameter_update with the returned change_id and proposed_update to
    open its approval card.

    Args:
        parameter: The parameter ID, for example `basic-assistant-config`.
        changes_json: A JSON object of the fields to set, merged over the live
            version, for example `{"model": "gemini-3.7-flash"}` or
            `{"instruction": "<the complete new instruction>"}`. The
            instruction is replaced whole, so send its full text. Other fields
            keep their live values.
    """
    project = _target_project()
    problem = _check_parameter(parameter)
    if problem:
        return {"status": "error", "error": problem}
    if _is_self(project, parameter):
        return {
            "status": "refused",
            "error": "This agent does not edit its own configuration. An administrator "
            "changes it in Parameter Manager.",
        }
    try:
        changes = json.loads(changes_json)
    except ValueError as error:
        return {"status": "needs_correction", "error": f"changes_json is not JSON: {error}"}
    if not isinstance(changes, dict) or not changes:
        return {"status": "needs_correction", "error": "changes_json must be a non-empty object."}
    protected = sorted(PROTECTED_FIELDS & changes.keys())
    if protected:
        return {"status": "refused", "error": f"These fields cannot be set here: {protected}."}
    if SECRET_REFERENCE in json.dumps(changes):
        return {"status": "refused", "error": f"Values may not contain {SECRET_REFERENCE}."}

    try:
        live = manager.render(project, parameter)
    except exceptions.GoogleAPICallError as error:
        return {**_error(error), "project": project, "parameter": parameter}
    current = _as_runtime_config(live.payload)
    if current is None:
        return {
            "status": "refused",
            "error": "The live version is not an agent runtime configuration, so it is "
            "not edited here.",
        }

    revision = f"chat-{time.strftime('%Y%m%d-%H%M%S')}-{uuid4().hex[:6]}"
    try:
        proposed = RuntimeConfig.model_validate(
            {**current, **changes, "config_revision": revision}
        ).model_dump(exclude_none=True)
    except ValidationError as invalid:
        problems = [
            f"{'.'.join(str(p) for p in e['loc']) or 'payload'}: {e['msg']}"
            for e in invalid.errors()
        ]
        return {"status": "needs_correction", "error": "; ".join(problems)}

    diff = _diff(current, proposed)
    if not diff:
        return {"status": "no_change", "parameter": parameter, "live_version": live.version}

    change_id = uuid4().hex[:8]
    proposed_update = _approval_text(project, parameter, live.version, diff)
    tool_context.state[f"{PENDING_PREFIX}{change_id}"] = {
        "project": project,
        "parameter": parameter,
        "base_version": live.version,
        "revision": revision,
        "payload": json.dumps(proposed),
        "instruction_changed": any(c["field"] == "instruction" for c in diff),
        "proposed_update": proposed_update,
    }
    return {
        "status": "awaiting_confirmation",
        "change_id": change_id,
        "project": project,
        "parameter": parameter,
        "live_version": live.version,
        "new_revision": revision,
        "changes": diff,
        "proposed_update": proposed_update,
    }


def apply_parameter_update(
    change_id: str, proposed_update: str, tool_context: ToolContext
) -> dict[str, object]:
    """Publish a previewed change after its ADK confirmation card is approved.

    The new version becomes the agent's live configuration on its next cache
    refresh, without a redeploy.

    Args:
        change_id: The change_id preview_parameter_update returned.
        proposed_update: Copy the preview's proposed_update exactly. This is
            displayed on the approval card and checked against the stored preview.
    """
    key = f"{PENDING_PREFIX}{change_id}"
    pending = tool_context.state.get(key)
    if not pending:
        return {
            "status": "error",
            "error": "No pending change has that ID. Preview the change again.",
        }
    if proposed_update != pending["proposed_update"]:
        return {
            "status": "refused",
            "error": "Approval text differs from the stored preview. Use the exact "
            "proposed_update returned by preview_parameter_update.",
        }
    project, parameter = pending["project"], pending["parameter"]
    if project != _target_project():
        tool_context.state[key] = None
        return {"status": "stale", "error": "The managed project changed. Preview again."}

    try:
        # Refuse to publish over a version the user never saw.
        live = manager.render(project, parameter)
        if live.version != pending["base_version"]:
            tool_context.state[key] = None
            return {
                "status": "stale",
                "error": f"{parameter} changed since the preview (now {live.version}, "
                f"was {pending['base_version']}). Read it and preview again.",
            }
        version = manager.create_version(
            project, parameter, pending["revision"], pending["payload"]
        )
    except exceptions.GoogleAPICallError as error:
        return {**_error(error), "project": project, "parameter": parameter}

    tool_context.state[key] = None
    # Audit logs name this runtime's identity, not the person, so the log line
    # records who asked.
    LOGGER.info(
        "Published parameter version %s/%s/%s over %s for user %s",
        project,
        parameter,
        version,
        pending["base_version"],
        tool_context.user_id,
    )
    result: dict[str, object] = {
        "status": "applied",
        "project": project,
        "parameter": parameter,
        "version": version,
        "previous_version": pending["base_version"],
        "takes_effect": "on each runtime's next configuration refresh, typically within "
        f"{get_bootstrap_settings().refresh_seconds} seconds; no redeploy is needed",
        "rollback": f"read {parameter} at version {pending['base_version']} and preview "
        "its values as a new change",
    }
    if pending["instruction_changed"]:
        result["note"] = RELEASE_NOTE
    return result
