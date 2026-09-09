from __future__ import annotations

import sys
from pathlib import Path

# Runnable directly as well as imported by release_dev.py, so dev/ has to be
# on sys.path either way: running this file puts only its own folder there.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import argparse
import os

from config.bootstrap import ensure_dev_prerequisites
from config.settings import (
    load_environment,
    require_dev_environment,
    validate_agent_remote_environment,
)
from iam.apply_agent_identity_iam import apply_agent_identity_iam
from paths import ROOT
from registry import AgentSpec, get_agent_spec

from deploy.runtime import build_app, build_client, deployment_config
from deploy.sources import staged_extra_packages
from deploy.state import load_resource_name, save_state


def update_agent(
    agent_name: str,
    project_id: str,
    location: str,
    staging_bucket: str,
    spec: AgentSpec,
) -> str:
    """Update the Agent Engine this developer already owns."""
    validate_agent_remote_environment(spec)
    resource_name = load_resource_name(agent_name, project_id, location)

    client = build_client(project_id, location, staging_bucket)
    app = build_app(spec)
    with staged_extra_packages(spec) as extra_packages:
        updated = client.agent_engines.update(
            name=resource_name,
            agent=app,
            config=deployment_config(spec, staging_bucket, extra_packages),
        )
    resource_name = updated.api_resource.name
    save_state(agent_name, resource_name, project_id, location)
    apply_agent_identity_iam(agent_name, project_id, resource_name, spec)
    return resource_name


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Update an existing developer-owned Agent Engine instance in dev."
    )
    parser.add_argument("--agent", required=True)
    args = parser.parse_args()

    os.chdir(ROOT)
    load_environment(".env.dev")
    spec = get_agent_spec(args.agent)
    project_id, location, staging_bucket = require_dev_environment(spec=spec)
    load_resource_name(args.agent, project_id, location)
    ensure_dev_prerequisites(project_id, location, staging_bucket, spec)

    resource_name = update_agent(args.agent, project_id, location, staging_bucket, spec)
    print(f"UPDATED_DEV_RESOURCE={resource_name}")


if __name__ == "__main__":
    main()
