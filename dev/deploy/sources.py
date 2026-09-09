"""One validated source manifest for archive creation and SDK deployment staging."""

from __future__ import annotations

import os
import shutil
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from paths import ROOT
from registry import AgentSpec


@dataclass(frozen=True, slots=True)
class SourceEntry:
    path: Path
    archive_name: str


def _walk(path: Path, archive_name: str) -> Iterator[SourceEntry]:
    if path.is_symlink():
        raise ValueError(f"Package sources must not contain symbolic links: {path}")
    if path.name == "__pycache__" or path.suffix in {".pyc", ".pyo"}:
        return
    if not path.is_dir() and not path.is_file():
        raise ValueError(f"Package sources must be regular files or directories: {path}")
    yield SourceEntry(path, archive_name)
    if path.is_dir():
        for child in sorted(path.iterdir()):
            yield from _walk(child, f"{archive_name}/{child.name}")


def source_entries(spec: AgentSpec) -> tuple[SourceEntry, ...]:
    """Validate the entire tree before any output is written or uploaded."""
    entries = []
    roots = set()
    for relative in spec.extra_packages:
        path = ROOT / relative
        if Path(relative).is_absolute() or ".." in Path(relative).parts:
            raise ValueError("Package sources must be paths within the repository.")
        for ancestor in (path, *path.parents):
            if ancestor == ROOT:
                break
            if ancestor.is_symlink():
                raise ValueError(f"Package sources must not contain symbolic links: {ancestor}")
        if not path.is_dir():
            raise FileNotFoundError(path)
        if path.name in roots:
            raise ValueError(f"Duplicate package archive root: {path.name}")
        roots.add(path.name)
        entries.extend(_walk(path, path.name))
    return tuple(entries)


@contextmanager
def staged_extra_packages(spec: AgentSpec) -> Iterator[list[str]]:
    entries = source_entries(spec)
    with tempfile.TemporaryDirectory(prefix="agent-deploy-") as temp_dir:
        staged_root = Path(temp_dir)
        roots = []
        for entry in entries:
            destination = staged_root / entry.archive_name
            if "/" not in entry.archive_name:
                roots.append(entry.archive_name)
            if entry.path.is_dir():
                destination.mkdir(parents=True, exist_ok=True)
            else:
                shutil.copyfile(entry.path, destination)
        previous_cwd = Path.cwd()
        os.chdir(staged_root)
        try:
            yield roots
        finally:
            os.chdir(previous_cwd)
