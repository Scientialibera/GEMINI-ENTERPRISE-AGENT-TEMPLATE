from __future__ import annotations

import argparse
import os

from bootstrap import ensure_dev_prerequisites
from common import (
    ROOT,
    build_app,
    build_client,
    deployment_config,
    get_agent_spec,
    load_environment,
    load_resource_name,
    require_dev_environment,
    staged_extra_packages,
    validate_agent_remote_environment,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Update an existing developer-owned Agent Engine instance in dev."
    )
    parser.add_argument("--agent", required=True)
    args = parser.parse_args()

    os.chdir(ROOT)
    load_environment(".env.dev")
    project_id, location, staging_bucket = require_dev_environment()
    spec = get_agent_spec(args.agent)
    validate_agent_remote_environment(spec)
    ensure_dev_prerequisites(project_id, location, staging_bucket)
    resource_name = load_resource_name(args.agent)

    client = build_client(project_id, location, staging_bucket)
    app = build_app(spec)
    with staged_extra_packages(spec) as extra_packages:
        updated = client.agent_engines.update(
            name=resource_name,
            agent=app,
            config=deployment_config(spec, staging_bucket, extra_packages),
        )
    print(f"UPDATED_DEV_RESOURCE={updated.api_resource.name}")


if __name__ == "__main__":
    main()
