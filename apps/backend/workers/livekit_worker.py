"""LiveKit agent worker — standalone process entry point.

    uv run python -m workers.livekit_worker dev
    uv run python -m workers.livekit_worker start

`dev` runs locally with the dev supervisor (auto-reconnect, prints a room URL you can join
with a webcam/mic client). `start` is the production worker. We use the AgentServer API
(livekit-agents >= 1.6): cli.run_app(server) reads LIVEKIT_URL / LIVEKIT_API_KEY /
LIVEKIT_API_SECRET from env and dispatches jobs to our rtc_session-decorated entrypoint.

Ponytail: a thin main() that delegates to cli.run_app. The worker + FastAPI are two
processes (plan: Railway two-service or single-service-dual-cmd deploy).
"""

from __future__ import annotations

import logging

from dotenv import load_dotenv
from livekit.agents import AgentServer, cli

from config.logging import setup_logging
from gateway.livekit.entrypoint import entrypoint

log = logging.getLogger(__name__)

# AgentServer is the livekit-agents >= 1.6 entrypoint surface. rtc_session registers
# our per-room handler; agent_name must match a LiveKit Cloud dispatch rule (dev mode
# auto-dispatches any room when no explicit rule filters it out).
server = AgentServer()
server.rtc_session(entrypoint, agent_name="memora-agent")


def main() -> None:
    """Run the livekit-agent worker. CLI args: dev | start."""
    setup_logging()
    # pydantic-settings reads .env for get_settings(), but the livekit-agent CLI reads
    # LIVEKIT_URL/API_KEY/SECRET straight from os.environ — export .env first.
    load_dotenv()
    log.info("starting livekit agent worker")
    cli.run_app(server)


if __name__ == "__main__":  # pragma: no cover
    main()
