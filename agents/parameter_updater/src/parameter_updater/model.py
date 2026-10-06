"""Recover once when the model rejects a cached access token."""

from __future__ import annotations

import logging

from google.adk.models import Gemini, LlmRequest, LlmResponse
from google.genai import types
from google.genai.errors import ClientError

LOGGER = logging.getLogger(__name__)


class RefreshingGemini(Gemini):
    async def generate_content_async(self, llm_request: LlmRequest, stream: bool = False):
        original = llm_request.model_copy(deep=True)
        for attempt in range(2):
            emitted = False
            try:
                async for response in super().generate_content_async(
                    original.model_copy(deep=True), stream=stream
                ):
                    emitted = True
                    yield response
                return
            except ClientError as error:
                if error.code != 401 or emitted:
                    raise
                if attempt == 0:
                    LOGGER.warning(
                        "Model rejected its credentials; rebuilding client and retrying once"
                    )
                    self.__dict__.pop("api_client", None)
                    self.__dict__.pop("_api_backend", None)
                    continue
                LOGGER.error("Model authentication failed after one fresh-client retry")
                yield LlmResponse(
                    content=types.Content(
                        role="model",
                        parts=[
                            types.Part(
                                text=(
                                    "I couldn't complete this request because model "
                                    "authentication failed. "
                                    "Check the target parameter's latest version before retrying. "
                                    "If the preview is gone, create and confirm a new one."
                                )
                            )
                        ],
                    ),
                    turn_complete=True,
                )
                return
