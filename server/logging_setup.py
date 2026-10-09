"""One logging setup for the whole backend, with a request ID on every line.

The ID lives in a ContextVar, so it follows an HTTP request or a WebSocket turn through
every ``await`` (and into tasks started from it) without being passed around. Lines
logged outside any request, such as startup, carry ``-``.
"""

from __future__ import annotations

import logging
import secrets
from contextvars import ContextVar

request_id: ContextVar[str] = ContextVar("request_id", default="-")
# Set for container health probes, which arrive every 30 s: their INFO lines (including
# the Qdrant calls they make) would bury real traffic. Warnings and errors still show.
is_quiet: ContextVar[bool] = ContextVar("is_quiet", default=False)

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s [%(request_id)s] %(message)s"


def new_request_id() -> str:
    return secrets.token_hex(4)


class _RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if is_quiet.get() and record.levelno < logging.WARNING:
            return False
        record.request_id = request_id.get()
        return True


def configure_logging(level: int = logging.INFO) -> None:
    """Send every logger's records to stderr with the request ID. Safe to call twice."""
    root = logging.getLogger()
    if any(isinstance(f, _RequestIdFilter) for h in root.handlers for f in h.filters):
        return
    handler = logging.StreamHandler()
    handler.addFilter(_RequestIdFilter())
    handler.setFormatter(logging.Formatter(LOG_FORMAT))
    root.addHandler(handler)
    root.setLevel(level)
