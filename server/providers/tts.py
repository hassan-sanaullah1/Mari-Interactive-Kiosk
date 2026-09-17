"""TTS adapters, each implementing :class:`server.providers.base.TTSProvider`.

  UpliftTTS        Urdu, and English while APP_EN_TTS=uplift (UpliftAI REST, mp3)
  KokoroLocalTTS   English, local Kokoro (GPU if available)
  KokoroRemoteTTS  English, remote OpenAI-compatible /v1/audio/speech

Adapters send text as given. Rewriting a reply into its spoken form is done by
server/normalization.py, for adapters that set ``wants_spoken_form``.
"""

from __future__ import annotations

import asyncio

import httpx

from .. import config as C
from .base import TTSProvider


class UpliftTTS(TTSProvider):
    """UpliftAI REST synthesis. One voice handles Urdu and English."""

    wants_spoken_form = True
    engine = "uplift"

    def __init__(
        self,
        api_key: str = "",
        base: str = "",
        path: str = "",
        voice: str = "",
        output_format: str = "",
        speed: float = 1.0,
        lang: str = "ur",
    ):
        self.api_key = api_key or C.UPLIFT_KEY
        self.base = (base or C.UPLIFT_BASE).rstrip("/")
        self.path = path or C.UPLIFT_PATH
        self.voice = voice or C.UPLIFT_VOICE
        self.output_format = output_format or C.UPLIFT_FORMAT
        self.lang = lang
        # 1.0 means "not set by the caller": use the configured per-language rate.
        self.speed = speed if speed != 1.0 else (
            C.UPLIFT_SPEED_EN if lang == "en" else C.UPLIFT_SPEED
        )

    async def synthesize(self, text: str) -> tuple[bytes, str]:
        if not (text or "").strip():
            return b"", "audio/mpeg"
        path = self.path if self.path.startswith("/") else f"/{self.path}"
        url = f"{self.base}{path}"
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        payload = {
            "voiceId": self.voice,
            "text": text,
            "speed": self.speed,
            "outputFormat": self.output_format,
        }
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.post(url, json=payload, headers=headers)
            r.raise_for_status()
            mime = r.headers.get("content-type", "audio/mpeg").split(";")[0]
            return r.content, mime or "audio/mpeg"


class KokoroLocalTTS(TTSProvider):
    """In-process Kokoro pipeline (GPU if available)."""

    wants_spoken_form = True
    engine = "kokoro"
    _pipe = None  # one pipeline per process

    def __init__(self, voice: str = ""):
        self.voice = voice or C.VOICE_EN

    def _get_pipe(self):
        if KokoroLocalTTS._pipe is None:
            from kokoro import KPipeline

            KokoroLocalTTS._pipe = KPipeline(lang_code="a")  # 'a' = American English
        return KokoroLocalTTS._pipe

    def warm(self) -> None:
        self._get_pipe()

    async def synthesize(self, text: str) -> tuple[bytes, str]:
        import io

        import numpy as np
        import soundfile as sf

        text = (text or "").strip()
        if not text:
            return b"", "audio/wav"
        pipe = self._get_pipe()

        def run() -> tuple[bytes, str]:
            parts = []
            for _, _, audio in pipe(text, voice=self.voice):
                if hasattr(audio, "detach"):
                    audio = audio.detach().cpu().numpy()
                parts.append(np.asarray(audio, dtype=np.float32).reshape(-1))
            if not parts:
                return b"", "audio/wav"
            buf = io.BytesIO()
            sf.write(buf, np.concatenate(parts), 24000, format="WAV", subtype="PCM_16")
            return buf.getvalue(), "audio/wav"

        return await asyncio.to_thread(run)


class KokoroRemoteTTS(TTSProvider):
    wants_spoken_form = True
    engine = "kokoro"

    def __init__(self, base: str = "", path: str = "", token: str = "", model: str = "", voice: str = "", fmt: str = ""):
        self.base = (base or C.KOKORO_BASE).rstrip("/")
        self.path = path or C.KOKORO_PATH
        self.token = token or C.KOKORO_TOKEN
        self.model = model or C.KOKORO_MODEL
        self.voice = voice or C.VOICE_EN
        self.fmt = fmt or C.KOKORO_FORMAT

    async def synthesize(self, text: str) -> tuple[bytes, str]:
        text = (text or "").strip()
        if not text:
            return b"", "audio/mpeg"
        url = f"{self.base}{self.path}"
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        payload = {"model": self.model, "input": text, "voice": self.voice, "response_format": self.fmt}
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.post(url, json=payload, headers=headers)
            r.raise_for_status()
            mime = r.headers.get("content-type", "audio/mpeg").split(";")[0]
            return r.content, mime or "audio/mpeg"


_tts_cache: dict[str, TTSProvider] = {}


def get_tts_provider(lang: str, avatar: str = "female") -> TTSProvider:
    """The configured TTS adapter for a language and presenter, cached per voice.

    ``avatar`` picks the voice, not the engine: the male rig uses UPLIFT_VOICE_MALE on
    Uplift and VOICE_EN_MALE on Kokoro.
    """
    male = avatar == "male"
    key = f"{lang}:{C.EN_TTS if lang != 'ur' else 'uplift'}:{'male' if male else 'female'}"
    if key not in _tts_cache:
        if lang == "ur":
            _tts_cache[key] = UpliftTTS(voice=C.UPLIFT_VOICE_MALE if male else C.UPLIFT_VOICE)
        elif C.EN_TTS == "uplift":
            # The male Uplift voice covers both languages; there is no separate male English id.
            _tts_cache[key] = UpliftTTS(
                voice=C.UPLIFT_VOICE_MALE if male else C.UPLIFT_VOICE_EN, lang="en"
            )
        else:
            voice = C.VOICE_EN_MALE if male else C.VOICE_EN
            kokoro = KokoroLocalTTS if C.EN_TTS == "local" else KokoroRemoteTTS
            _tts_cache[key] = kokoro(voice=voice)
    return _tts_cache[key]
