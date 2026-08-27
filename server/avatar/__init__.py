"""Avatar support: NVIDIA Audio2Face-3D lipsync for the Three.js/GLB presenter.

Public surface used by server/app.py:

  get_a2f_client()      the shared A2FClient, or None when A2F isn't configured
  LipsyncTurn           per-reply fan-out of TTS sentences into A2F clips
  a2f_status()          config snapshot for /healthz (no secrets)

Everything here is optional: with ``APP_A2F_URL`` unset — or the ``nvidia-ace``
wheel absent — ``get_a2f_client()`` returns None and the speech pipeline runs
exactly as it did before, minus lipsync frames.
"""

from __future__ import annotations

import logging

from .. import config as C
from .a2f_client import AVAILABLE, IMPORT_ERROR, A2FClient, A2FStreamSession
from .lipsync import LipsyncTurn, decode_to_pcm16_16k

logger = logging.getLogger(__name__)

__all__ = [
    "A2FClient",
    "A2FStreamSession",
    "LipsyncTurn",
    "decode_to_pcm16_16k",
    "get_a2f_client",
    "a2f_status",
    "warm",
]

_client: A2FClient | None = None
_resolved = False


def get_a2f_client() -> A2FClient | None:
    """The process-wide A2F client (one shared gRPC channel), or None."""
    global _client, _resolved
    if not _resolved:
        _resolved = True
        if not C.A2F_URL:
            logger.info("A2F lipsync disabled (APP_A2F_URL not set)")
        elif not AVAILABLE:
            logger.warning(
                "APP_A2F_URL set but the A2F client is unavailable (%s) — "
                "install with: pip install grpcio nvidia-ace",
                IMPORT_ERROR,
            )
        else:
            _client = A2FClient(
                target=C.A2F_URL, api_key=C.A2F_API_KEY, tls_ca_file=C.A2F_TLS_CA
            )
            logger.info("A2F lipsync enabled (url=%s)", C.A2F_URL)
    return _client


async def warm() -> None:
    """Dial the A2F channel at startup so the first reply doesn't pay for it."""
    client = get_a2f_client()
    if client is not None:
        await client.warmup()


def a2f_status() -> dict:
    return {
        "configured": bool(C.A2F_URL),
        "client": AVAILABLE,
        "ready": bool(C.A2F_URL) and AVAILABLE,
        "url": C.A2F_URL or None,
    }
