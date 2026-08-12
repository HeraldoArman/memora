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
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from dotenv import load_dotenv
from env import get_settings
from livekit.agents import AgentServer, cli

from config.logging import setup_logging
from gateway.livekit.entrypoint import entrypoint

log = logging.getLogger(__name__)

_settings = get_settings()
log.info("worker registering agent_name=%s", _settings.agent_name)

server = AgentServer()
server.rtc_session(entrypoint, agent_name=_settings.agent_name)


class _HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/health":
            self.send_response(200)
            self.send_header("content-type", "text/plain")
            self.send_header("access-control-allow-origin", "*")
            self.end_headers()
            self.wfile.write(b"ok")
        else:
            self.send_response(404)
            self.send_header("access-control-allow-origin", "*")
            self.end_headers()

    def log_message(self, *a):
        pass


def _start_health_server(port: int) -> None:
    srv = HTTPServer(("127.0.0.1", port), _HealthHandler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    log.info("worker health check on http://127.0.0.1:%d/health", port)


def main() -> None:
    """Run the livekit-agent worker. CLI args: dev | start."""
    setup_logging(log_file="logs/worker.log")
    load_dotenv()
    settings = get_settings()
    _start_health_server(settings.worker_health_port)
    log.info("starting livekit agent worker")
    cli.run_app(server)


if __name__ == "__main__":  # pragma: no cover
    main()
