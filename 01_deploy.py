from __future__ import annotations

import asyncio
import json
from pathlib import Path

import vertexai
from vertexai import types
from vertexai.agent_engines import AdkApp

from agent import root_agent
from deployment_support import EXTRA_PACKAGES
from deployment_support import LOCATION
from deployment_support import PROJECT_ID
from deployment_support import REQUIREMENTS
from deployment_support import RUNTIME_ENV_VARS
from deployment_support import STAGING_BUCKET


DISPLAY_NAME = "Template Pro-Code Agent"


# AdkApp reads the legacy Vertex AI global configuration while it is being
# constructed, so initialize it before creating the application.
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
app = AdkApp(agent=root_agent, enable_tracing=True)


async def test_locally() -> None:
    received_event = False
    async for event in app.async_stream_query(
        user_id="deployment-validator",
        message="Confirm that the local ADK validation works.",
    ):
        received_event = True
        print(event)
    if not received_event:
        raise RuntimeError("The local ADK test returned no events.")


def deploy() -> str:
    remote_agent = client.agent_engines.create(
        agent=app,
        config={
            "display_name": DISPLAY_NAME,
            "requirements": REQUIREMENTS,
            "extra_packages": EXTRA_PACKAGES,
            "staging_bucket": STAGING_BUCKET,
            "env_vars": RUNTIME_ENV_VARS,
            "identity_type": types.IdentityType.AGENT_IDENTITY,
        },
    )
    resource_name = remote_agent.api_resource.name
    Path("deployment_result.json").write_text(
        json.dumps(
            {
                "project_id": PROJECT_ID,
                "location": LOCATION,
                "display_name": DISPLAY_NAME,
                "reasoning_engine": resource_name,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"DEPLOYED_RESOURCE={resource_name}")
    return resource_name


if __name__ == "__main__":
    asyncio.run(test_locally())
    deploy()
