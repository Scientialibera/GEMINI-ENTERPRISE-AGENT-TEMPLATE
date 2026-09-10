"""No-cloud tests for configurable attempts and cross-stage call limits."""

import asyncio
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from gemini_shared.config.runtime_config import RuntimeConfig
from gemini_shared.limits import RuntimeLimitsPlugin
from google.adk.agents import Agent, SequentialAgent
from google.adk.agents.run_config import RunConfig
from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.adk.runners import InMemoryRunner
from google.genai import types


@pytest.mark.parametrize("field", ["max_attempts", "max_model_calls_per_request"])
@pytest.mark.parametrize("value", [0, -1, 101])
def test_invalid_limits_rejected(field, value):
    with pytest.raises(ValueError):
        RuntimeConfig(config_revision="test", model="test", instruction="test", **{field: value})


def test_caller_cannot_raise_server_limit(monkeypatch):
    monkeypatch.setenv("MAX_MODEL_CALLS_PER_REQUEST", "20")
    context = SimpleNamespace(run_config=RunConfig(max_llm_calls=999))
    asyncio.run(RuntimeLimitsPlugin().before_run_callback(invocation_context=context))
    assert context.run_config.max_llm_calls == 20
    context.run_config = RunConfig(max_llm_calls=2)
    asyncio.run(RuntimeLimitsPlugin().before_run_callback(invocation_context=context))
    assert context.run_config.max_llm_calls == 2


def test_transport_attempts_use_live_setting(monkeypatch):
    monkeypatch.setenv("MAX_ATTEMPTS", "2")
    request = LlmRequest()
    asyncio.run(
        RuntimeLimitsPlugin().before_model_callback(callback_context=None, llm_request=request)
    )
    assert request.config.http_options.retry_options.attempts == 2


def test_image_retries_stop_at_configured_attempts(monkeypatch):
    from gemini_shared.media import images

    monkeypatch.setenv("MAX_ATTEMPTS", "3")
    monkeypatch.setattr(images.time, "sleep", lambda _: None)
    call = Mock(side_effect=images.NoImageReturned("no image"))
    with pytest.raises(images.NoImageReturned):
        images._with_retries(call, "test")
    assert call.call_count == 3


def test_request_budget_is_shared_across_workflow_stages(monkeypatch):
    from google.adk.agents.invocation_context import LlmCallsLimitExceededError

    monkeypatch.setenv("MAX_MODEL_CALLS_PER_REQUEST", "1")
    calls = []

    class FakeModel(BaseLlm):
        async def generate_content_async(self, llm_request, stream=False):
            calls.append(llm_request)
            yield LlmResponse(content=types.Content(role="model", parts=[types.Part(text="Done")]))

    async def run():
        root = SequentialAgent(
            name="workflow",
            sub_agents=[
                Agent(name=name, model=FakeModel(model="fake")) for name in ("first", "second")
            ],
        )
        runner = InMemoryRunner(agent=root, app_name="test", plugins=[RuntimeLimitsPlugin()])
        session = await runner.session_service.create_session(app_name="test", user_id="test")
        with pytest.raises(LlmCallsLimitExceededError):
            async for _ in runner.run_async(
                user_id="test",
                session_id=session.id,
                new_message=types.Content(role="user", parts=[types.Part(text="Start")]),
            ):
                pass
        await runner.close()

    asyncio.run(run())
    assert len(calls) == 1
