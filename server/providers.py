"""MARI · Voice — STT / TTS providers (no LiveKit, no s2s runtime).

Direct API clients so this project's web server does speech-to-speech on its own:

  Urdu     STT  Soniox realtime websocket  (stt-rt-v4, language_hints=["ur"])
  English  STT  remote Whisper  (OpenAI-compatible /audio/transcriptions)
  Urdu     TTS  UpliftAI REST   (returns mp3)
  English  TTS  Kokoro          (OpenAI-compatible /v1/audio/speech)

Audio in: the browser sends 16 kHz mono PCM WAV. Soniox wants raw PCM (we strip the
WAV header); Whisper takes the WAV file as-is. Audio out: mp3 bytes the browser plays
directly — no server-side decoding needed.
"""

from __future__ import annotations

import asyncio
import json
import struct

import httpx

from . import config as C


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


def _resample_pcm16(pcm: bytes, src_sr: int, dst_sr: int = 16000) -> bytes:
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


# ─────────────────────────── STT ────────────────────────────────────
async def stt(wav: bytes, lang: str) -> str:
    if lang == "ur":
        return await _stt_soniox(wav, lang)
    return await (_stt_whisper_local(wav) if C.EN_STT == "local" else _stt_whisper(wav))


# ── English STT — local faster-whisper (GPU if available) ────────────
_whisper_model = None


def _get_whisper():
    global _whisper_model
    if _whisper_model is None:
        from faster_whisper import WhisperModel
        import torch

        if torch.cuda.is_available():
            try:
                _whisper_model = WhisperModel(C.WHISPER_LOCAL_MODEL, device="cuda", compute_type="float16")
            except Exception:
                _whisper_model = WhisperModel(C.WHISPER_LOCAL_MODEL, device="cpu", compute_type="int8")
        else:
            _whisper_model = WhisperModel(C.WHISPER_LOCAL_MODEL, device="cpu", compute_type="int8")
    return _whisper_model


async def _stt_whisper_local(wav: bytes) -> str:
    import numpy as np

    pcm, sr = wav_to_pcm16(wav)
    pcm = _resample_pcm16(pcm, sr, 16000)
    if not pcm:
        return ""
    audio = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
    model = _get_whisper()

    def run() -> str:
        segments, _ = model.transcribe(audio, language="en", beam_size=1, vad_filter=False)
        return "".join(s.text for s in segments).strip()

    return await asyncio.to_thread(run)


async def _stt_soniox(wav: bytes, lang: str = "ur") -> str:
    """Soniox realtime: open ws, send config, stream the utterance, read finals."""
    import websockets

    pcm, sr = wav_to_pcm16(wav)
    pcm = _resample_pcm16(pcm, sr, 16000)
    if not pcm:
        return ""

    cfg = {
        "api_key": C.SONIOX_KEY,
        "model": C.SONIOX_MODEL,
        "audio_format": "pcm_s16le",
        "sample_rate": 16000,
        "num_channels": 1,
        "language_hints": [lang],
        "enable_endpoint_detection": True,
    }
    finals: list[str] = []
    async with websockets.connect(C.SONIOX_URL, max_size=None) as ws:
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

    def __init__(self, lang: str = "ur", on_partial=None):
        self.lang = lang
        self.on_partial = on_partial
        self.ws = None
        self.finals: list[str] = []
        self.last_partial = ""
        self._reader = None

    async def start(self) -> None:
        import websockets

        self.ws = await websockets.connect(C.SONIOX_URL, max_size=None)
        cfg = {
            "api_key": C.SONIOX_KEY,
            "model": C.SONIOX_MODEL,
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


def pcm16_to_wav(pcm: bytes, sr: int = 16000) -> bytes:
    """Wrap raw PCM s16le mono in a WAV header (for batch STT like Whisper)."""
    return (
        b"RIFF" + struct.pack("<I", 36 + len(pcm)) + b"WAVEfmt "
        + struct.pack("<IHHIIHH", 16, 1, 1, sr, sr * 2, 2, 16)
        + b"data" + struct.pack("<I", len(pcm)) + pcm
    )


async def _stt_whisper(wav: bytes) -> str:
    """Remote Whisper — OpenAI /audio/transcriptions multipart."""
    headers = {}
    if C.WHISPER_TOKEN:
        headers["Authorization"] = f"Bearer {C.WHISPER_TOKEN}"
    files = {"file": ("audio.wav", wav, "audio/wav")}
    data = {"model": C.WHISPER_MODEL, "language": "en", "response_format": "json"}
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post(C.WHISPER_URL, headers=headers, files=files, data=data)
        r.raise_for_status()
        try:
            return (r.json().get("text") or "").strip()
        except Exception:
            return r.text.strip()


# ─────────────────────────── TTS ────────────────────────────────────
async def tts(text: str, lang: str) -> tuple[bytes, str]:
    """Return (audio_bytes, mime). Empty bytes if unavailable."""
    text = (text or "").strip()
    if not text:
        return b"", "audio/mpeg"
    if lang == "ur":
        return await _tts_uplift(text)
    return await (_tts_kokoro_local(text) if C.EN_TTS == "local" else _tts_kokoro(text))


# ── English TTS — local Kokoro (GPU if available) ───────────────────
_kokoro_pipe = None


def _get_kokoro():
    global _kokoro_pipe
    if _kokoro_pipe is None:
        from kokoro import KPipeline

        _kokoro_pipe = KPipeline(lang_code="a")  # 'a' = American English
    return _kokoro_pipe


async def _tts_kokoro_local(text: str) -> tuple[bytes, str]:
    import io

    import numpy as np
    import soundfile as sf

    pipe = _get_kokoro()

    def run() -> tuple[bytes, str]:
        parts = []
        for _, _, audio in pipe(text, voice=C.VOICE_EN):
            if hasattr(audio, "detach"):
                audio = audio.detach().cpu().numpy()
            parts.append(np.asarray(audio, dtype=np.float32).reshape(-1))
        if not parts:
            return b"", "audio/wav"
        buf = io.BytesIO()
        sf.write(buf, np.concatenate(parts), 24000, format="WAV", subtype="PCM_16")
        return buf.getvalue(), "audio/wav"

    return await asyncio.to_thread(run)


async def _tts_uplift(text: str) -> tuple[bytes, str]:
    url = f"{C.UPLIFT_BASE}{C.UPLIFT_PATH}"
    headers = {"Authorization": f"Bearer {C.UPLIFT_KEY}", "Content-Type": "application/json"}
    payload = {
        "voiceId": C.UPLIFT_VOICE,
        "text": text,
        "outputFormat": C.UPLIFT_FORMAT,
    }
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post(url, json=payload, headers=headers)
        r.raise_for_status()
        mime = r.headers.get("content-type", "audio/mpeg").split(";")[0]
        return r.content, mime or "audio/mpeg"


async def _tts_kokoro(text: str) -> tuple[bytes, str]:
    url = f"{C.KOKORO_BASE}{C.KOKORO_PATH}"
    headers = {"Content-Type": "application/json"}
    if C.KOKORO_TOKEN:
        headers["Authorization"] = f"Bearer {C.KOKORO_TOKEN}"
    payload = {
        "model": C.KOKORO_MODEL,
        "input": text,
        "voice": C.VOICE_EN,
        "response_format": C.KOKORO_FORMAT,
    }
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post(url, json=payload, headers=headers)
        r.raise_for_status()
        mime = r.headers.get("content-type", "audio/mpeg").split(";")[0]
        return r.content, mime or "audio/mpeg"
