"""Runs one reply turn over the WebSocket: reply sentences → TTS → audio and lipsync.

Protocol, server → client:
    {"stt", text}                       the transcript (skipped for typed turns)
    per sentence: {"reply", text, demo}, then {"tts", mime, clip?} followed by audio bytes
    {"done", spoken}
    out of band: {"lipsync", uid, names?, frames}, keyed to the {"tts"} message's clip

Synthesis runs ahead of playback: each sentence's TTS starts as soon as the responder
yields it, so the next one renders while this one is sent and the LLM keeps streaming.
Sentences still go out strictly in order.
"""

from __future__ import annotations

import asyncio
import logging
import time

from fastapi import WebSocket

from .. import avatar
from .. import config as C
from . import speech
from .replies import canned
from .responder import respond_sentences

logger = logging.getLogger(__name__)

# Sentences synthesized ahead and not yet sent. Small, so an interrupted turn wastes
# little and Uplift never sees more than this many concurrent calls from one turn.
_LOOKAHEAD = 2

_turn_seq = 0


async def run_reply(
    sock: WebSocket,
    transcript: str,
    lang: str,
    echo_transcript: bool = True,
    history: list | None = None,
    avatar_id: str = "female",
    spoke: bool = True,
) -> None:
    """Speak the reply to ``transcript`` (spoken or typed) on this socket.

    ``echo_transcript`` is False for typed turns, whose text the browser already shows.
    ``avatar_id`` is fixed for the whole turn, so the voice never changes mid-reply.
    ``spoke`` is the browser VAD's verdict for an empty transcript: True means the
    visitor spoke and STT lost it, which gets an apology; False means nobody spoke.
    """
    global _turn_seq
    _turn_seq += 1
    turn_id = f"t{_turn_seq}"

    # Starlette WebSockets are not safe for concurrent sends, and the A2F publishers
    # send too. The lock also keeps each {"tts"} header glued to its audio bytes.
    lock = asyncio.Lock()

    async def send_json(payload: dict) -> None:
        async with lock:
            await sock.send_json(payload)

    async def send_audio(header: dict, audio: bytes) -> None:
        async with lock:
            await sock.send_json(header)
            await sock.send_bytes(audio)

    a2f = avatar.get_a2f_client()
    lips = avatar.LipsyncTurn(a2f, send_json, turn_id) if a2f is not None else None

    t_turn = time.perf_counter()
    first_audio_ms: float | None = None
    synth_ms: list[int] = []
    synths: list[asyncio.Task] = []

    async def synthesize(text: str) -> tuple[bytes, str, int]:
        t = time.perf_counter()
        audio, mime = await speech.speak(text, lang, avatar_id)
        return audio, mime, round((time.perf_counter() - t) * 1000)

    def start_synthesis(text: str) -> asyncio.Task | None:
        """Start one sentence's TTS now; None when TTS isn't configured."""
        if not C.tts_ready(lang, avatar_id):
            return None
        task = asyncio.create_task(synthesize(text))
        synths.append(task)
        return task

    async def deliver(text: str, is_demo: bool, synth: asyncio.Task | None) -> bool:
        """Send one sentence, its audio and its lipsync clip. True if audio was sent."""
        nonlocal first_audio_ms
        await send_json({"type": "reply", "text": text, "demo": is_demo})
        if synth is None:
            return False
        # Opened before waiting on the audio, so the A2F stream primes while it renders,
        # but only after the previous sentence's audio went out, as A2F_MAX_CLIPS=1 expects.
        clip = lips.open_clip() if lips is not None else None
        sent = False
        try:
            audio, mime, ms = await synth
            synth_ms.append(ms)
            if audio:
                header = {"type": "tts", "mime": mime}
                if clip is not None:
                    header["clip"] = clip
                await send_audio(header, audio)
                sent = True
                if first_audio_ms is None:
                    first_audio_ms = (time.perf_counter() - t_turn) * 1000
                if clip is not None:
                    lips.feed(clip, audio, mime)
            elif clip is not None:
                lips.cancel(clip)
        except Exception as exc:
            if clip is not None:
                lips.cancel(clip)
            await send_json({"type": "warn", "message": f"tts: {exc}"})
        return sent

    producer: asyncio.Task | None = None
    try:
        if echo_transcript:
            await send_json({"type": "stt", "text": transcript, "lang": lang})
        spoken = False
        if not transcript:
            if not spoke:
                # Answering silence made the kiosk talk to an empty room in a loop.
                await send_json({"type": "done", "spoken": False})
                return
            line = canned("no_speech", lang, avatar_id)
            spoken = await deliver(line, True, start_synthesis(line))
        else:
            ahead = asyncio.Semaphore(_LOOKAHEAD)
            queue: asyncio.Queue = asyncio.Queue()

            async def produce() -> None:
                try:
                    async for sentence, is_demo in respond_sentences(
                        transcript, lang, history, avatar_id
                    ):
                        await ahead.acquire()
                        queue.put_nowait((sentence, is_demo, start_synthesis(sentence)))
                finally:
                    queue.put_nowait(None)

            producer = asyncio.create_task(produce())
            while (item := await queue.get()) is not None:
                if await deliver(*item):
                    spoken = True
                ahead.release()
            await producer  # re-raises a failure of the reply stream
        await send_json({"type": "done", "spoken": spoken})
        if first_audio_ms is not None:
            logger.info(
                "turn %s: first audio %.0f ms after the transcript; synth ms per sentence %s",
                turn_id, first_audio_ms, synth_ms,
            )
        if lips is not None:
            # The browser is still playing the audio these frames belong to.
            await lips.drain()
    except Exception:
        if lips is not None:
            await lips.abort()
        raise
    finally:
        # Interrupted or failed: nothing still rendering is going to be sent.
        if producer is not None:
            producer.cancel()
        for task in synths:
            task.cancel()
