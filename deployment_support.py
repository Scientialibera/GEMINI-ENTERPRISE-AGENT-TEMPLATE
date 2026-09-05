"""Shared local deployment settings.

This module is used by 01_deploy.py and 02_update.py on the developer workstation.
It is intentionally not included in the Agent Engine source bundle.
"""

from __future__ import annotations

from pathlib import Path

import config


PROJECT_ID = config.PROJECT_ID
LOCATION = config.LOCATION
STAGING_BUCKET = f"gs://{config.AGENT_IDENTITY_BUCKET_NAME}"
REASONING_ENGINE = (
    f"projects/{config.PROJECT_NUMBER}/locations/{config.LOCATION}/"
    f"reasoningEngines/{config.REASONING_ENGINE_ID}"
)
REQUIREMENTS = [
    line.strip()
    for line in Path(__file__).with_name("requirements.txt").read_text().splitlines()
    if line.strip() and not line.lstrip().startswith("#")
]
EXTRA_PACKAGES = ["agent.py", "bootstrap.py", "runtime_config.py"]
RUNTIME_ENV_VARS = {
    "AGENT_PROJECT_ID": config.PROJECT_ID,
    "AGENT_LOCATION": config.LOCATION,
    "AGENT_CONFIG_PARAMETER": config.RUNTIME_CONFIG_PARAMETER_ID,
    "AGENT_CONFIG_VERSION": config.RUNTIME_CONFIG_PARAMETER_VERSION,
    "AGENT_CONFIG_CACHE_SECONDS": str(config.RUNTIME_CONFIG_CACHE_SECONDS),
    "AGENT_GEMINI_AUTHORIZATION": config.GEMINI_ENTERPRISE_AUTHORIZATION_ID,
}
