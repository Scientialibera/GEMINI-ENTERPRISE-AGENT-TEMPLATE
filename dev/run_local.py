from __future__ import annotations

import argparse
import asyncio
import os

from common import ROOT, build_app, get_agent_spec, load_environment


async def _run(agent_name: str, message: str) -> None:
    spec = get_agent_spec(agent_name)
    app = build_app(spec)
    received = False
    async for event in app.async_stream_query(
        user_id="local-developer",
        message=message,
    ):
        received = True
        print(event)
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
    asyncio.run(_run(args.agent, args.message))


if __name__ == "__main__":
    main()
