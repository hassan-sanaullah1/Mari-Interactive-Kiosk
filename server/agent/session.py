"""One WebSocket connection: receive loop, per-message handlers, turn state.

The browser opens a socket per turn and sends one of two openings:

    spoken   {"start", lang, avatar, history} · raw 16 kHz PCM16 frames · {"end", spoke}
    typed    {"text", text, lang, avatar, history}

Urdu audio is relayed to Soniox as it arrives, so partial captions come back while the
visitor is still speaking; English is buffered and transcribed in one go at ``end``.
Either way the turn itself is ``agent/turn.py``'s job — this module only decides which
handler a message belongs to and holds what the connection has been told so far.

It is a class because that state (language, presenter, the audio buffer, the live STT
stream) has to survive between messages. It used to live in local variables inside the
route, which is how the route ended up seven levels deep.
"""

from __future__ import annotations

import json
import logging

from fastapi import WebSocket, WebSocketDisconnect

from .. import config, providers, rag
from ..logging_setup import new_request_id, request_id
from ..personas import default_persona, persona_ids
from .turn import run_reply

logger = logging.getLogger(__name__)


class VoiceSession:
    """The state of one connection, and the handlers that advance it."""

    def __init__(self, sock: WebSocket) -> None:
        self._sock = sock
        self._lang = "en"
        self._avatar_id = default_persona().id
        # English audio is buffered here until {"end"}; Urdu goes straight to Soniox.
        self._pcm = bytearray()
        self._stt_stream: providers.SonioxStream | None = None
        # The browser's copy of the conversation. Nothing about the visitor is kept
        # on the server between turns.
        self._history: list = []

    # ── the loop ────────────────────────────────────────────────────

    async def run(self) -> None:
        """Receive until the turn is answered, the client leaves, or a stage fails."""
        # Runs in this socket's own task, so the ID covers only this connection.
        request_id.set(new_request_id())
        await self._sock.accept()
        try:
            while await self._receive_one():
                pass
        except WebSocketDisconnect:
            pass
        except Exception as exc:  # pragma: no cover - last resort
            logger.exception("turn failed: %s", exc)
            await self._try_send({"type": "error", "message": str(exc) or exc.__class__.__name__})
        finally:
            await self.aclose()

    async def _receive_one(self) -> bool:
        """Handle one frame. False once the connection is finished with."""
        message = await self._sock.receive()
        if message["type"] == "websocket.disconnect":
            return False

        if (audio := message.get("bytes")) is not None:
            await self._on_audio(bytes(audio))
            return True

        text = message.get("text")
        if text is None:
            return True

        event = json.loads(text)
        handler = {
            "start": self._on_start,
            "text": self._on_typed_turn,
            "end": self._on_end_of_speech,
        }.get(event.get("type"))
        if handler is None:
            # An unknown type is ignored rather than fatal: a newer browser may send
            # something this server predates.
            return True
        return await handler(event)

    # ── handlers ────────────────────────────────────────────────────

    async def _on_audio(self, audio: bytes) -> None:
        if self._stt_stream is not None:
            await self._stt_stream.send(audio)
        else:
            self._pcm.extend(audio)

    async def _on_start(self, event: dict) -> bool:
        """The visitor is about to speak. Opens live STT for Urdu."""
        lang = event.get("lang", "en")
        self._lang = lang if lang in config.LANGS else "en"
        self._read_turn_settings(event)
        self._pcm.clear()

        if self._lang != "ur" or not config.SONIOX_KEY:
            return True
        # Held before start() so a stream that fails to open is still closed on the
        # way out rather than leaking its reader task.
        self._stt_stream = providers.SonioxStream(self._lang, on_partial=self._send_partial)
        try:
            await self._stt_stream.start()
        except Exception as exc:
            await self._try_send({"type": "error", "message": f"stt: {exc}"})
            return False
        return True

    async def _on_typed_turn(self, event: dict) -> bool:
        """A question from the chat composer: no audio, no transcript to echo back."""
        typed = (event.get("text") or "").strip()
        if (named_lang := event.get("lang")) in config.LANGS:
            self._lang = named_lang
        self._read_turn_settings(event)
        await self._close_stt_stream()

        rag.prestart(typed)
        await self._answer(typed, echo_transcript=False)
        return False

    async def _on_end_of_speech(self, event: dict) -> bool:
        """The visitor stopped talking. Transcribe, then answer."""
        try:
            transcript = await self._transcribe()
        except Exception as exc:
            await self._try_send({"type": "error", "message": f"stt: {exc}"})
            return False

        # Embedding starts now, so retrieval finds the vector ready.
        rag.prestart(transcript)
        # An older browser sends a bare {"end"} with no `spoke`; it keeps getting the
        # apology, which is the right answer when we cannot tell.
        await self._answer(transcript, spoke=bool(event.get("spoke", True)))
        return False

    # ── pieces the handlers share ───────────────────────────────────

    def _read_turn_settings(self, event: dict) -> None:
        """Presenter and history, which both openings carry."""
        if (named := event.get("avatar")) in persona_ids():
            self._avatar_id = named
        self._history = event.get("history") or []

    async def _transcribe(self) -> str:
        """Whatever the visitor said: from the live stream, or the buffered audio."""
        if self._stt_stream is not None:
            stream, self._stt_stream = self._stt_stream, None
            return await stream.finish()
        if not self._pcm:
            return ""
        return await providers.stt(providers.pcm16_to_wav(bytes(self._pcm)), self._lang)

    async def _answer(
        self, transcript: str, *, echo_transcript: bool = True, spoke: bool = True
    ) -> None:
        await run_reply(
            self._sock,
            transcript,
            self._lang,
            echo_transcript=echo_transcript,
            history=self._history,
            avatar_id=self._avatar_id,
            spoke=spoke,
        )

    async def _send_partial(self, text: str) -> None:
        """Live caption while the visitor is still speaking."""
        await self._try_send({"type": "partial", "text": text})

    async def _try_send(self, payload: dict) -> None:
        """Send if the socket is still there. A closed socket is not an error here."""
        try:
            await self._sock.send_json(payload)
        except Exception:
            logger.debug("could not send %s: socket already gone", payload.get("type"))

    async def _close_stt_stream(self) -> None:
        if self._stt_stream is not None:
            stream, self._stt_stream = self._stt_stream, None
            await stream.close()

    async def aclose(self) -> None:
        await self._close_stt_stream()
        try:
            await self._sock.close()
        except Exception:
            logger.debug("socket already closed")
