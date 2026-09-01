"""STT adapters — each implements :class:`server.providers.base.STTProvider`.

  SonioxSTT       Urdu (and any language Soniox supports) — realtime websocket
  WhisperLocalSTT English — local faster-whisper (GPU if available)
  WhisperRemoteSTT English — remote OpenAI-compatible /audio/transcriptions

Shared by both entrypoints: server/app.py (FastAPI) and mari_s2s/handlers/*.py
(huggingface/speech-to-speech plugin handlers) — no more duplicated websocket logic.
"""

from __future__ import annotations

import asyncio
import json
import struct

import httpx

from .. import config as C
from .base import STTProvider


# ─────────────────────────── WAV helpers ────────────────────────────
def wav_to_pcm16(wav: bytes) -> tuple[bytes, int]:
    """Return (pcm_s16le_bytes, sample_rate) from a PCM WAV. Falls back to the
    whole payload at 16 kHz if the header can't be parsed."""
    try:
        if wav[:4] != b"RIFF" or wav[8:12] != b"WAVE":
            return wav, 16000
        sr = 16000
        i = 12
        while i + 8 <= len(wav):
            cid = wav[i : i + 4]
            size = struct.unpack("<I", wav[i + 4 : i + 8])[0]
            body = i + 8
            if cid == b"fmt ":
                sr = struct.unpack("<I", wav[body + 4 : body + 8])[0]
            elif cid == b"data":
                return wav[body : body + size], sr
            i = body + size + (size & 1)
    except Exception:
        pass
    return wav, 16000


def pcm16_to_wav(pcm: bytes, sr: int = 16000) -> bytes:
    """Wrap raw PCM s16le mono in a WAV header (for batch STT like Whisper)."""
    return (
        b"RIFF" + struct.pack("<I", 36 + len(pcm)) + b"WAVEfmt "
        + struct.pack("<IHHIIHH", 16, 1, 1, sr, sr * 2, 2, 16)
        + b"data" + struct.pack("<I", len(pcm)) + pcm
    )


def resample_pcm16(pcm: bytes, src_sr: int, dst_sr: int = 16000) -> bytes:
    if src_sr == dst_sr or not pcm:
        return pcm
    import numpy as np

    a = np.frombuffer(pcm, dtype=np.int16).astype(np.float32)
    n = int(round(a.size * dst_sr / src_sr))
    if n <= 0:
        return b""
    xo = np.linspace(0.0, 1.0, a.size, endpoint=False)
    xn = np.linspace(0.0, 1.0, n, endpoint=False)
    return np.interp(xn, xo, a).astype(np.int16).tobytes()


# ─────────────────────────── Soniox (realtime websocket) ────────────
class SonioxSTT(STTProvider):
    """Batch (one-shot) Soniox transcription. For live/streaming captions use
    :class:`SonioxStream` instead."""

    def __init__(self, api_key: str = "", url: str = "", model: str = "", lang: str = "ur"):
        self.api_key = api_key or C.SONIOX_KEY
        self.url = url or C.SONIOX_URL
        self.model = model or C.SONIOX_MODEL
        self.lang = lang

    async def transcribe(self, wav: bytes) -> str:
        pcm, sr = wav_to_pcm16(wav)
        return await self.transcribe_pcm(resample_pcm16(pcm, sr, 16000))

    async def transcribe_pcm(self, pcm: bytes) -> str:
        """Open ws, send config, stream the utterance, read finals."""
        import websockets

        if not pcm:
            return ""
        cfg = {
            "api_key": self.api_key,
            "model": self.model,
            "audio_format": "pcm_s16le",
            "sample_rate": 16000,
            "num_channels": 1,
            "language_hints": [self.lang],
            "enable_endpoint_detection": True,
        }
        finals: list[str] = []
        async with websockets.connect(self.url, max_size=None) as ws:
            await ws.send(json.dumps(cfg))
            frame = 16000 // 10 * 2  # 100 ms of int16
            for i in range(0, len(pcm), frame):
                await ws.send(pcm[i : i + frame])
            await ws.send("")  # end-of-audio
            async for message in ws:
                if isinstance(message, bytes):
                    continue
                data = json.loads(message)
                if data.get("error_code"):
                    raise RuntimeError(f"soniox {data.get('error_code')}: {data.get('error_message')}")
                for tok in data.get("tokens", []):
                    text = tok.get("text", "")
                    # skip Soniox control tokens like <end>, <fin>
                    if tok.get("is_final") and not (text.startswith("<") and text.endswith(">")):
                        finals.append(text)
                if data.get("finished"):
                    break
        return "".join(finals).strip()


