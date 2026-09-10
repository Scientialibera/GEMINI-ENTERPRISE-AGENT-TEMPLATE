"""Browse and retrieve published card assets by relative path.

The model never handles a bucket name or a ``gs://`` URI. ``list_folders``
returns paths relative to the use-case root and ``retrieve`` resolves them back
against that same root, so a recipe can only ever name an asset a listing
already offered. Authorization is therefore structural: there is no allowlist to
compare against and no absolute location for a payload to point elsewhere.

Session state is per conversation and keeps only the most recent runs, so it
cannot answer "does a chili card already exist?" in a fresh chat. The bucket
outlives every conversation and is the source of truth here.
"""

from __future__ import annotations

from gemini_shared.connectors.cloud_storage import download_bytes, list_objects
from google.adk.tools import ToolContext
from google.genai import types

from .config import OUTPUT_BUCKET, OUTPUT_BUCKET_ENV, PROJECT_ID, USE_CASE_PREFIX, resolve_relative

# Bounded so listing stays cheap metadata calls rather than a walk of the bucket.
MAX_DISHES = 100
MAX_RUNS_PER_DISH = 50
MAX_OBJECTS_PER_FOLDER = 400
# One preview only, and small: pixels in a prompt are expensive and a card is
# rendered from bytes the renderer fetches itself, not from what the model sees.
MAX_PREVIEW_BYTES = 4 * 1024 * 1024
DECK_SUFFIX = ".pptx"
IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp")


def _require_bucket() -> None:
    if not OUTPUT_BUCKET:
        raise RuntimeError(f"{OUTPUT_BUCKET_ENV} is not set, so there are no cards to browse.")


def _relative(object_name: str) -> str:
    return object_name.removeprefix(f"{USE_CASE_PREFIX}/")


def list_folders() -> dict[str, object]:
    """List every published recipe card folder, newest run first.

    Call this before generating a card, so a dish that already has one can be
    offered for reuse instead of being photographed again. Paths are relative
    to the card store; pass them to `retrieve` to see or use a folder's files.
    """
    _require_bucket()
    _, dish_prefixes, truncated = list_objects(
        PROJECT_ID, OUTPUT_BUCKET, f"{USE_CASE_PREFIX}/", limit=MAX_DISHES, delimiter="/"
    )

    folders: list[dict[str, object]] = []
    for dish_prefix in dish_prefixes:
        dish = _relative(dish_prefix).rstrip("/")
        _, run_prefixes, dish_truncated = list_objects(
            PROJECT_ID, OUTPUT_BUCKET, dish_prefix, limit=MAX_RUNS_PER_DISH, delimiter="/"
        )
        truncated = truncated or dish_truncated
        # Run IDs begin with a timestamp, so reverse order is newest first.
        for run_prefix in sorted(run_prefixes, reverse=True):
            folders.append({"dish": dish, "path": _relative(run_prefix).rstrip("/")})
    return {
        "folder_count": len(folders),
        "folders": folders,
        # Say so rather than implying the list is complete.
        "truncated": truncated,
    }


def retrieve(
    folders: list[str], tool_context: ToolContext, preview_image: str = ""
) -> dict[str, object]:
    """List the files in one or more card folders, ready to use in a recipe.

    Give the relative paths `list_folders` returned. Returns each file's
    relative path, which is what a recipe's image fields take, plus a link for
    any finished deck. File contents are not returned: the renderer fetches the
    images itself.

    Args:
        folders: Relative folder paths, for example
            `classic-beef-chili/20260910-120000-abc`.
        preview_image: Optionally, the relative path of one image to look at.
            Use it only when the user asks about how a photograph looks; it is
            unnecessary for building a card.
    """
    _require_bucket()
    if not folders:
        raise ValueError("Name at least one folder from list_folders.")

    images: list[dict[str, object]] = []
    decks: list[dict[str, str]] = []
    truncated = False
    for folder in folders:
        prefix = resolve_relative(folder).rstrip("/") + "/"
        names, _, folder_truncated = list_objects(
            PROJECT_ID, OUTPUT_BUCKET, prefix, limit=MAX_OBJECTS_PER_FOLDER
        )
        truncated = truncated or folder_truncated
        for name in names:
            entry = {"path": _relative(name), "folder": folder.strip("/")}
            if name.endswith(DECK_SUFFIX):
                decks.append(
                    {**entry, "url": f"https://storage.cloud.google.com/{OUTPUT_BUCKET}/{name}"}
                )
            elif name.lower().endswith(IMAGE_SUFFIXES):
                images.append(entry)

    result: dict[str, object] = {
        "image_count": len(images),
        "images": images,
        "decks": decks,
        "truncated": truncated,
    }
    if preview_image:
        result["preview"] = _preview(preview_image, tool_context)
    return result


def _preview(path: str, tool_context: ToolContext) -> str:
    """Save one image as an artifact so the model can look at it."""
    object_name = resolve_relative(path)
    if not object_name.lower().endswith(IMAGE_SUFFIXES):
        raise ValueError("Only an image can be previewed.")
    content = download_bytes(
        PROJECT_ID, f"gs://{OUTPUT_BUCKET}/{object_name}", max_bytes=MAX_PREVIEW_BYTES
    )
    suffix = object_name.rsplit(".", 1)[-1].lower()
    mime = "image/jpeg" if suffix in ("jpg", "jpeg") else f"image/{suffix}"
    filename = _relative(object_name).replace("/", "_")
    tool_context.save_artifact(filename, types.Part.from_bytes(data=content, mime_type=mime))
    return filename
