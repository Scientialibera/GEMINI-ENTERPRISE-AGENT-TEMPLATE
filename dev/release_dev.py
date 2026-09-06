"""Take one agent from source to a usable Gemini Enterprise agent.

    preflight -> package -> deploy (or update) -> register

Each step is idempotent, so re-running is the normal way to ship a change.
Shared infrastructure remains Terraform's responsibility.
"""

from __future__ import annotations

import argparse
import os

from bootstrap import ensure_dev_prerequisites
from common import (
    ROOT,
    get_agent_spec,
    load_environment,
    load_resource_name,
    require_dev_environment,
    state_path,
)
from package_agent import package_agent
from register_agent import APP_ENGINE_ID_ENV, register_agent

ARTIFACTS_DIR = ROOT / "artifacts"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Package, deploy and register one agent in a dev sandbox.",
    )
    parser.add_argument("--agent", required=True)
    parser.add_argument(
        "--skip-register",
        action="store_true",
        help="Stop after deployment instead of publishing into a Gemini Enterprise app.",
    )
    args = parser.parse_args()

    os.chdir(ROOT)
    load_environment(".env.dev")
    project_id, location, staging_bucket = require_dev_environment()
    spec = get_agent_spec(args.agent)

    print("STEP=preflight")
    ensure_dev_prerequisites(project_id, location, staging_bucket, spec)

    print("STEP=package")
    archive = package_agent(args.agent, ARTIFACTS_DIR / f"{spec.package_name}.tar.gz")
    print(f"AGENT_ARCHIVE={archive}")

    already_deployed = state_path(args.agent).exists()
    print("STEP=update" if already_deployed else "STEP=deploy")
    if already_deployed:
        from update_dev import update_agent

        resource_name = update_agent(args.agent, project_id, location, staging_bucket, spec)
    else:
        from deploy_dev import deploy_agent

        resource_name = deploy_agent(args.agent, project_id, location, staging_bucket, spec)
    print(f"REASONING_ENGINE={resource_name}")

    if args.skip_register:
        print("STEP=register skipped")
        return

    app_id = os.getenv(APP_ENGINE_ID_ENV, "").strip()
    if not app_id:
        print(
            f"STEP=register skipped: {APP_ENGINE_ID_ENV} is not set. The agent is deployed but "
            "will not appear in a Gemini Enterprise app until it is registered."
        )
        return

    print("STEP=register")
    register_agent(args.agent, app_id, project_id, spec, load_resource_name(args.agent))


if __name__ == "__main__":
    main()
