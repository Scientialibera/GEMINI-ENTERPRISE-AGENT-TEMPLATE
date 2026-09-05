from __future__ import annotations

import argparse
import os

from vertexai import types

from bootstrap import ensure_dev_prerequisites
from common import (
    ROOT,
    build_app,
    build_client,
    deployment_config,
    get_agent_spec,
    load_environment,
    require_dev_environment,
    save_state,
    validate_agent_remote_environment,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create a developer-owned Agent Engine instance in dev."
    )
    parser.add_argument("--agent", required=True)
    args = parser.parse_args()

    os.chdir(ROOT)
    load_environment(".env.dev")
    project_id, location, staging_bucket = require_dev_environment()
    spec = get_agent_spec(args.agent)
    validate_agent_remote_environment(spec)
    ensure_dev_prerequisites(project_id, location, staging_bucket)

    client = build_client(project_id, location, staging_bucket)
    remote = client.agent_engines.create(
        agent=build_app(spec),
        config={
            "display_name": f"{spec.display_name} [dev]",
            **deployment_config(spec, staging_bucket),
            "identity_type": types.IdentityType.AGENT_IDENTITY,
        },
    )
    resource_name = remote.api_resource.name
    save_state(args.agent, resource_name)
    print(f"DEPLOYED_DEV_RESOURCE={resource_name}")


if __name__ == "__main__":
    main()
