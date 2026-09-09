"""Package, deploy or update, then register a development agent."""

from __future__ import annotations

import argparse
import os

from config.bootstrap import ensure_dev_prerequisites
from config.settings import load_environment, require_dev_environment
from deploy.package_agent import package_agent
from deploy.state import find_resource_name, runtime_override
from paths import ROOT
from register.register_agent import APP_ENGINE_ID_ENV, register_agent
from registry import get_agent_spec

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
    spec = get_agent_spec(args.agent)
    project_id, location, staging_bucket = require_dev_environment(spec=spec)

    existing_resource = runtime_override(project_id, location)

    print("STEP=preflight")
    ensure_dev_prerequisites(project_id, location, staging_bucket, spec)

    # Preflight may create an explicitly requested new sandbox project. Resolve
    # its numeric state scope only after that project exists.
    existing_resource = existing_resource or find_resource_name(args.agent, project_id, location)

    print("STEP=package")
    archive = package_agent(args.agent, ARTIFACTS_DIR / f"{spec.package_name}.tar.gz")
    print(f"AGENT_ARCHIVE={archive}")

    already_deployed = existing_resource is not None
    print("STEP=update" if already_deployed else "STEP=deploy")
    if already_deployed:
        from deploy.update_dev import update_agent

        resource_name = update_agent(args.agent, project_id, location, staging_bucket, spec)
    else:
        from deploy.deploy_dev import deploy_agent

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
    register_agent(args.agent, app_id, project_id, spec, resource_name)


if __name__ == "__main__":
    main()
