"""Export each runtime's exact third-party dependencies from the workspace lock."""

from __future__ import annotations

import shutil
import subprocess

from paths import ROOT
from registry import AgentSpec


def export_requirements(spec: AgentSpec) -> tuple[str, ...]:
    executable = shutil.which("uv")
    if executable is None:
        raise SystemExit("uv is required to export locked deployment dependencies.")
    result = subprocess.run(
        [
            executable,
            "export",
            "--locked",
            "--offline",
            "--package",
            spec.package_name,
            "--no-dev",
            "--no-emit-workspace",
            "--no-hashes",
            "--no-header",
            "--no-annotate",
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode:
        raise SystemExit(
            f"Cannot export dependencies for {spec.package_name}: {result.stderr.strip()} "
            "Run uv sync --all-packages --group dev and commit the updated uv.lock."
        )
    requirements = tuple(line.strip() for line in result.stdout.splitlines() if line.strip())
    if not requirements:
        raise SystemExit(f"No locked dependencies were exported for {spec.package_name}.")
    return requirements
