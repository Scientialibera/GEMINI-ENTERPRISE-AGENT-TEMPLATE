"""Tool-call logging levels, and what each one is allowed to disclose.

A tool's arguments are the signed-in user's own request text, so the levels
below ``full`` must name the call without ever recording what was asked for.
"""

from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace

import pytest
from gemini_shared.config.runtime_config import (
    TOOL_CALL_LOGGING_LEVELS,
    RuntimeConfig,
)
from gemini_shared.limits import RuntimeLimitsPlugin

# Stand-ins for what a delegated tool actually receives: the signed-in user's
# own query text and paths. Named for what they are, since S105 reads a
# "SECRET_" prefix as a credential.
USER_SQL = "SELECT ssn FROM customers"
USER_PATH = "chili/private-run/images/hero.png"
TOOL = SimpleNamespace(name="execute_sql_readonly")
ARGS = {"sql": USER_SQL, "path": USER_PATH}


def _config(level: str) -> RuntimeConfig:
    return RuntimeConfig(
        config_revision="test", model="test-model", instruction="test", tool_call_logging=level
    )


def _run(monkeypatch, caplog, level: str, *, error: Exception | None = None) -> str:
    from gemini_shared import limits

    monkeypatch.setattr(limits, "get_runtime_config", lambda: _config(level))
    plugin = RuntimeLimitsPlugin()
    context = SimpleNamespace(state={})
    with caplog.at_level(logging.INFO, logger="gemini_shared.limits"):
        asyncio.run(plugin.before_tool_callback(tool=TOOL, tool_args=ARGS, tool_context=context))
        if error is None:
            asyncio.run(
                plugin.after_tool_callback(
                    tool=TOOL, tool_args=ARGS, tool_context=context, result={"rows": [USER_SQL]}
                )
            )
        else:
            asyncio.run(
                plugin.on_tool_error_callback(
                    tool=TOOL, tool_args=ARGS, tool_context=context, error=error
                )
            )
    return caplog.text


def test_off_records_nothing(monkeypatch, caplog):
    """The default must leave logs exactly as they were."""
    assert _run(monkeypatch, caplog, "off") == ""


def test_names_identifies_the_call_without_disclosing_it(monkeypatch, caplog):
    """This is the level that answers 'which tools ran'."""
    text = _run(monkeypatch, caplog, "names")

    assert "tool_call execute_sql_readonly" in text
    assert "tool_done execute_sql_readonly" in text
    # Nothing the user typed may appear.
    assert USER_SQL not in text
    assert USER_PATH not in text
    assert "args=" not in text


def test_argument_keys_names_parameters_but_not_values(monkeypatch, caplog):
    text = _run(monkeypatch, caplog, "argument_keys")

    assert "args=['path', 'sql']" in text
    assert USER_SQL not in text
    assert USER_PATH not in text


def test_full_records_values_as_documented(monkeypatch, caplog):
    """The one level that does disclose, so it must be unmistakable."""
    text = _run(monkeypatch, caplog, "full")

    assert USER_SQL in text
    assert USER_PATH in text


@pytest.mark.parametrize("level", ["names", "argument_keys"])
def test_errors_below_full_report_only_the_type(monkeypatch, caplog, level):
    """An exception message can quote the input that caused it."""
    text = _run(monkeypatch, caplog, level, error=ValueError(USER_SQL))

    assert "tool_error execute_sql_readonly ValueError" in text
    assert USER_SQL not in text


def test_full_errors_include_the_message(monkeypatch, caplog):
    text = _run(monkeypatch, caplog, "full", error=ValueError(USER_SQL))
    assert USER_SQL in text


def test_logging_failure_never_breaks_a_tool_call(monkeypatch, caplog):
    """An unreadable parameter must not take the agent down with it."""
    from gemini_shared import limits

    def unavailable():
        raise RuntimeError("Parameter Manager unreachable")

    monkeypatch.setattr(limits, "get_runtime_config", unavailable)
    plugin = RuntimeLimitsPlugin()
    with caplog.at_level(logging.INFO, logger="gemini_shared.limits"):
        asyncio.run(
            plugin.before_tool_callback(
                tool=TOOL, tool_args=ARGS, tool_context=SimpleNamespace(state={})
            )
        )
    assert caplog.text == ""


def test_an_invalid_level_fails_at_config_load():
    """A typo must not silently disable logging."""
    with pytest.raises(ValueError, match="tool_call_logging must be one of"):
        _config("verbose")


def test_default_is_off_so_existing_parameters_are_unchanged():
    config = RuntimeConfig(config_revision="test", model="m", instruction="i")
    assert config.tool_call_logging == "off"
    assert "off" in TOOL_CALL_LOGGING_LEVELS
