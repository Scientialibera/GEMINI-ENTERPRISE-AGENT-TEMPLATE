"""A rejected model token gets one fresh-client retry and a visible failure."""

import asyncio

import pytest
from google.adk.models import Gemini, LlmRequest, LlmResponse
from google.genai import types
from google.genai.errors import ClientError
from parameter_updater.model import RefreshingGemini


def _collect(model):
    async def run():
        return [item async for item in model.generate_content_async(LlmRequest(model="test"))]

    return asyncio.run(run())


def test_401_rebuilds_client_and_retries_once(monkeypatch):
    calls = []

    async def generate(self, request, stream=False):
        calls.append(request.model)
        request.model = "changed-by-sdk"
        if len(calls) == 1:
            raise ClientError(401, {"error": {"message": "expired"}})
        yield LlmResponse(content=types.Content(parts=[types.Part(text="ready")]))

    monkeypatch.setattr(Gemini, "generate_content_async", generate)
    model = RefreshingGemini(model="test")
    model.__dict__["api_client"] = object()
    [result] = _collect(model)
    assert result.content.parts[0].text == "ready"
    assert len(calls) == 2
    assert calls == ["test", "test"]
    assert "api_client" not in model.__dict__


def test_second_401_returns_visible_failure(monkeypatch):
    calls = []

    async def generate(self, request, stream=False):
        calls.append(request)
        raise ClientError(401, {"error": {"message": "expired"}})
        yield  # Make this an async generator.

    monkeypatch.setattr(Gemini, "generate_content_async", generate)
    [result] = _collect(RefreshingGemini(model="test"))
    assert len(calls) == 2
    assert "authentication failed" in result.content.parts[0].text
    assert result.turn_complete


def test_non_authentication_error_is_not_retried(monkeypatch):
    calls = []

    async def generate(self, request, stream=False):
        calls.append(request)
        raise ClientError(403, {"error": {"message": "denied"}})
        yield  # Make this an async generator.

    monkeypatch.setattr(Gemini, "generate_content_async", generate)
    with pytest.raises(ClientError):
        _collect(RefreshingGemini(model="test"))
    assert len(calls) == 1
