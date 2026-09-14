"""Uplift TTS handler for huggingface/speech-to-speech (Urdu).

s2s ships Qwen3-TTS / Kokoro / MMS / ChatTTS — none are Urdu-native. This adds
UpliftAI's cloud TTS as a drop-in handler.

Contract (confirmed against the repo, mirrors TTS/facebookmms_handler.py):
  input  : TTSInput (.text, .language_code)   [or EndOfResponse — ignored]
  output : np.ndarray int16 chunks @ 16 kHz    (TTSOut allows bytes | np.ndarray | AudioOutput)

Uplift returns mp3 for the whole segment; we decode to PCM (PyAV), resample to
16 kHz mono, and yield fixed-size chunks so downstream streaming/interruption
works like the built-in handlers. Spoken-form normalization and the REST call are the
same ones server/app.py uses (server/normalization.py, server.providers.tts.UpliftTTS).
"""

from __future__ import annotations

import asyncio
import io
from threading import Event
from typing import Iterator

import numpy as np

from speech_to_speech.baseHandler import BaseHandler
from speech_to_speech.pipeline.handler_types import TTSIn, TTSOut
from speech_to_speech.pipeline.messages import EndOfResponse, TTSInput

from server.normalization import normalize_for_tts
from server.providers.tts import UpliftTTS

_TARGET_SR = 16000


def _decode_mp3_to_int16_16k(data: bytes) -> np.ndarray:
    import av

    container = av.open(io.BytesIO(data))
    resampler = av.audio.resampler.AudioResampler(format="s16", layout="mono", rate=_TARGET_SR)
    chunks: list[np.ndarray] = []
    for frame in container.decode(audio=0):
        for r in resampler.resample(frame):
            chunks.append(r.to_ndarray().reshape(-1))
    container.close()
    return np.concatenate(chunks).astype(np.int16) if chunks else np.zeros(0, dtype=np.int16)


class UpliftTTSHandler(BaseHandler[TTSIn, TTSOut]):
    def setup(
        self,
        should_listen: Event,
        api_key: str = "",
        api_base: str = "https://ap-southeast-1.api.upliftai.org",
        api_path: str = "/v1/synthesis/text-to-speech",
        voice_id: str = "v_8eelc901v6",
        output_format: str = "MP3_22050_128",
        speed: float = 1.0,
        blocksize: int = 512,
        **kwargs,
    ) -> None:
        if not api_key:
            raise ValueError("UpliftTTSHandler requires api_key (APP_UPLIFT_API_KEY)")
        self.should_listen = should_listen
        self.blocksize = blocksize
        self._provider = UpliftTTS(
            api_key=api_key,
            base=api_base,
            path=api_path,
            voice=voice_id,
            output_format=output_format,
            speed=speed,
        )

    def process(self, tts_input: TTSIn) -> Iterator[np.ndarray]:
        if isinstance(tts_input, EndOfResponse) or not isinstance(tts_input, TTSInput):
            return
        text = (tts_input.text or "").strip()
        if not text:
            return

        spoken = normalize_for_tts(text, self._provider.lang)
        mp3, _mime = asyncio.run(self._provider.synthesize(spoken))
        pcm = _decode_mp3_to_int16_16k(mp3)

        # Yield fixed-size chunks; pad the final one (matches facebookmms_handler).
        for i in range(0, len(pcm), self.blocksize):
            chunk = pcm[i : i + self.blocksize]
            if len(chunk) < self.blocksize:
                chunk = np.pad(chunk, (0, self.blocksize - len(chunk)))
            yield chunk
            if self.should_listen.is_set():  # user interrupted — stop speaking
                break
