from __future__ import annotations

import os

from bootstrap import ensure_runtime_parameter, prepare_dev_platform
from common import ROOT, load_environment, require_dev_environment


def main() -> None:
    os.chdir(ROOT)
    load_environment(".env.dev")
    project_id, location, staging_bucket = require_dev_environment(
        require_parameter=False
    )
    prepare_dev_platform(project_id, location, staging_bucket)

    parameter = os.getenv("CONFIG_PARAMETER", "").strip()
    if parameter and "REPLACE" not in parameter and not parameter.startswith("<"):
        ensure_runtime_parameter(project_id)
        print("DEV_PREREQUISITES=ready")
    else:
        print("DEV_PLATFORM_PREREQUISITES=ready")
        print(
            "NEXT_STEP=Apply the Terraform dev stack, then set CONFIG_PARAMETER "
            "to its runtime_config_parameter output."
        )


if __name__ == "__main__":
    main()
