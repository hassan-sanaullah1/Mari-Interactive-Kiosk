"""The shared log format: every line carries the request ID, and health probes stay quiet.

Without the ID, the lines of two visitors' overlapping turns cannot be told apart. Without
the quiet flag, a container probe every 30 s buries real traffic in INFO lines, but a
probe's warnings and errors must still get through.
"""

from __future__ import annotations

import io
import logging

from server.logging_setup import LOG_FORMAT, _RequestIdFilter, is_quiet, request_id


def _logger_writing_to(stream: io.StringIO) -> logging.Logger:
    handler = logging.StreamHandler(stream)
    handler.addFilter(_RequestIdFilter())
    handler.setFormatter(logging.Formatter(LOG_FORMAT))
    logger = logging.getLogger("tests.logging_setup")
    logger.handlers = [handler]
    logger.propagate = False
    logger.setLevel(logging.INFO)
    return logger


def test_every_line_carries_the_request_id() -> None:
    stream = io.StringIO()
    logger = _logger_writing_to(stream)
    logger.info("outside a request")
    token = request_id.set("a1b2c3d4/t2")
    try:
        logger.info("inside a turn")
    finally:
        request_id.reset(token)
    first, second = stream.getvalue().splitlines()
    assert "[-] outside a request" in first
    assert "[a1b2c3d4/t2] inside a turn" in second


def test_quiet_requests_drop_info_but_keep_warnings() -> None:
    stream = io.StringIO()
    logger = _logger_writing_to(stream)
    token = is_quiet.set(True)
    try:
        logger.info("probe noise")
        logger.warning("probe found a problem")
    finally:
        is_quiet.reset(token)
    output = stream.getvalue()
    assert "probe noise" not in output
    assert "probe found a problem" in output
