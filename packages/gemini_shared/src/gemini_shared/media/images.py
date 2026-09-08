"""Generate images in batches, optionally chaining each one onto the last.

A card needs a dozen or more images, so the unit of work here is a batch
rather than a single call. Two modes cover what a document needs:

- ``parallel``             independent prompts use the configured worker limit.
  Ingredient cutouts work this way: an onion does not depend on a carrot.
- ``sequential_reference`` each image receives the ones already produced in
  this batch as references, so a series holds the same pot, surface and
  lighting. Step photography works this way.

Chaining inside the tool is what keeps the agent from having to make one call
per step and carry image bytes through the conversation.
"""

from __future__ import annotations

import concurrent.futures
import os
import random
import threading
import time
from dataclasses import dataclass, field

from google import genai
from google.genai import errors as genai_errors
from google.genai import types

# The model accepts a bounded number of reference images per request, so a long
# sequence keeps the most recent ones and drops the oldest.
MAX_REFERENCE_IMAGES = 14
DEFAULT_IMAGE_MODEL = "gemini-3.1-flash-image"
IMAGE_MODEL_ENV = "IMAGE_MODEL"
IMAGE_MODEL_LOCATION_ENV = "IMAGE_MODEL_LOCATION"
DEFAULT_IMAGE_MODEL_LOCATION = "global"
DEFAULT_MIME_TYPE = "image/png"
MODE_PARALLEL = "parallel"
MODE_SEQUENTIAL_REFERENCE = "sequential_reference"
# Serialize image calls by default; project quotas vary.
MAX_PARALLEL_WORKERS = 1

# Spacing between requests, applied across the whole process, matched to the
# quota with a little headroom. Pacing to the real limit is what keeps a batch
# from spending its retries on rejections it could have avoided.
IMAGE_REQUESTS_PER_MINUTE = 2
MIN_REQUEST_INTERVAL_SECONDS = 60.0 / IMAGE_REQUESTS_PER_MINUTE + 2.0

# Image generation is quota-limited per minute, and a batch is precisely the
# thing that exhausts it. Retrying with an exponential, jittered backoff is what
# keeps a large card from failing halfway through and wasting the images that
# already succeeded.
MAX_ATTEMPTS = 8
INITIAL_BACKOFF_SECONDS = 15.0
BACKOFF_MULTIPLIER = 2.0
MAX_BACKOFF_SECONDS = 90.0
# 401 is included deliberately: under concurrent load the service returns it
# for a request whose credential is momentarily unusable, not for one that is
# genuinely unauthorised, and a retry with a fresh client succeeds.
RETRYABLE_STATUS_CODES = frozenset({401, 429, 500, 502, 503, 504})


@dataclass(frozen=True, slots=True)
class ImageRequest:
    """One image to generate.

    Args:
        prompt: What to draw. The caller supplies the full art direction.
        name: Stable identifier, used to name the stored object.
        reference_images: Bytes the caller already has, such as a house style
            plate. In ``sequential_reference`` mode the images produced earlier
            in the batch are appended to these.
    """

    prompt: str
    name: str
    reference_images: tuple[bytes, ...] = field(default=())


@dataclass(frozen=True, slots=True)
class GeneratedImage:
    """One generated image and the request it came from."""

    name: str
    data: bytes
    mime_type: str
    prompt: str


_rate_lock = threading.Lock()
_last_request_at = 0.0


def _wait_for_slot() -> None:
    """Space requests out to the service's rate limit.

    Held across threads, so the parallel mode is paced by the same limit the
    sequential mode is.
    """
    global _last_request_at
    with _rate_lock:
        wait = MIN_REQUEST_INTERVAL_SECONDS - (time.monotonic() - _last_request_at)
        if wait > 0:
            time.sleep(wait)
        _last_request_at = time.monotonic()


def _client(location: str) -> genai.Client:
    """Vertex-backed client, so generation runs under the runtime's identity.

    Credentials are left to the client rather than resolved here. On Agent
    Runtime the Agent Identity is supplied through a mechanism that
    ``google.auth.default`` does not reproduce: re-resolving it yields a
    credential the API rejects as unauthenticated, while the ambient one works.

    The location is passed explicitly because the image models are served from
    ``global`` and the runtime's own GOOGLE_CLOUD_LOCATION is the region the
    agent is deployed to, where they do not exist.
    """
    return genai.Client(
        vertexai=True,
        project=os.environ["GOOGLE_CLOUD_PROJECT"],
        location=location,
    )


def _model_name() -> str:
    return os.getenv(IMAGE_MODEL_ENV, "").strip() or DEFAULT_IMAGE_MODEL


def _model_location() -> str:
    return os.getenv(IMAGE_MODEL_LOCATION_ENV, "").strip() or DEFAULT_IMAGE_MODEL_LOCATION


class NoImageReturned(RuntimeError):
    """The call succeeded but carried no image.

    Distinct from an API error because it is retried: the model intermittently
    answers a perfectly acceptable prompt with text or an empty candidate, and
    the same prompt succeeds on a second attempt.
    """


