"""Runs one reply turn over the WebSocket: reply sentences → TTS → audio and lipsync.

Protocol, server → client:
    {"stt", text}                       the transcript (skipped for typed turns)
    per sentence: {"reply", text, demo}, then {"tts", mime, clip?} followed by audio bytes
    {"done", spoken}
    out of band: {"lipsync", uid, names?, frames}, keyed to the {"tts"} message's clip
"""

from __future__ import annotations

import asyncio

from fastapi import WebSocket

from .. import avatar
from .. import config as C
from . import speech
from .replies import canned
from .responder import respond_sentences

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

    async def speak_sentence(text: str) -> bool:
        """Synthesize and send one sentence, with its lipsync clip. True if audio was sent."""
        if not C.tts_ready(lang):
            return False
        # Opened before synthesis so the A2F stream is primed by the time audio exists.
        clip = lips.open_clip() if lips is not None else None
        sent = False
        try:
            audio, mime = await speech.speak(text, lang, avatar_id)
            if audio:
                header = {"type": "tts", "mime": mime}
                if clip is not None:
                    header["clip"] = clip
                await send_audio(header, audio)
                sent = True
                if clip is not None:
                    lips.feed(clip, audio, mime)
            elif clip is not None:
                lips.cancel(clip)
        except Exception as exc:
            if clip is not None:
                lips.cancel(clip)
            await send_json({"type": "warn", "message": f"tts: {exc}"})
        return sent

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
            await send_json({"type": "reply", "text": line, "demo": True})
            spoken = await speak_sentence(line)
        else:
            async for sentence, is_demo in respond_sentences(transcript, lang, history, avatar_id):
                await send_json({"type": "reply", "text": sentence, "demo": is_demo})
                if await speak_sentence(sentence):
                    spoken = True
        await send_json({"type": "done", "spoken": spoken})
        if lips is not None:
            # The browser is still playing the audio these frames belong to.
            await lips.drain()
    except Exception:
        if lips is not None:
            await lips.abort()
        raise
