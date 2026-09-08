"""Generate bounded image batches and register each asset in session state."""

from __future__ import annotations

import functools
from pathlib import Path

from gemini_shared.connectors.cloud_storage import upload_bytes
from gemini_shared.media import ImageRequest, generate_images
from gemini_shared.media.images import MODE_PARALLEL, MODE_SEQUENTIAL_REFERENCE
from google.adk.tools import ToolContext

from .config import OUTPUT_BUCKET, OUTPUT_BUCKET_ENV, PROJECT_ID
from .runs import get_run, new_run_id, safe_slug, save_run
from .schema import MAX_IMAGES_PER_BATCH, MAX_IMAGES_PER_RUN

IMAGE_EXTENSIONS = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}

# Finished cards shipped with the agent. Passing them as references shows the
# model the house look — palette, lighting, unbranded containers, isolated
# ingredients — rather than relying on the prompt to describe it in words.
STYLE_DIR = Path(__file__).resolve().parent / "style"


@functools.cache
def _style_plates() -> tuple[bytes, ...]:
    """Read the reference cards once per process."""
    if not STYLE_DIR.is_dir():
        return ()
    return tuple(path.read_bytes() for path in sorted(STYLE_DIR.glob("*.jpg")))


def _object_name(recipe_slug: str, run_id: str, image_name: str, extension: str = "png") -> str:
    """Group one run's images under their own prefix."""
    return (
        f"{safe_slug(recipe_slug)}/{safe_slug(run_id, 'run')}"
        f"/images/{safe_slug(image_name, 'image')}.{extension}"
    )


def generate_recipe_images(
    recipe_slug: str,
    prompts: list[str],
    names: list[str],
    tool_context: ToolContext,
    mode: str = MODE_PARALLEL,
    run_id: str = "",
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
        run_id: Pass the `run_id` returned by your first call so every image
            for one card is stored together. Omit it on the first call and one
            is created for you.
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
    if len(prompts) > MAX_IMAGES_PER_BATCH:
        raise ValueError(f"At most {MAX_IMAGES_PER_BATCH} images may be generated per batch.")
    if any(not p.strip() or len(p) > 4000 for p in prompts):
        raise ValueError("Each image prompt must contain 1-4000 characters.")
    normalized_names = [safe_slug(name, "") for name in names]
    if not all(normalized_names) or len(set(normalized_names)) != len(names):
        raise ValueError("Image names must be nonempty and unique after normalization.")
    if mode not in (MODE_PARALLEL, MODE_SEQUENTIAL_REFERENCE):
        raise ValueError(
            f"Unknown mode '{mode}'. Use '{MODE_PARALLEL}' for independent images "
            f"or '{MODE_SEQUENTIAL_REFERENCE}' for a consistent series."
        )

    slug = safe_slug(recipe_slug)
    run = get_run(tool_context, run_id) if run_id else {"slug": slug, "images": {}}
    if run["slug"] != slug:
        raise ValueError("The run belongs to a different recipe.")
    existing = dict(run["images"])
    if set(normalized_names) & existing.keys():
        raise ValueError("An image with that name already exists in this run; use a new name.")
    if len(existing) + len(names) > MAX_IMAGES_PER_RUN:
        raise ValueError(f"At most {MAX_IMAGES_PER_RUN} images may be generated per recipe run.")
    run_id = run_id or new_run_id()
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

    uris = {}
    for image in images:
        if image.mime_type not in IMAGE_EXTENSIONS:
            raise ValueError("Unsupported generated image type.")
        uri = upload_bytes(
            PROJECT_ID,
            OUTPUT_BUCKET,
            _object_name(slug, run_id, image.name, IMAGE_EXTENSIONS[image.mime_type]),
            image.data,
            image.mime_type,
            create_only=True,
        )
        uris[image.name] = uri
        existing[safe_slug(image.name)] = uri
        save_run(tool_context, run_id, {"slug": slug, "images": existing})
    return {
        "bucket": OUTPUT_BUCKET,
        "bucket_created": False,
        "mode": mode,
        # Pass this back on the next call and to render_recipe_card, so one
        # card's images and deck stay together.
        "run_id": run_id,
        "image_count": len(uris),
        "images": uris,
    }
