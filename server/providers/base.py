"""Provider interfaces (ports) for STT and TTS.

Callers (server/app.py, server/agent/, mari_s2s/handlers/) depend only on these, so
swapping a provider means building a different adapter, not editing dispatch code.
"""

from __future__ import annotations

from typing import Protocol


class STTProvider(Protocol):
    """Speech-to-text: raw 16 kHz mono PCM in, transcript text out."""

    async def transcribe_pcm(self, pcm: bytes) -> str: ...


class TTSProvider(Protocol):
    """Text-to-speech: text in, (audio_bytes, mime_type) out."""

    # True when the voice needs server/normalization.py applied to its input first.
    wants_spoken_form: bool
    # Which spoken form it needs: one of server.normalization.ENGINES.
    engine: str

    async def synthesize(self, text: str) -> tuple[bytes, str]: ...