def _extract_image(response: object, name: str) -> tuple[bytes, str]:
    """Return the first inline image, or explain what came back instead.

    A refusal or a text-only answer arrives as a normal response, so failing
    here with the model's own words is more useful than an attribute error.
    """
    candidates = getattr(response, "candidates", None) or []
    for candidate in candidates:
        content = getattr(candidate, "content", None)
        for part in getattr(content, "parts", None) or []:
            inline = getattr(part, "inline_data", None)
            if inline is not None and inline.data:
                return inline.data, inline.mime_type or DEFAULT_MIME_TYPE

    text = getattr(response, "text", None)
    detail = f" The model returned text instead: {text.strip()[:300]}" if text else ""
    finish = ""
    for candidate in candidates:
        reason = getattr(candidate, "finish_reason", None)
        if reason:
            finish = f" finish_reason={reason}."
            break
    raise NoImageReturned(f"No image was returned for '{name}'.{finish}{detail}")


def _sniff_mime(data: bytes) -> str:
    """Identify a reference image from its magic bytes.

    References come from the caller and need not be PNG, and declaring the
    wrong type makes the request fail rather than degrade.
    """
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "image/webp"
    return DEFAULT_MIME_TYPE


def _is_retryable(error: Exception) -> bool:
    """Whether the failure is a transient quota, server or empty-response error."""
    if isinstance(error, NoImageReturned):
        return True
    code = getattr(error, "code", None) or getattr(error, "status_code", None)
    if code in RETRYABLE_STATUS_CODES:
        return True
    # Some transports surface the status only in the message.
    return isinstance(error, genai_errors.APIError) and any(
        str(status) in str(error) for status in RETRYABLE_STATUS_CODES
    )


def _with_retries(call, name: str):
    """Run ``call``, backing off exponentially while the failure is transient."""
    delay = INITIAL_BACKOFF_SECONDS
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            return call()
        except Exception as error:
            if attempt == MAX_ATTEMPTS or not _is_retryable(error):
                raise
            capped = min(delay, MAX_BACKOFF_SECONDS)
            # Equal jitter avoids both synchronized retries and near-zero waits.
            time.sleep(random.uniform(capped / 2, capped))  # noqa: S311
            delay *= BACKOFF_MULTIPLIER
    raise RuntimeError(f"Exhausted retries generating '{name}'.")


def _generate_one(
    location: str,
    model: str,
    request: ImageRequest,
    extra_references: tuple[bytes, ...],
) -> GeneratedImage:
    parts: list[types.Part] = [types.Part(text=request.prompt)]
    references = (*request.reference_images, *extra_references)
    # Keep the most recent references when a long sequence exceeds the limit:
    # the nearest neighbours carry the style that must not drift.
    for reference in references[-MAX_REFERENCE_IMAGES:]:
        parts.append(
            types.Part(inline_data=types.Blob(mime_type=_sniff_mime(reference), data=reference))
        )

    def call():
        _wait_for_slot()
        # Each attempt owns and closes its client.
        with _client(location) as client:
            response = client.models.generate_content(
                model=model,
                contents=[types.Content(role="user", parts=parts)],
                config=types.GenerateContentConfig(response_modalities=["IMAGE"]),
            )
        # Extracted inside the retried call, so a response that carries no
        # image is retried rather than ending the batch.
        return _extract_image(response, request.name)

    data, mime_type = _with_retries(call, request.name)
    return GeneratedImage(
        name=request.name,
        data=data,
        mime_type=mime_type,
        prompt=request.prompt,
    )


def generate_images(
    requests: list[ImageRequest],
    *,
    mode: str = MODE_PARALLEL,
) -> list[GeneratedImage]:
    """Generate every requested image, returning them in the requested order.

    Args:
        requests: The images to produce.
        mode: ``parallel`` when the prompts are independent, or
            ``sequential_reference`` when each image should inherit the look of
            the ones before it.

    Raises:
        ValueError: The mode is not one of the two supported values.
    """
    if mode not in (MODE_PARALLEL, MODE_SEQUENTIAL_REFERENCE):
        raise ValueError(
            f"Unknown image generation mode '{mode}'. "
            f"Use '{MODE_PARALLEL}' or '{MODE_SEQUENTIAL_REFERENCE}'."
        )
    if not requests:
        return []

    location = _model_location()
    model = _model_name()

    if mode == MODE_SEQUENTIAL_REFERENCE:
        produced: list[GeneratedImage] = []
        for request in requests:
            image = _generate_one(location, model, request, tuple(item.data for item in produced))
            produced.append(image)
        return produced

    # Pace independent requests and return results in input order.
    workers = min(len(requests), MAX_PARALLEL_WORKERS)
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(_generate_one, location, model, request, ()): index
            for index, request in enumerate(requests)
        }
        results: list[GeneratedImage | None] = [None] * len(requests)
        for future in concurrent.futures.as_completed(futures):
            results[futures[future]] = future.result()

    return [image for image in results if image is not None]