class SonioxStream:
    """Live Soniox realtime STT. Open once per turn, ``send()`` PCM frames as they are
    captured, then ``finish()`` to flush and get the final transcript. Partial results
    are pushed to ``on_partial`` for live captions — so STT overlaps with speaking and
    the transcript is ready almost as soon as the user stops."""

    def __init__(self, lang: str = "ur", on_partial=None, api_key: str = "", url: str = "", model: str = ""):
        self.lang = lang
        self.on_partial = on_partial
        self.api_key = api_key or C.SONIOX_KEY
        self.url = url or C.SONIOX_URL
        self.model = model or C.SONIOX_MODEL
        self.ws = None
        self.finals: list[str] = []
        self.last_partial = ""
        self._reader = None
        self._closing = None

    async def start(self) -> None:
        import websockets

        self.ws = await websockets.connect(self.url, max_size=None)
        cfg = {
            "api_key": self.api_key,
            "model": self.model,
            "audio_format": "pcm_s16le",
            "sample_rate": 16000,
            "num_channels": 1,
            "language_hints": [self.lang],
            "enable_endpoint_detection": True,
        }
        await self.ws.send(json.dumps(cfg))
        self._reader = asyncio.create_task(self._read())

    async def send(self, pcm: bytes) -> None:
        if self.ws and pcm:
            await self.ws.send(pcm)

    async def _read(self) -> None:
        async for message in self.ws:
            if isinstance(message, bytes):
                continue
            data = json.loads(message)
            if data.get("error_code"):
                raise RuntimeError(f"soniox {data.get('error_code')}: {data.get('error_message')}")
            partial = ""
            for tok in data.get("tokens", []):
                text = tok.get("text", "")
                if text.startswith("<") and text.endswith(">"):
                    continue
                if tok.get("is_final"):
                    self.finals.append(text)
                else:
                    partial += text
            self.last_partial = partial
            if self.on_partial:
                cur = ("".join(self.finals) + partial).strip()
                if cur:
                    try:
                        await self.on_partial(cur)
                    except Exception:
                        pass
            if data.get("finished"):
                break

    async def finish(self, grace: float = 0.35) -> str:
        """End the utterance and return the transcript fast. Soniox only emits its
        `is_final` tokens ~1s+ after end-of-audio, but the streaming partials already
        hold the full text (the client keeps streaming through the VAD silence tail).
        So instead of blocking for finalization we take a short grace, then use
        finals + the latest partial. Cuts ~1s off every turn."""
        try:
            if self.ws:
                await self.ws.send("")  # end-of-audio
        except Exception:
            pass
        await asyncio.sleep(grace)      # let the reader catch the tail of the partial
        text = ("".join(self.finals) + self.last_partial).strip()
        # Close in the background — the Soniox close handshake (~1s to JP) must not
        # block the reply from starting.
        self._closing = asyncio.create_task(self.close())
        return text

    async def close(self) -> None:
        if self._reader and not self._reader.done():
            self._reader.cancel()
        try:
            if self.ws:
                await asyncio.wait_for(self.ws.close(), timeout=3)
        except Exception:
            pass
        self.ws = None


# ─────────────────────────── Whisper (English) ───────────────────────
class WhisperLocalSTT(STTProvider):
    """faster-whisper, in-process (GPU if available)."""

    _model = None  # class-level cache: one model instance per process

    def __init__(self, model_size: str = ""):
        self.model_size = model_size or C.WHISPER_LOCAL_MODEL

    def _get_model(self):
        if WhisperLocalSTT._model is None:
            from faster_whisper import WhisperModel
            import torch

            if torch.cuda.is_available():
                try:
                    WhisperLocalSTT._model = WhisperModel(self.model_size, device="cuda", compute_type="float16")
                except Exception:
                    WhisperLocalSTT._model = WhisperModel(self.model_size, device="cpu", compute_type="int8")
            else:
                WhisperLocalSTT._model = WhisperModel(self.model_size, device="cpu", compute_type="int8")
        return WhisperLocalSTT._model

    def warm(self) -> None:
        self._get_model()

    async def transcribe(self, wav: bytes) -> str:
        pcm, sr = wav_to_pcm16(wav)
        return await self.transcribe_pcm(resample_pcm16(pcm, sr, 16000))

    async def transcribe_pcm(self, pcm: bytes) -> str:
        import numpy as np

        if not pcm:
            return ""
        audio = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
        model = self._get_model()

        def run() -> str:
            segments, _ = model.transcribe(audio, language="en", beam_size=1, vad_filter=False)
            return "".join(s.text for s in segments).strip()

        return await asyncio.to_thread(run)


class WhisperRemoteSTT(STTProvider):
    """Remote Whisper — OpenAI-compatible /audio/transcriptions multipart."""

    def __init__(self, url: str = "", token: str = "", model: str = ""):
        self.url = url or C.WHISPER_URL
        self.token = token or C.WHISPER_TOKEN
        self.model = model or C.WHISPER_MODEL

    async def transcribe(self, wav: bytes) -> str:
        headers = {}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        files = {"file": ("audio.wav", wav, "audio/wav")}
        data = {"model": self.model, "language": "en", "response_format": "json"}
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.post(self.url, headers=headers, files=files, data=data)
            r.raise_for_status()
            try:
                return (r.json().get("text") or "").strip()
            except Exception:
                return r.text.strip()

    async def transcribe_pcm(self, pcm: bytes) -> str:
        return await self.transcribe(pcm16_to_wav(pcm))


# ─────────────────────────── selection + dispatch ────────────────────
_stt_cache: dict[str, STTProvider] = {}


def get_stt_provider(lang: str) -> STTProvider:
    """Return the configured STT adapter for a language (cached — local-model
    adapters keep their loaded model across calls)."""
    key = f"{lang}:{C.EN_STT if lang != 'ur' else 'soniox'}"
    if key not in _stt_cache:
        if lang == "ur":
            _stt_cache[key] = SonioxSTT(lang="ur")
        else:
            _stt_cache[key] = WhisperLocalSTT() if C.EN_STT == "local" else WhisperRemoteSTT()
    return _stt_cache[key]


async def stt(wav: bytes, lang: str) -> str:
    return await get_stt_provider(lang).transcribe(wav)
