"""Generate a batch of recipe photographs and publish them to Cloud Storage.

One call produces a whole set, so a card costs two tool calls rather than one
per photograph. The agent chooses the mode: ingredient cutouts are independent
and run in parallel, while step photographs run sequentially so each inherits
the pot, surface and lighting of the ones before it.
"""

from __future__ import annotations

import functools
import re
from pathlib import Path

from gemini_shared.connectors.cloud_storage import ensure_bucket, upload_bytes
from gemini_shared.media import ImageRequest, generate_images
from gemini_shared.media.images import MODE_PARALLEL, MODE_SEQUENTIAL_REFERENCE

from ..config import OUTPUT_BUCKET, OUTPUT_BUCKET_ENV, OUTPUT_BUCKET_LOCATION, PROJECT_ID

IMAGE_CONTENT_TYPE = "image/png"
UNSAFE_NAME = re.compile(r"[^a-z0-9]+")

# Finished cards shipped with the agent. Passing them as references shows the
# model the house look — palette, lighting, unbranded containers, isolated
# ingredients — rather than relying on the prompt to describe it in words.
STYLE_DIR = Path(__file__).resolve().parents[1] / "style"


@functools.cache
def _style_plates() -> tuple[bytes, ...]:
    """Read the reference cards once per process."""
    if not STYLE_DIR.is_dir():
        return ()
    return tuple(path.read_bytes() for path in sorted(STYLE_DIR.glob("*.jpg")))


def _object_name(recipe_slug: str, image_name: str) -> str:
    """Group a recipe's images under its own prefix."""
    slug = UNSAFE_NAME.sub("-", recipe_slug.strip().lower()).strip("-") or "recipe"
    name = UNSAFE_NAME.sub("-", image_name.strip().lower()).strip("-") or "image"
    return f"{slug}/images/{name}.png"


def generate_recipe_images(
    recipe_slug: str,
    prompts: list[str],
    names: list[str],
    mode: str = MODE_PARALLEL,
) -> dict[str, object]:
    """Generate recipe photographs and store them, returning their gs:// URIs.

    Use `parallel` for images that do not depend on each other, such as the
    ingredient cutouts. Use `sequential_reference` for a series that must look
    like one continuous shoot, such as the numbered cooking steps: each image
    is generated with the previous ones as references, so the pot, surface and
    lighting stay the same without you passing images yourself.

    Write the full art direction into every prompt. Nothing is added for you.

    Args:
        recipe_slug: Identifier for the recipe, used as the storage prefix.
        prompts: One prompt per image, in the order they should be produced.
        names: One short name per image, positionally matching `prompts`.
            Used as the stored file name, for example `hero` or `step-1`.
        mode: `parallel` or `sequential_reference`.
    """
    if not OUTPUT_BUCKET:
        raise RuntimeError(
            f"{OUTPUT_BUCKET_ENV} is not set, so there is nowhere to publish the images."
        )
    if len(prompts) != len(names):
        raise ValueError(
            f"Received {len(prompts)} prompts and {len(names)} names. "
            "Supply exactly one name per prompt."
        )
    if not prompts:
        raise ValueError("No prompts were supplied.")
    if mode not in (MODE_PARALLEL, MODE_SEQUENTIAL_REFERENCE):
        raise ValueError(
            f"Unknown mode '{mode}'. Use '{MODE_PARALLEL}' for independent images "
            f"or '{MODE_SEQUENTIAL_REFERENCE}' for a consistent series."
        )

    created = ensure_bucket(PROJECT_ID, OUTPUT_BUCKET, OUTPUT_BUCKET_LOCATION)
    # Every image carries the house style plates. In sequential mode the batch's
    # own earlier images are appended to these by the shared helper.
    plates = _style_plates()
    images = generate_images(
        [
            ImageRequest(prompt=prompt, name=name, reference_images=plates)
            for prompt, name in zip(prompts, names, strict=True)
        ],
        mode=mode,
    )

    uris = {
        image.name: upload_bytes(
            PROJECT_ID,
            OUTPUT_BUCKET,
            _object_name(recipe_slug, image.name),
            image.data,
            IMAGE_CONTENT_TYPE,
        )
        for image in images
    }
    return {
        "bucket": OUTPUT_BUCKET,
        "bucket_created": created,
        "mode": mode,
        "image_count": len(uris),
        "images": uris,
    }
