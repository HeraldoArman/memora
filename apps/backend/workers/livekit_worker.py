"""LiveKit agent worker — standalone process entry point.

    uv run python -m workers.livekit_worker dev
    uv run python -m workers.livekit_worker start

`dev` runs locally with the dev supervisor (auto-reconnect, prints a room URL you can join
with a webcam/mic client). `start` is the production worker. We use agents.cli.run_app,
which reads LIVEKIT_URL / LIVEKIT_API_KEY / LIVEKIT_API_SECRET from env (already validated
by Settings) and dispatches jobs to our entrypoint.

Ponytail: a thin main() that delegates to cli.run_app. The worker + FastAPI are two
processes (plan: Railway two-service or single-service-dual-cmd deploy).
"""

from __future__ import annotations

import logging

from livekit.agents import cli

from config.logging import setup_logging
from gateway.livekit.entrypoint import build_worker_options

log = logging.getLogger(__name__)


def main() -> None:
    """Run the livekit-agent worker. CLI args: dev | start."""
    setup_logging()
    log.info("starting livekit agent worker")
    cli.run_app(build_worker_options())


if __name__ == "__main__":  # pragma: no cover
    main()
