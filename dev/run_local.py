from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys

from config.settings import load_environment
from deploy.runtime import build_app
from paths import ROOT
from registry import get_agent_spec


async def _run(agent_name: str, message: str) -> None:
    spec = get_agent_spec(agent_name)
    app = build_app(spec)
    received = False
    async for event in app.async_stream_query(
        user_id="local-developer",
        message=message,
    ):
        received = True
        for part in event.get("content", {}).get("parts", []):
            if part.get("text") and not part.get("thought"):
                print(part["text"])
    if not received:
        raise RuntimeError("The local ADK run returned no events.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run one workspace agent locally.")
    parser.add_argument("--agent", required=True)
    parser.add_argument(
        "--message",
        default="Confirm that the local ADK agent is running.",
    )
    args = parser.parse_args()

    os.chdir(ROOT)
    load_environment(".env.local")
    # Without a handler the shared plugins log into a void, so tool_call_logging
    # shows nothing locally. The runtime configures its own; a local run does not.
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        stream=sys.stdout,
        format="%(levelname)s %(name)s %(message)s",
    )
    asyncio.run(_run(args.agent, args.message))


if __name__ == "__main__":
    main()
