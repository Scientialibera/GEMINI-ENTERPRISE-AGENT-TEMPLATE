"""Generate images in batches, optionally chaining each one onto the last.

A card needs a dozen or more images, so the unit of work here is a batch
rather than a single call. Two modes cover what a document needs:

- ``parallel``             every prompt is independent, so they run at once.
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
MAX_PARALLEL_WORKERS = 8

# Image generation is quota-limited per minute, and a batch is precisely the
# thing that exhausts it. Retrying with an exponential, jittered backoff is what
# keeps a large card from failing halfway through and wasting the images that
# already succeeded.
MAX_ATTEMPTS = 6
INITIAL_BACKOFF_SECONDS = 10.0
BACKOFF_MULTIPLIER = 2.0
MAX_BACKOFF_SECONDS = 120.0
RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})


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


def _client(location: str) -> genai.Client:
    """Vertex-backed client, so generation runs under the runtime's identity."""
    return genai.Client(
        vertexai=True,
        project=os.environ["GOOGLE_CLOUD_PROJECT"],
        location=location,
    )


def _model_name() -> str:
    return os.getenv(IMAGE_MODEL_ENV, "").strip() or DEFAULT_IMAGE_MODEL


def _model_location() -> str:
    return os.getenv(IMAGE_MODEL_LOCATION_ENV, "").strip() or DEFAULT_IMAGE_MODEL_LOCATION


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
    raise RuntimeError(f"No image was returned for '{name}'.{detail}")


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
    """Whether the failure is a transient quota or server error."""
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
            # Full jitter, so a parallel batch that hit the limit together does
            # not retry in lockstep and exhaust it again.
            time.sleep(random.uniform(0, min(delay, MAX_BACKOFF_SECONDS)))  # noqa: S311
            delay *= BACKOFF_MULTIPLIER
    raise RuntimeError(f"Exhausted retries generating '{name}'.")


def _generate_one(
    client: genai.Client,
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

    response = _with_retries(
        lambda: client.models.generate_content(
            model=model,
            contents=[types.Content(role="user", parts=parts)],
            config=types.GenerateContentConfig(response_modalities=["IMAGE"]),
        ),
        request.name,
    )
    data, mime_type = _extract_image(response, request.name)
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

    client = _client(_model_location())
    model = _model_name()

    if mode == MODE_SEQUENTIAL_REFERENCE:
        produced: list[GeneratedImage] = []
        for request in requests:
            image = _generate_one(client, model, request, tuple(item.data for item in produced))
            produced.append(image)
        return produced

    # Independent prompts, so the wall-clock cost is one image rather than all
    # of them. Results are reordered to match the requests.
    workers = min(len(requests), MAX_PARALLEL_WORKERS)
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(_generate_one, client, model, request, ()): index
            for index, request in enumerate(requests)
        }
        results: list[GeneratedImage | None] = [None] * len(requests)
        for future in concurrent.futures.as_completed(futures):
            results[futures[future]] = future.result()

    return [image for image in results if image is not None]
