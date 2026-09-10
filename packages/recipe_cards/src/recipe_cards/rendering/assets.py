"""Request-scoped image resolution with bounded downloads."""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from gemini_shared.connectors.cloud_storage import download_bytes
from PIL import Image

from ..config import resolve_relative

MAX_IMAGE_BYTES = 12 * 1024 * 1024
MAX_TOTAL_BYTES = 64 * 1024 * 1024
MAX_IMAGE_PIXELS = 4_194_304


@dataclass
class RenderAssets:
    directory: str
    resolved: dict[str, str] = field(default_factory=dict)
    transparent: dict[str, str] = field(default_factory=dict)
    local_paths: set[str] = field(default_factory=set)


CURRENT_ASSETS: ContextVar[RenderAssets | None] = ContextVar("recipe_assets", default=None)


def image_uris(data: Any) -> set[str]:
    """Collect canonical image fields as relative paths.

    A recipe names images the way a listing tool returned them, relative to the
    use-case root. Nothing here accepts a bucket, a URL or a local path, so the
    payload cannot point the renderer at an object outside that root.
    """
    found: set[str] = set()
    if isinstance(data, dict):
        for key, value in data.items():
            if key.endswith(("image_path", "ImagePath")) and value:
                if not isinstance(value, str):
                    raise ValueError("Recipe images must be relative asset paths.")
                # Raises on anything that is not an ordinary relative path.
                resolve_relative(value)
                found.add(value)
            else:
                found.update(image_uris(value))
    elif isinstance(data, list):
        for item in data:
            found.update(image_uris(item))
    return found


def resolve(path: Any) -> str:
    assets = CURRENT_ASSETS.get()
    if assets is None or not isinstance(path, str):
        return ""
    return assets.resolved.get(path, path if path in assets.local_paths else "")


@contextmanager
def asset_context(
    data: dict[str, Any], project_id: str, directory: str, bucket: str
) -> Iterator[RenderAssets]:
    """Resolve every image against the use-case root before fetching any.

    Authorization is structural rather than a list check: each path is rebuilt
    from the fixed root, so a recipe can only reach objects inside it.
    """
    uris = image_uris(data)
    assets = RenderAssets(directory)
    token = CURRENT_ASSETS.set(assets)
    try:
        total = 0
        for uri in sorted(uris):
            object_name = resolve_relative(uri)
            content = download_bytes(
                project_id, f"gs://{bucket}/{object_name}", max_bytes=MAX_IMAGE_BYTES
            )
            total += len(content)
            if total > MAX_TOTAL_BYTES:
                raise ValueError("Recipe images exceed the 64 MiB render limit.")
            target = Path(directory) / f"{hashlib.sha256(uri.encode()).hexdigest()}.png"
            target.write_bytes(content)
            with Image.open(target) as source:
                if source.width * source.height > MAX_IMAGE_PIXELS:
                    raise ValueError("Recipe image exceeds the pixel limit.")
                source.verify()
            assets.resolved[uri] = str(target)
            assets.local_paths.add(str(target))
        yield assets
    finally:
        CURRENT_ASSETS.reset(token)
