"""Runs one reply turn over the WebSocket: reply sentences → TTS → audio and lipsync.

Protocol, server → client:
    {"stt", text}                       the transcript (skipped for typed turns)
    per sentence: {"reply", text, demo}, then {"tts", mime, clip?} followed by audio bytes
    {"done", spoken}
    out of band: {"lipsync", uid, names?, frames}, keyed to the {"tts"} message's clip

Synthesis runs ahead of playback: each sentence's TTS starts as soon as the responder
yields it, so the next one renders while this one is sent and the LLM keeps streaming.
Sentences still go out strictly in order. ``tests/test_turn_timing.py`` guards that
overlap, because nothing on the wire shows whether it is still happening.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass

from fastapi import WebSocket

from .. import avatar, config
from ..logging_setup import request_id
from ..personas import Persona, get_persona
from . import speech
from .replies import canned
from .responder import respond_sentences

logger = logging.getLogger(__name__)

# Sentences synthesized ahead and not yet sent. Small, so an interrupted turn wastes
# little and Uplift never sees more than this many concurrent calls from one turn.
_LOOKAHEAD = 2

_turn_seq = 0


def _next_turn_id() -> str:
    """A short id per turn, embedded in every lipsync clip id of that turn."""
    global _turn_seq
    _turn_seq += 1
    return f"t{_turn_seq}"


@dataclass(slots=True)
class _Synthesis:
    """One sentence on its way to the browser."""

    text: str
    is_demo: bool
    # None when TTS is not configured: the sentence is still sent, just not spoken.
    task: asyncio.Task | None


class TurnRunner:
    """One reply turn on one socket.

    A class rather than a function with closures because a turn carries real state —
    the send lock, the lipsync session, the in-flight synthesis tasks, the timings —
    and threading that through nested functions is what made the original 140-line
    version hard to follow.

    Build it, call ``run()`` once, discard it.
    """

    def __init__(
        self,
        sock: WebSocket,
        lang: str,
        persona: Persona,
    ) -> None:
        self._sock = sock
        self._lang = lang
        self._persona = persona
        self._turn_id = _next_turn_id()

        # Starlette WebSockets are not safe for concurrent sends, and the A2F
        # publishers send too. The lock also keeps each {"tts"} header glued to its
        # audio bytes.
        self._send_lock = asyncio.Lock()

        a2f = avatar.get_a2f_client()
        face_params, bs_multipliers = persona.a2f_tuning()
        self._lips = (
            avatar.LipsyncTurn(a2f, self.send_json, self._turn_id, face_params, bs_multipliers)
            if a2f is not None
            else None
        )

        self._started_at = time.perf_counter()
        self._first_audio_ms: float | None = None
        self._synth_ms: list[int] = []
        self._in_flight: list[asyncio.Task] = []

    # ── sending ─────────────────────────────────────────────────────

    async def send_json(self, payload: dict) -> None:
        async with self._send_lock:
            await self._sock.send_json(payload)

    async def _send_audio(self, header: dict, audio: bytes) -> None:
        async with self._send_lock:
            await self._sock.send_json(header)
            await self._sock.send_bytes(audio)

    # ── synthesis ───────────────────────────────────────────────────

    async def _synthesize(self, text: str) -> tuple[bytes, str, int]:
        started = time.perf_counter()
        audio, mime = await speech.speak(text, self._lang, self._persona.id)
        return audio, mime, round((time.perf_counter() - started) * 1000)

    def _start_synthesis(self, text: str, is_demo: bool) -> _Synthesis:
        """Begin one sentence's TTS now, so it renders while the previous one plays."""
        if not config.tts_ready(self._lang, self._persona.id):
            return _Synthesis(text, is_demo, None)
        task = asyncio.create_task(self._synthesize(text))
        self._in_flight.append(task)
        return _Synthesis(text, is_demo, task)

    async def _deliver(self, sentence: _Synthesis) -> bool:
        """Send one sentence, its audio and its lipsync clip. True if audio was sent."""
        await self.send_json({"type": "reply", "text": sentence.text, "demo": sentence.is_demo})
        if sentence.task is None:
            return False

        # Opened before waiting on the audio, so the A2F stream primes while it
        # renders — but only after the previous sentence's audio went out, which is
        # what A2F_MAX_CLIPS=1 expects.
        clip = self._lips.open_clip() if self._lips is not None else None
        try:
            audio, mime, elapsed_ms = await sentence.task
        except Exception as exc:
            self._release_clip(clip)
            await self.send_json({"type": "warn", "message": f"tts: {exc}"})
            return False

        self._synth_ms.append(elapsed_ms)
        if not audio:
            self._release_clip(clip)
            return False

        header: dict = {"type": "tts", "mime": mime}
        if clip is not None:
            header["clip"] = clip
        try:
            await self._send_audio(header, audio)
        except Exception as exc:
            self._release_clip(clip)
            await self.send_json({"type": "warn", "message": f"tts: {exc}"})
            return False

        if self._first_audio_ms is None:
            self._first_audio_ms = (time.perf_counter() - self._started_at) * 1000
        if clip is not None and self._lips is not None:
            # The exact bytes the browser is about to play, so the frames line up.
            self._lips.feed(clip, audio, mime)
        return True

    def _release_clip(self, clip: str | None) -> None:
        """This sentence produced no audio — let its A2F slot go."""
        if clip is not None and self._lips is not None:
            self._lips.cancel(clip)

    # ── the turn ────────────────────────────────────────────────────

    async def run(
        self,
        transcript: str,
        *,
        echo_transcript: bool = True,
        history: list | None = None,
        spoke: bool = True,
    ) -> None:
        """Speak the reply to ``transcript``, then close out the turn."""
        # Synthesis tasks are created below, so they inherit this connection/turn ID.
        id_token = request_id.set(f"{request_id.get()}/{self._turn_id}")
        producer: asyncio.Task | None = None
        try:
            if echo_transcript:
                await self.send_json({"type": "stt", "text": transcript, "lang": self._lang})

            if not transcript:
                spoken = await self._answer_silence(spoke)
                if spoken is None:
                    return
            else:
                producer, spoken = await self._speak_reply(transcript, history)

            await self.send_json({"type": "done", "spoken": spoken})
            self._log_timings()
            if self._lips is not None:
                # The browser is still playing the audio these frames belong to.
                await self._lips.drain()
        except Exception:
            if self._lips is not None:
                await self._lips.abort()
            raise
        finally:
            # Interrupted or failed: nothing still rendering is going to be sent.
            if producer is not None:
                producer.cancel()
            for task in self._in_flight:
                task.cancel()
            request_id.reset(id_token)

    async def _answer_silence(self, spoke: bool) -> bool | None:
        """Nothing was transcribed. Returns None when the turn is already finished."""
        if not spoke:
            # Answering silence made the kiosk talk to an empty room in a loop.
            await self.send_json({"type": "done", "spoken": False})
            return None
        line = canned("no_speech", self._lang, self._persona.id)
        return await self._deliver(self._start_synthesis(line, is_demo=True))

    async def _speak_reply(
        self, transcript: str, history: list | None
    ) -> tuple[asyncio.Task, bool]:
        """Stream the reply, synthesizing ahead and sending strictly in order.

        The producer task pulls sentences from the LLM and starts their TTS; this
        coroutine sends them. A semaphore caps how far synthesis may run ahead, so an
        interrupted turn wastes at most that many calls.
        """
        lookahead = asyncio.Semaphore(_LOOKAHEAD)
        queue: asyncio.Queue[_Synthesis | None] = asyncio.Queue()

        async def produce() -> None:
            try:
                async for text, is_demo in respond_sentences(
                    transcript, self._lang, history, self._persona.id
                ):
                    await lookahead.acquire()
                    queue.put_nowait(self._start_synthesis(text, is_demo))
            finally:
                queue.put_nowait(None)  # sentinel: the reply is complete

        producer = asyncio.create_task(produce())
        spoken = False
        while (sentence := await queue.get()) is not None:
            if await self._deliver(sentence):
                spoken = True
            lookahead.release()
        await producer  # re-raises a failure of the reply stream
        return producer, spoken

    def _log_timings(self) -> None:
        """One line per spoken turn: the latency numbers worth watching in production."""
        if self._first_audio_ms is None:
            return
        logger.info(
            "turn %s: first audio %.0f ms after the transcript; synth ms per sentence %s",
            self._turn_id,
            self._first_audio_ms,
            self._synth_ms,
        )


async def run_reply(
    sock: WebSocket,
    transcript: str,
    lang: str,
    echo_transcript: bool = True,
    history: list | None = None,
    avatar_id: str | None = None,
    spoke: bool = True,
) -> None:
    """Speak the reply to ``transcript`` (spoken or typed) on this socket.

    ``echo_transcript`` is False for typed turns, whose text the browser already shows.
    ``avatar_id`` is fixed for the whole turn, so the voice never changes mid-reply;
    an unknown one becomes the default presenter rather than an error.
    ``spoke`` is the browser VAD's verdict for an empty transcript: True means the
    visitor spoke and STT lost it, which gets an apology; False means nobody spoke.
    """
    runner = TurnRunner(sock, lang, get_persona(avatar_id))
    await runner.run(transcript, echo_transcript=echo_transcript, history=history, spoke=spoke)
