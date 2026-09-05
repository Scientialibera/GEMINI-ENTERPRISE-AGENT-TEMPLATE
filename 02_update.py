from __future__ import annotations

import vertexai
from vertexai.agent_engines import AdkApp

from agent import root_agent
from deployment_support import EXTRA_PACKAGES
from deployment_support import LOCATION
from deployment_support import PROJECT_ID
from deployment_support import REASONING_ENGINE
from deployment_support import REQUIREMENTS
from deployment_support import RUNTIME_ENV_VARS
from deployment_support import STAGING_BUCKET




vertexai.init(
    project=PROJECT_ID,
    location=LOCATION,
    staging_bucket=STAGING_BUCKET,
)
client = vertexai.Client(
    project=PROJECT_ID,
    location=LOCATION,
    http_options={"api_version": "v1beta1"},
)


def main() -> None:
    app = AdkApp(agent=root_agent, enable_tracing=True)
    updated = client.agent_engines.update(
        name=REASONING_ENGINE,
        agent=app,
        config={
            "requirements": REQUIREMENTS,
            "extra_packages": EXTRA_PACKAGES,
            "staging_bucket": STAGING_BUCKET,
            "env_vars": RUNTIME_ENV_VARS,
        },
    )
    print(f"UPDATED_RESOURCE={updated.api_resource.name}")


if __name__ == "__main__":
    main()
