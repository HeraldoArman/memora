"""Detailed logging setup for the Memora backend.

One function — setup_logging() — configures the root logger with a verbose
line format so a prototype bug can be traced without guessing:

    %(asctime)s %(levelname)-7s [%(name)s] %(module)s:%(lineno)d %(funcName)s()
        %(process)d %(threadName)s — %(message)s

- timestamps include milliseconds + UTC (glasses run on a headless box; local
  time is meaningless across devices)
- logger name = module path (e.g. `reasoning.agent.agent`) so a log
  line immediately tells you which subsystem emitted it
- function + line = jump straight to the call site
- process/thread distinguishes the FastAPI uvicorn process from the
  livekit-agent worker when both write to the same sink

Wire this at every entry point (FastAPI lifespan, worker main). Without it the
stdlib default formatter hides all of the above.

ponytail: stdlib `logging` only — no structlog dependency for a prototype.
"""

from __future__ import annotations

import logging
import logging.handlers
import sys
from pathlib import Path

from env import get_settings

# Shared verbose format. `-7s` keeps columns aligned for INFO/WARNING/ERROR.
_VERBOSE_FORMAT = (
    "%(asctime)s %(levelname)-7s [%(name)s] %(module)s:%(lineno)d %(funcName)s() "
    "pid=%(process)d %(threadName)s — %(message)s"
)
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# LiveKit + Google SDKs are chatty at DEBUG; keep them at WARNING unless someone
# explicitly enables debug logging. Our own loggers inherit root level.
_NOISY = {"livekit", "google", "httpcore", "httpx", "neo4j", "faiss"}


def _formatter() -> logging.Formatter:
    fmt = logging.Formatter(_VERBOSE_FORMAT, datefmt=_DATE_FORMAT)
    fmt.converter = __import__("time").gmtime  # UTC timestamps
    return fmt


def setup_logging(*, level: str | None = None, log_file: str | None = None) -> None:
    """Configure root logging once. Idempotent across uvicorn reload.

    level: default from Settings.log_level. log_file: optional rotating file
    (e.g. logs/backend.log); stderr is always the primary sink. Relative
    paths resolve against the workspace root (parent of apps/).
    """
    settings = get_settings()
    level = (level or settings.log_level).upper()

    root = logging.getLogger()
    # uvicorn reload re-runs this; drop old handlers so lines don't duplicate.
    root.handlers.clear()
    root.setLevel(level)

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(_formatter())
    root.addHandler(handler)

    if log_file:
        # apps/backend/config/logging.py → 3 parents up = workspace root
        root_dir = Path(__file__).resolve().parents[3]
        path = root_dir / log_file if not Path(log_file).is_absolute() else Path(log_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        fh = logging.handlers.RotatingFileHandler(
            path, maxBytes=10 * 1024 * 1024, backupCount=3, encoding="utf-8"
        )
        fh.setFormatter(_formatter())
        root.addHandler(fh)

    # Cap chatty third-party SDKs so our logs stay readable at INFO.
    for name in _NOISY:
        logging.getLogger(name).setLevel(logging.WARNING)
    # Our own package loggers follow root.
    logging.getLogger("api").setLevel(level)
    logging.getLogger("config").setLevel(level)
    logging.getLogger("context").setLevel(level)
    logging.getLogger("extraction").setLevel(level)
    logging.getLogger("gateway").setLevel(level)
    logging.getLogger("memory").setLevel(level)
    logging.getLogger("perception").setLevel(level)
    logging.getLogger("pipeline").setLevel(level)
    logging.getLogger("reasoning").setLevel(level)
    logging.getLogger("tools").setLevel(level)
    logging.getLogger("workers").setLevel(level)

    root.info("logging configured (level=%s%s)", level, f", file={log_file}" if log_file else "")
