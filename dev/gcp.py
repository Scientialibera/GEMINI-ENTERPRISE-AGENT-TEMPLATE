"""Small Google Cloud CLI operations shared by developer commands."""

from __future__ import annotations

import functools
import shutil
import subprocess
from collections.abc import Sequence


def run_gcloud(args: Sequence[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    executable = shutil.which("gcloud")
    if executable is None:
        raise SystemExit("Google Cloud CLI is required and must be available on PATH.")
    result = subprocess.run([executable, *args], check=False, capture_output=True, text=True)
    if check and result.returncode:
        raise SystemExit(f"gcloud failed: {(result.stderr or result.stdout).strip()}")
    return result


@functools.cache
def project_number(project_id: str) -> str:
    """Normalize project IDs and numeric project names to the same state scope."""
    if project_id.isdigit():
        return project_id
    number = run_gcloud(
        ("projects", "describe", project_id, "--format=value(projectNumber)")
    ).stdout.strip()
    if not number.isdigit():
        raise SystemExit(f"Could not resolve the numeric project number for '{project_id}'.")
    return number
