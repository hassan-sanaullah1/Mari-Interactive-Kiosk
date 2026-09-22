"""Turn-level lipsync orchestration: TTS audio → Audio2Face → the browser.

``server/agent/turn.py`` synthesizes one audio blob per reply sentence and sends it down
the WebSocket; this module feeds the same blob to Audio2Face:

    speech.speak(sentence)  ──► WebSocket ──► <audio> playback
                            └─► LipsyncTurn.feed() ──► A2F ──► lipsync frames

Each sentence is one A2F "clip" (§10 of THREEJS_A2F_INTEGRATION.md: the NIM is
clip-in / burst-out, so short clips per sentence let sentence N's frames burst
back while sentence N+1 is still being synthesized). Because this app plays one
discrete ``<audio>`` element per sentence rather than a single continuous track,
each clip carries its OWN timeline and the browser anchors it against that
element's ``currentTime`` — so no cumulative per-sentence offsets and no
wall-clock anchor are needed here, and per-clip ordering does not matter.

Wire format (JSON text frames on the existing ``/ws``, additive — every message
carries ``type: "lipsync"`` and older clients ignore unknown types):

    {"type":"lipsync","uid":"t1c0","names":[...52 ARKit names],"frames":[[t,w0,...]]}
    {"type":"lipsync","uid":"t1c0","frames":[[t,w0,...]]}

Frame times are seconds from the start of THAT sentence's audio.
"""

from __future__ import annotations

import asyncio
import io
import logging
from collections.abc import Awaitable, Callable

import numpy as np

from .. import config as C
from .a2f_client import A2F_SAMPLE_RATE, A2FClient

logger = logging.getLogger(__name__)

Send = Callable[[dict], Awaitable[None]]

# A wedged NIM must never hold the WebSocket open past the end of the spoken reply.
_CLIP_TIMEOUT_S = 25.0
# Hard cap on opening a stream, so an unreachable NIM costs one clip's lipsync
# rather than stalling the turn.
_OPEN_TIMEOUT_S = 4.0
# How long a primed stream waits for its sentence's audio; longer means TTS has stalled.
_AUDIO_WAIT_S = 12.0
# The NIM appends ~1.5s of near-neutral frames after real speech; anything past
# the clip's true audio length is dropped so the mouth doesn't hold a stale pose.
_TAIL_TRIM_S = 0.05
# One process-wide pool of NIM stream slots (see LipsyncTurn.__init__).
_SLOTS = asyncio.Semaphore(C.A2F_MAX_CLIPS)


def decode_to_pcm16_16k(data: bytes, mime: str = "") -> bytes:
    """Decode TTS output (mp3 / wav / anything ffmpeg reads) to mono 16 kHz PCM16.

    A2F takes 16-bit PCM at 16 kHz (§7). PyAV is already a dependency of the
    Urdu s2s handler, and handles both providers' formats (Uplift → mp3,
    local Kokoro → wav).
    """
    import av

    container = av.open(io.BytesIO(data))
    resampler = av.audio.resampler.AudioResampler(
        format="s16", layout="mono", rate=A2F_SAMPLE_RATE
    )
    chunks: list[np.ndarray] = []
    try:
        for frame in container.decode(audio=0):
            for r in resampler.resample(frame):
                chunks.append(r.to_ndarray().reshape(-1))
        for r in resampler.resample(None):  # flush the resampler's tail
            chunks.append(r.to_ndarray().reshape(-1))
    finally:
        container.close()
    if not chunks:
        return b""
    return np.concatenate(chunks).astype(np.int16).tobytes()


class _Publisher:
    """Batch callback for one clip — trims the NIM's trailing silence and ships.

    ``clip_secs`` is filled in once the clip's audio length is known; frames can
    only arrive after that, since the NIM emits nothing until end_of_audio.
    """

    def __init__(self, send: Send, uid: str) -> None:
        self._send = send
        self._uid = uid
        self.clip_secs: float | None = None

    async def publish(self, names: list[str] | None, frames: list[list[float]]) -> None:
        if self.clip_secs is not None:
            frames = [f for f in frames if f[0] <= self.clip_secs + _TAIL_TRIM_S]
        if not frames and not names:
            return
        msg: dict = {"type": "lipsync", "uid": self._uid, "frames": frames}
        if names:
            msg["names"] = names
        await self._send(msg)


