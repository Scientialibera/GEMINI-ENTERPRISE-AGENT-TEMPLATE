"""Validate runtime_config.json and publish it as a Parameter Manager version.

runtime_config.json is gitignored (it holds this project's real bucket name).
Copy runtime_config.example.json to runtime_config.json and edit it before
running this script.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess

import config

from runtime_config import RuntimeConfig


def find_gcloud() -> str:
    discovered = shutil.which("gcloud")
    if discovered:
        return discovered
    local_app_data = os.getenv("LOCALAPPDATA")
    if local_app_data:
        candidate = Path(local_app_data) / "Google/Cloud SDK/google-cloud-sdk/bin/gcloud.cmd"
        if candidate.exists():
            return str(candidate)
    return "gcloud"


GCLOUD = find_gcloud()
PAYLOAD_PATH = Path(__file__).with_name("runtime_config.json")


def run_gcloud(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        [GCLOUD, *args],
        check=False,
        text=True,
        capture_output=True,
    )
    if completed.stdout.strip():
        print(completed.stdout.strip())
    if completed.stderr.strip():
        print(completed.stderr.strip())
    if check and completed.returncode:
        raise subprocess.CalledProcessError(completed.returncode, [GCLOUD, *args])
    return completed


def main() -> None:
    payload = json.loads(PAYLOAD_PATH.read_text(encoding="utf-8"))
    validated = RuntimeConfig.model_validate(payload)

    describe = run_gcloud(
        "parametermanager",
        "parameters",
        "describe",
        config.RUNTIME_CONFIG_PARAMETER_ID,
        f"--project={config.PROJECT_ID}",
        f"--location={config.LOCATION}",
        check=False,
    )
    if describe.returncode:
        combined_output = f"{describe.stdout}\n{describe.stderr}"
        if "NOT_FOUND" not in combined_output:
            raise subprocess.CalledProcessError(
                describe.returncode,
                [GCLOUD, "parametermanager", "parameters", "describe"],
            )
        run_gcloud(
            "parametermanager",
            "parameters",
            "create",
            config.RUNTIME_CONFIG_PARAMETER_ID,
            f"--project={config.PROJECT_ID}",
            f"--location={config.LOCATION}",
            "--parameter-format=JSON",
            "--quiet",
        )

    run_gcloud(
        "parametermanager",
        "parameters",
        "versions",
        "create",
        validated.config_revision,
        f"--parameter={config.RUNTIME_CONFIG_PARAMETER_ID}",
        f"--project={config.PROJECT_ID}",
        f"--location={config.LOCATION}",
        f"--payload-data-from-file={PAYLOAD_PATH}",
        "--quiet",
    )


if __name__ == "__main__":
    main()
