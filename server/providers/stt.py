"""STT adapters, each implementing :class:`server.providers.base.STTProvider`.

  SonioxSTT        Urdu, one-shot over the Soniox realtime websocket
  SonioxStream     Urdu, live partials for the /ws turn
  WhisperLocalSTT  English, local faster-whisper (GPU if available)
  WhisperRemoteSTT English, remote OpenAI-compatible /audio/transcriptions

Used by server/app.py.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import struct
import threading

import httpx

from .. import config
from .base import STTProvider

logger = logging.getLogger(__name__)

# Biases the recognizer toward the kiosk's vocabulary; without it "Mari" comes back as
# "Mary". Deliberately a bare name list and not a sentence: this text is also Whisper's
# initial_prompt, and on near-silent audio the decoder completes the prompt rather than
# transcribing. Phrased as a narrative opener ("The following is a conversation with
# Maryam at the Mari Energies kiosk...") it emitted that very line as if a visitor had
# said it, then drifted into the YouTube boilerplate it resembles ("Thanks for
# watching!"). A list carries the same vocabulary with no sentence to continue.
_VOCAB_HINT_EN = (
    "Mari Energies, Mari Petroleum, MPCL, the Mari Gas Field, Daharki, "
    "Mari Services, Mari Minerals, Mari Technologies, Sky47, GEM Energy, "
    "Faheem Haider, PSX, OGDCL, Maryam."
)
_VOCAB_HINT_UR = (
    "ماری انرجیز، ماری پیٹرولیم، ایم پی سی ایل، ماری گیس فیلڈ، ڈھرکی، ماری سروسز، "
    "ماری منرلز، ماری ٹیکنالوجیز، سکائی فورٹی سیون، جیم انرجی، فہیم حیدر، پی ایس ایکس"
)


def _vocab_hint(lang: str) -> str:
    return _VOCAB_HINT_UR if lang == "ur" else _VOCAB_HINT_EN


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
        b"RIFF"
        + struct.pack("<I", 36 + len(pcm))
        + b"WAVEfmt "
        + struct.pack("<IHHIIHH", 16, 1, 1, sr, sr * 2, 2, 16)
        + b"data"
        + struct.pack("<I", len(pcm))
        + pcm
    )


def resample_pcm16(pcm: bytes, src_sr: int, dst_sr: int = 16000) -> bytes:
    if src_sr == dst_sr or not pcm:
        return pcm
    import numpy as np

    a = np.frombuffer(pcm, dtype=np.int16).astype(np.float32)
    n = round(a.size * dst_sr / src_sr)
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
        self.api_key = api_key or config.SONIOX_KEY
        self.url = url or config.SONIOX_URL
        self.model = model or config.SONIOX_MODEL
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
            "context": _vocab_hint(self.lang),
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
                    raise RuntimeError(
                        f"soniox {data.get('error_code')}: {data.get('error_message')}"
                    )
                for tok in data.get("tokens", []):
                    text = tok.get("text", "")
                    # skip Soniox control tokens like <end>, <fin>
                    if tok.get("is_final") and not (text.startswith("<") and text.endswith(">")):
                        finals.append(text)
                if data.get("finished"):
                    break
        return "".join(finals).strip()


# How long finish() keeps waiting when the first grace produced no text at all, and
# how often it looks. Only an otherwise-lost turn ever waits this long; see finish().
_EMPTY_GRACE = 1.5
_EMPTY_POLL = 0.05


class SonioxStream:
    """Live Soniox realtime STT. Open once per turn, ``send()`` PCM frames as they are
    captured, then ``finish()`` to flush and get the final transcript. Partial results
    are pushed to ``on_partial`` for live captions — so STT overlaps with speaking and
    the transcript is ready almost as soon as the user stops."""

    def __init__(
        self, lang: str = "ur", on_partial=None, api_key: str = "", url: str = "", model: str = ""
    ):
        self.lang = lang
        self.on_partial = on_partial
        self.api_key = api_key or config.SONIOX_KEY
        self.url = url or config.SONIOX_URL
        self.model = model or config.SONIOX_MODEL
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
            "context": _vocab_hint(self.lang),
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
            saw_token = False
            for tok in data.get("tokens", []):
                text = tok.get("text", "")
                if text.startswith("<") and text.endswith(">"):
                    continue
                saw_token = True
                if tok.get("is_final"):
                    self.finals.append(text)
                else:
                    partial += text
            # Replaced by any message with a real token (a final one included, or the
            # tail is said twice), but never blanked by a keepalive or marker-only
            # message, which would leave finish() with an empty transcript.
            if saw_token:
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
        """End the utterance and return finals + the latest partial after a short grace.

        Soniox finalizes ~1s after end-of-audio, but the partials already hold the text,
        so this does not wait for finalization.
        """
        try:
            if self.ws:
                await self.ws.send("")  # end-of-audio
        except Exception:
            pass
        await asyncio.sleep(grace)  # let the reader catch the tail of the partial
        text = ("".join(self.finals) + self.last_partial).strip()
        # Still empty: wait longer, polling. Only a turn that would otherwise be lost pays.
        if not text:
            for _ in range(int(_EMPTY_GRACE / _EMPTY_POLL)):
                await asyncio.sleep(_EMPTY_POLL)
                text = ("".join(self.finals) + self.last_partial).strip()
                if text:
                    break
        # In the background: the close handshake (~1s) must not delay the reply.
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
    # app.py warms every presenter concurrently and they all share that one instance.
    # Unlocked, two of those tasks clear the None check together and each builds its own
    # model; the loser is simply dropped. That was ~150 MB of waste with base.en, but a
    # stranded large-v3-turbo holds ~1.6 GB of VRAM until the process exits, on a card
    # also running Audio2Face.
    _model_lock = threading.Lock()

    def __init__(self, model_size: str = ""):
        self.model_size = model_size or config.WHISPER_LOCAL_MODEL

    def _get_model(self):
        if WhisperLocalSTT._model is not None:
            return WhisperLocalSTT._model
        with WhisperLocalSTT._model_lock:
            # Re-checked with the lock held: whoever waited here while the first caller
            # built the model must use it rather than build a second.
            if WhisperLocalSTT._model is not None:
                return WhisperLocalSTT._model
            import ctranslate2
            from faster_whisper import WhisperModel

            # compute_type has to match the device. int8 is right for CPU, but on a GPU
            # it leaves the card mostly idle, and the turbo and large models are only
            # fast enough for a visitor's patience in float16.
            #
            # The device is chosen by asking ctranslate2 what it can actually see rather
            # than by passing device="auto": "auto" also resolves to CPU when a GPU is
            # present but unusable, so a kiosk that lost its GPU passthrough would go on
            # answering, several seconds slower, with nothing in the log to say why.
            if ctranslate2.get_cuda_device_count() > 0:
                try:
                    model = WhisperModel(
                        self.model_size, device="cuda", compute_type="float16"
                    )
                    # Constructing the model does not touch cuBLAS or cuDNN, so an image
                    # that has the driver but not those libraries loads cleanly here and
                    # then raises on every visitor's turn instead. One throwaway decode
                    # moves that failure to startup, where the CPU fallback can take over.
                    import numpy as np

                    list(model.transcribe(np.zeros(1600, dtype=np.float32), language="en")[0])
                    WhisperLocalSTT._model = model
                    logger.info("whisper %s loaded on cuda (float16)", self.model_size)
                    return WhisperLocalSTT._model
                except Exception as exc:
                    logger.warning("whisper cuda unusable, falling back to cpu: %s", exc)
            WhisperLocalSTT._model = WhisperModel(
                self.model_size, device="cpu", compute_type="int8"
            )
            logger.info("whisper %s loaded on cpu (int8)", self.model_size)
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
            # initial_prompt biases Whisper's decoder toward this vocabulary without
            # constraining it to only these words — it is context, not a grammar. This
            # is what stops "Mari" (the company's own name, said constantly here) from
            # coming back as the far more common English name "Mary".
            #
            # The next two arguments keep a silent or noisy buffer from becoming phantom
            # visitor input. The browser's VAD decides when to send, so a burst of room
            # noise still arrives here with no speech in it:
            #   vad_filter  drops non-speech audio, so such a buffer transcribes to ""
            #               instead of to whatever the decoder invents to fill it.
            #   condition_on_previous_text=False  stops one hallucination seeding the
            #               next; with it on, the invented line came back as context and
            #               the kiosk held a conversation with itself.
            #
            # beam_size stays above 1 because greedy decoding makes the initial_prompt
            # above leak into the transcript. On real kiosk-mic turns, a visitor asking
            # "...the industry in which Mari Energies works" came back as "...in which
            # Mari Minerals, GEM Energy, Faheem Haider, PSX, OGDCL," - the decoder
            # abandoned the sentence and recited the hint. Greedy has no competing
            # hypothesis to prefer, so once it steps onto the prompt it cannot come
            # back; a beam keeps the real continuation alive and outscores it.
            # Dropping the hint instead is not the fix: without it "Mari" degrades to
            # "Marley" / "Mardi Gras". Measured on this kiosk GPU over 8 recorded turns
            # (57s of audio): leaks 1/8 -> 0/8, total STT 2.53s -> 2.56s.
            segments, _ = model.transcribe(
                audio,
                language="en",
                beam_size=5,
                vad_filter=True,
                condition_on_previous_text=False,
                initial_prompt=_vocab_hint("en"),
            )
            return "".join(s.text for s in segments).strip()

        return await asyncio.to_thread(run)


class WhisperRemoteSTT(STTProvider):
    """Remote Whisper — OpenAI-compatible /audio/transcriptions multipart."""

    def __init__(self, url: str = "", token: str = "", model: str = ""):
        self.url = url or config.WHISPER_URL
        self.token = token or config.WHISPER_TOKEN
        self.model = model or config.WHISPER_MODEL

    async def transcribe(self, wav: bytes) -> str:
        headers = {}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        files = {"file": ("audio.wav", wav, "audio/wav")}
        # "prompt" is the OpenAI-compatible name for the same initial_prompt bias used
        # by the local model below — see _VOCAB_HINT_EN for why "Mari" needs it.
        data = {
            "model": self.model,
            "language": "en",
            "response_format": "json",
            "prompt": _vocab_hint("en"),
        }
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
    """The configured STT adapter for a language, cached so local models stay loaded."""
    key = f"{lang}:{config.EN_STT if lang != 'ur' else 'soniox'}"
    if key not in _stt_cache:
        if lang == "ur":
            _stt_cache[key] = SonioxSTT(lang="ur")
        else:
            _stt_cache[key] = WhisperLocalSTT() if config.EN_STT == "local" else WhisperRemoteSTT()
    return _stt_cache[key]


# "Mari" still sometimes comes back as a homophone. Only shapes that clearly refer to
# the company are corrected, so "call Mary" or "who is Mary" are left alone.
_MARI_SOUND_ALIKES = r"Mary|Marry|Merry|M[aā]ori|Mardi"

# Followed by a word from the company's name ("Mary Energies"), or asked about on its
# own ("tell me about Mary").
_MARI_FOLLOWED = r"(?=\s+Energ|\s+Petroleum|\s+Gas\b|\s+Services|\s+Minerals|\s+Technolog|'s\b)"
_MARI_PRECEDED = (
    r"(?<=tell\sme\sabout\s)|(?<=what\sis\s)|(?<=what's\s)|(?<=tell\sme\s)|"
    r"(?<=who\sowns\s)|(?<=explain\s)"
)
_NOT_MARDI_GRAS = r"(?!\s+Gras\b)"
_MISHEARD_MARI_EN = re.compile(
    rf"(?:{_MARI_PRECEDED})(?:{_MARI_SOUND_ALIKES}){_NOT_MARDI_GRAS}\b"
    rf"|\b(?:{_MARI_SOUND_ALIKES}){_NOT_MARDI_GRAS}\b{_MARI_FOLLOWED}",
    re.IGNORECASE,
)
_MISHEARD_MARI_UR = re.compile(r"میری(?=\s*انرجیز|\s*پیٹرولیم|\s*گیس|\s*کے|\s*کیا|\s*کون)")


def _fix_misheard_mari(text: str, lang: str) -> str:
    if not text:
        return text
    if lang == "ur":
        return _MISHEARD_MARI_UR.sub("ماری", text)
    return _MISHEARD_MARI_EN.sub("Mari", text)


async def stt(wav: bytes, lang: str) -> str:
    text = await get_stt_provider(lang).transcribe(wav)
    return _fix_misheard_mari(text, lang)