class LipsyncTurn:
    """Per-reply fan-out of TTS sentences into A2F clips.

    One instance per WebSocket turn. Nothing here blocks the reply path: every A2F
    round trip runs in a background task.

    Each sentence goes through two calls:

      ``open_clip()``  reserves a clip id and opens its A2F stream *now*, so
                       silence priming (§7/§15.2) runs while TTS is still
                       synthesizing — that's the gap priming exists to cover,
                       and it keeps the NIM from paying its 2-3s cold start on
                       the first real audio.
      ``feed()``       hands over the synthesized audio; ``cancel()`` instead
                       if that sentence produced none.
    """

    def __init__(self, client: A2FClient, send: Send, turn_id: str) -> None:
        self._client = client
        self._send = send
        self._turn_id = turn_id
        # Shared across turns: the NIM's slot count is global, so a per-turn
        # semaphore let an overlapping turn (a second page, a chat reply, an
        # interruption still draining) open a stream the NIM had no slot for.
        self._slots = _SLOTS
        self._tasks: list[asyncio.Task] = []
        self._audio: dict[str, asyncio.Future] = {}
        self._sessions: set = set()
        self._clip_n = 0
        # Two consecutive failures to open a stream disable A2F for this turn —
        # a down NIM shouldn't cost every sentence a 4s timeout.
        self._failed_opens = 0
        self._disabled = False

    @property
    def enabled(self) -> bool:
        return not self._disabled

    def open_clip(self) -> str | None:
        """Reserve a clip and start its A2F stream. Returns the id for the
        browser to tag this sentence's audio with, or None when A2F is off."""
        if self._disabled:
            return None
        self._clip_n += 1
        uid = f"{self._turn_id}c{self._clip_n}"
        self._audio[uid] = asyncio.get_running_loop().create_future()
        self._tasks.append(asyncio.create_task(self._run_clip(uid)))
        return uid

    def feed(self, uid: str, audio: bytes, mime: str) -> None:
        """Hand a clip the exact audio bytes the user is about to hear."""
        fut = self._audio.get(uid)
        if fut is not None and not fut.done():
            fut.set_result((audio, mime))

    def cancel(self, uid: str) -> None:
        """That sentence produced no audio — release the clip."""
        fut = self._audio.get(uid)
        if fut is not None and not fut.done():
            fut.set_result(None)

    async def _run_clip(self, uid: str) -> None:
        await self._slots.acquire()
        session = None
        try:
            if self._disabled:
                return
            publisher = _Publisher(self._send, uid)
            try:
                session = await asyncio.wait_for(
                    self._client.open_stream(
                        sample_rate=A2F_SAMPLE_RATE, on_batch=publisher.publish
                    ),
                    timeout=_OPEN_TIMEOUT_S,
                )
            except Exception as exc:
                self._failed_opens += 1
                if self._failed_opens >= 2:
                    self._disabled = True
                logger.warning("A2F clip open failed (strike %d): %s", self._failed_opens, exc)
                return
            self._failed_opens = 0
            self._sessions.add(session)

            # Keep the stream warm while TTS synthesizes this sentence.
            session.start_priming()

            fed = await asyncio.wait_for(self._audio[uid], timeout=_AUDIO_WAIT_S)
            if not fed:
                await session.abort()
                return
            audio, mime = fed
            try:
                pcm = await asyncio.to_thread(decode_to_pcm16_16k, audio, mime)
            except Exception as exc:
                logger.warning("A2F: could not decode TTS audio (%s): %s", mime, exc)
                await session.abort()
                return
            if not pcm:
                await session.abort()
                return

            # The clip's true audio length — everything the NIM emits past it is
            # its ~1.5s of appended trailing silence (§10).
            publisher.clip_secs = len(pcm) / 2 / A2F_SAMPLE_RATE
            await session.write(pcm)
            try:
                frames = await asyncio.wait_for(session.finish(), timeout=_CLIP_TIMEOUT_S)
            except RuntimeError as exc:
                # The NIM can free the previous clip's slot later than our semaphore
                # does. One retry covers that race without masking a down NIM.
                if "No available stream" not in str(exc):
                    raise
                logger.warning("A2F clip %s: no stream slot yet, retrying once: %s", uid, exc)
                await session.abort()
                self._sessions.discard(session)
                await asyncio.sleep(0.3)
                session = await asyncio.wait_for(
                    self._client.open_stream(sample_rate=A2F_SAMPLE_RATE, on_batch=publisher.publish),
                    timeout=_OPEN_TIMEOUT_S,
                )
                self._sessions.add(session)
                await session.write(pcm)
                frames = await asyncio.wait_for(session.finish(), timeout=_CLIP_TIMEOUT_S)
            logger.info(
                "A2F clip %s: %d frames for %.2fs of audio", uid, frames, publisher.clip_secs
            )
        except asyncio.CancelledError:
            if session is not None:
                await session.abort()
            raise
        except Exception as exc:
            logger.warning("A2F clip %s failed: %s", uid, exc)
            if session is not None:
                try:
                    await session.abort()
                except Exception:
                    pass
        finally:
            self._sessions.discard(session)
            self._audio.pop(uid, None)
            self._slots.release()

    async def drain(self, timeout: float = _CLIP_TIMEOUT_S) -> None:
        """Wait for in-flight clips so their frames land before the socket closes."""
        if not self._tasks:
            return
        pending = [t for t in self._tasks if not t.done()]
        if pending:
            _, still = await asyncio.wait(pending, timeout=timeout)
            for task in still:
                task.cancel()
        self._tasks.clear()

    async def abort(self) -> None:
        """User interrupted / socket died — drop everything in flight."""
        self._disabled = True
        for task in self._tasks:
            if not task.done():
                task.cancel()
        for session in list(self._sessions):
            try:
                await session.abort()
            except Exception:
                pass
        self._sessions.clear()
        self._tasks.clear()
