"""TTS adapters — each implements :class:`server.providers.base.TTSProvider`.

  UpliftTTS        Urdu, and English while APP_EN_TTS=uplift — UpliftAI REST (mp3)
  KokoroLocalTTS   English — local Kokoro (GPU if available)
  KokoroRemoteTTS  English — remote OpenAI-compatible /v1/audio/speech

Shared by both entrypoints: server/app.py (FastAPI) and mari_s2s/handlers/*.py
(huggingface/speech-to-speech plugin handlers) — no more duplicated REST-call logic.
"""

from __future__ import annotations

import asyncio
import re

import httpx

from .. import config as C
from .base import TTSProvider


# The brand name has to be forced into words for Uplift's Urdu-first voices, both ways:
# in English text "Sky47" comes out as one mangled word ("SkySitalis"), and in Urdu text
# the digits are read as the Urdu number — "اسکائی ۴۷" is spoken "sentaalees", not "forty
# seven". Spelling it out fixes both, and "Sky Forty Seven" is pronounced identically in
# an Urdu sentence, so one replacement covers every reply.
_SKY = r"(?:Sky|\u0627\u0633\u06a9\u0627\u0626\u06cc|\u0633\u06a9\u0627\u0626\u06cc|\u0627\u0633\u06a9\u0627\u06cc|\u0633\u06a9\u0627\u06cc)"
_47 = r"(?:47|\u06f4\u06f7|\u0664\u0667)"  # ASCII, Urdu (۴۷) and Arabic-Indic (٤٧) digits
# Mari Energies' own reports are full of initialisms and industry units that the voices
# either spell out wrongly or run together into a non-word, so they are written out too.
# ``\b``-anchored and applied to both languages, since an Urdu reply keeps these in Latin script.
_ACRONYMS = {
    "MPCL": "M P C L",
    "PSX": "P S X",
    "OGDCL": "O G D C L",
    "MMBOE": "million barrels of oil equivalent",
    "KBOEPD": "thousand barrels of oil equivalent per day",
    "MMSCFD": "million standard cubic feet per day",
    "MMSCF": "million standard cubic feet",
    "BBLs": "barrels",
    "BBL": "barrel",
    "REE": "rare earth elements",
    "TCF": "trillion cubic feet",
    "E&P": "exploration and production",
    "ESG": "E S G",
    "EPS": "earnings per share",
}

_SAY_AS = (
    (re.compile(rf"(?<!\w){_SKY}\s*-?\s*{_47}(?!\w)", re.I), "Sky Forty Seven"),
    # currency reads after the amount in both languages: "PKR 65 billion" -> "65 billion rupees"
    (re.compile(r"\b(?:PKR|Rs\.?)\s*([\d,.]+)\s*(billion|million|trillion|bn|mn)?\b", re.I),
     lambda m: f"{m.group(1)} {m.group(2) + ' ' if m.group(2) else ''}rupees"),
    (re.compile(r"\bUSD\s*([\d,.]+)\s*(billion|million|trillion)?\b", re.I),
     lambda m: f"{m.group(1)} {m.group(2) + ' ' if m.group(2) else ''}US dollars"),
    *((re.compile(rf"\b{re.escape(k)}\b"), v) for k, v in _ACRONYMS.items()),
)


def _spoken(text: str) -> str:
    for pattern, replacement in _SAY_AS:
        text = pattern.sub(replacement, text)
    return text


class UpliftTTS(TTSProvider):
    """UpliftAI REST synthesis. Handles Urdu and English with the same voice."""

    def __init__(
        self,
        api_key: str = "",
        base: str = "",
        path: str = "",
        voice: str = "",
        output_format: str = "",
        speed: float = 1.0,
    ):
        self.api_key = api_key or C.UPLIFT_KEY
        self.base = (base or C.UPLIFT_BASE).rstrip("/")
        self.path = path or C.UPLIFT_PATH
        self.voice = voice or C.UPLIFT_VOICE
        self.output_format = output_format or C.UPLIFT_FORMAT
        self.speed = speed

    async def synthesize(self, text: str) -> tuple[bytes, str]:
        text = (text or "").strip()
        if not text:
            return b"", "audio/mpeg"
        path = self.path if self.path.startswith("/") else f"/{self.path}"
        url = f"{self.base}{path}"
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        payload = {
            "voiceId": self.voice,
            "text": _spoken(text),
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

    _pipe = None  # class-level cache: one pipeline instance per process

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


# ─────────────────────────── selection + dispatch ────────────────────
_tts_cache: dict[str, TTSProvider] = {}


def get_tts_provider(lang: str) -> TTSProvider:
    """Return the configured TTS adapter for a language (cached — local-model
    adapters keep their loaded pipeline across calls)."""
    key = f"{lang}:{C.EN_TTS if lang != 'ur' else 'uplift'}"
    if key not in _tts_cache:
        if lang == "ur":
            _tts_cache[key] = UpliftTTS()
        elif C.EN_TTS == "uplift":
            # No Kokoro deployment right now — English goes out through Uplift too.
            _tts_cache[key] = UpliftTTS(voice=C.UPLIFT_VOICE_EN)
        else:
            _tts_cache[key] = KokoroLocalTTS() if C.EN_TTS == "local" else KokoroRemoteTTS()
    return _tts_cache[key]


async def tts(text: str, lang: str) -> tuple[bytes, str]:
    return await get_tts_provider(lang).synthesize(text)
