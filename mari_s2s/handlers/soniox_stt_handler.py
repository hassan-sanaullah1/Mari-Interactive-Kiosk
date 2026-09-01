"""Soniox STT handler for huggingface/speech-to-speech (Urdu).

s2s ships Parakeet / Whisper / Paraformer STT — none cover Urdu well. This adds
Soniox's realtime websocket STT as a drop-in handler following s2s's contract:
subclass ``BaseHandler[STTIn, STTOut]``, implement ``setup()`` + ``process()``.

Contract (confirmed against the repo):
  input  : VADAudio     (.audio ndarray, .mode "progressive"|"final", .turn_id, ...)
  output : Transcription (.text, .language_code, .turn_id, .turn_revision, ...)

The websocket call itself is delegated to ``server.providers.stt.SonioxSTT`` — the
same adapter server/app.py uses — so the Soniox protocol logic lives in one place
instead of being duplicated per entrypoint. process() is a *sync* generator (s2s
runs each handler in its own thread), so the async call is driven with asyncio.run().
"""

from __future__ import annotations

import asyncio
from threading import Event
from typing import Iterator

import numpy as np

# s2s provides these. Kept as top-level imports so the class is a true drop-in;
# see docs/integration.md for how the pipeline builder selects it.
from speech_to_speech.baseHandler import BaseHandler
from speech_to_speech.pipeline.handler_types import STTIn, STTOut
from speech_to_speech.pipeline.messages import Transcription, VADAudio

from server.providers.stt import SonioxSTT

_TARGET_SR = 16000


def _to_int16_16k(audio: np.ndarray, src_sr: int = _TARGET_SR) -> bytes:
    arr = np.asarray(audio).reshape(-1)
    if arr.dtype != np.int16:
        # VAD may hand us float32 in [-1, 1].
        arr = np.clip(arr, -1.0, 1.0)
        arr = (arr * 32767).astype(np.int16)
    if src_sr != _TARGET_SR and arr.size:
        n = int(round(arr.size * _TARGET_SR / src_sr))
        xo = np.linspace(0.0, 1.0, arr.size, endpoint=False)
        xn = np.linspace(0.0, 1.0, n, endpoint=False)
        arr = np.interp(xn, xo, arr.astype(np.float32)).astype(np.int16)
    return arr.tobytes()


class SonioxSTTHandler(BaseHandler[STTIn, STTOut]):
    def setup(
        self,
        should_listen: Event,
        api_key: str = "",
        api_base: str = "wss://stt-rt.soniox.com/transcribe-websocket",
        model: str = "stt-rt-preview",
        language: str = "ur",
        **kwargs,
    ) -> None:
        if not api_key:
            raise ValueError("SonioxSTTHandler requires api_key (APP_SONIOX_API_KEY)")
        self.should_listen = should_listen
        self.language = language
        self._provider = SonioxSTT(api_key=api_key, url=api_base, model=model, lang=language)

    def process(self, vad_audio: VADAudio) -> Iterator[Transcription]:
        # Only transcribe a completed utterance; skip progressive/partial frames.
        if getattr(vad_audio, "mode", "final") == "progressive":
            return
        pcm = _to_int16_16k(vad_audio.audio)
        text = asyncio.run(self._provider.transcribe_pcm(pcm))
        if not text:
            return
        yield Transcription(
            text=text,
            language_code=self.language,
            turn_id=getattr(vad_audio, "turn_id", None),
            turn_revision=getattr(vad_audio, "turn_revision", None),
            speech_stopped_at_s=getattr(vad_audio, "created_at_s", None),
        )
