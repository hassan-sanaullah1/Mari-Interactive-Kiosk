"""NVIDIA Audio2Face-3D client — audio in, ARKit blendshape keyframes out.

Ported (near-verbatim) from the working implementation described in
``THREEJS_A2F_INTEGRATION.md`` §6–§8. Talks to an Audio2Face-3D NIM over gRPC
(default port 52000) using the ``nvidia_ace`` protos.

One ``ProcessAudioStream`` call per CLIP. The NIM's contract is
clip-in / burst-out: it emits nothing until ``end_of_audio``, then drains the
whole clip's frames at once. Callers keep clips short (one TTS sentence) and
``finish()`` as soon as that sentence's audio is complete.

Endpoint forms (``APP_A2F_URL``):
  host:port              plaintext gRPC — NIM on the same network/tunnel
  grpc://host:port       same, explicit
  grpcs://host[:port]    TLS (port defaults to 443). Pair with APP_A2F_API_KEY
                         (sent as ``authorization`` metadata) and optionally
                         APP_A2F_TLS_CA for a private CA.

The ``nvidia_ace`` import is guarded: without the wheel this module reports
``AVAILABLE = False`` and the rest of the app runs unchanged, minus lipsync.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable

import numpy as np

logger = logging.getLogger(__name__)

try:  # nvidia-ace wheel / grpcio not installed → lipsync degrades to "off"
    import grpc
    from nvidia_ace.a2f.v1_pb2 import AudioWithEmotion
    from nvidia_ace.audio.v1_pb2 import AudioHeader
    from nvidia_ace.controller.v1_pb2 import AudioStream, AudioStreamHeader
    from nvidia_ace.services.a2f_controller.v1_pb2_grpc import A2FControllerServiceStub

    AVAILABLE = True
    IMPORT_ERROR = ""
except ImportError as exc:  # pragma: no cover - depends on the deployment
    grpc = None  # type: ignore[assignment]
    AVAILABLE = False
    IMPORT_ERROR = str(exc)
    logger.warning("A2F client unavailable: %s", exc)


A2F_SAMPLE_RATE = 16000

# Frames per published batch: 3 ≈ 100ms at the NIM's 30fps — the lipsync
# latency granularity. The FIRST frame ships alone so lips engage the moment
# A2F produces anything.
_BATCH_FRAMES = 3
_FIRST_BATCH_FRAMES = 1

# (names, frames) — frames are [t, w0, ..., wN]; names sent on the first batch only.
OnBatch = Callable[["list[str] | None", "list[list[float]]"], Awaitable[None]]


def _resample_to_16k(pcm16: bytes, from_rate: int) -> np.ndarray:
    """Linear-interpolation resample to 16 kHz — adequate for lipsync."""
    audio = np.frombuffer(pcm16, dtype=np.int16)
    if from_rate == A2F_SAMPLE_RATE:
        return audio
    n_out = int(len(audio) * A2F_SAMPLE_RATE / from_rate)
    x_out = np.linspace(0, len(audio) - 1, n_out)
    return np.interp(x_out, np.arange(len(audio)), audio.astype(np.float32)).astype(np.int16)


class A2FStreamSession:
    """One clip: write audio as it becomes available, frames stream back.

    Supports silence priming — the NIM needs ~2-3s of audio context before its
    first frame on a fresh stream. Priming feeds paced silence while the clip's
    audio is still being fetched, so the warm-up happens before real audio
    exists; the silence duration is then subtracted from every emitted time code
    (and the neutral silence-era frames dropped), keeping the timeline
    speech-relative.
    """

    def __init__(self, sample_rate: int, on_batch: OnBatch, metadata: tuple | None = None) -> None:
        self._in_rate = sample_rate
        self._on_batch = on_batch
        self._metadata = metadata
        self._stream = None
        self._read_task: asyncio.Task | None = None
        self._prime_task: asyncio.Task | None = None
        self._writer_task: asyncio.Task | None = None
        self._write_queue: asyncio.Queue = asyncio.Queue()
        self._silence_secs = 0.0
        self._real_audio = asyncio.Event()
        self._t_start = 0.0
        self.frames_total = 0

    async def start(self, channel) -> None:
        # Streams multiplex over the client's ONE persistent channel — a new
        # channel per sentence would pay connection setup every time.
        stub = A2FControllerServiceStub(channel)
        self._stream = stub.ProcessAudioStream(metadata=self._metadata)
        self._t_start = time.monotonic()
        await self._stream.write(
            AudioStream(
                audio_stream_header=AudioStreamHeader(
                    audio_header=AudioHeader(
                        samples_per_second=A2F_SAMPLE_RATE,
                        bits_per_sample=16,
                        channel_count=1,
                        audio_format=AudioHeader.AUDIO_FORMAT_PCM,
                    ),
                )
            )
        )
        self._read_task = asyncio.create_task(self._read_loop())

    def start_priming(self) -> None:
        """Feed paced silence until real audio arrives (call right after start)."""
        if self._prime_task is None:
            self._prime_task = asyncio.create_task(self._prime_loop())

    async def _prime_loop(self) -> None:
        chunk = b"\x00\x00" * (A2F_SAMPLE_RATE // 10)  # 100ms of 16k mono silence
        try:
            while not self._real_audio.is_set():
                await self._stream.write(
                    AudioStream(audio_with_emotion=AudioWithEmotion(audio_buffer=chunk))
                )
                self._silence_secs += 0.1
                await asyncio.sleep(0.1)
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.debug("A2F priming stopped: %s", exc)

    async def write(self, pcm16: bytes) -> None:
        """Enqueue speech audio — never blocks the caller.

        Actual gRPC writes happen in a paced writer task; see _paced_writer.
        """
        if not self._real_audio.is_set():
            self._real_audio.set()
            if self._prime_task is not None:
                await asyncio.wait([self._prime_task])
            logger.info(
                "A2F first speech audio written (+%.2fs after stream open, %.1fs silence primed)",
                time.monotonic() - self._t_start,
                self._silence_secs,
            )
            self._writer_task = asyncio.create_task(self._paced_writer())
        self._write_queue.put_nowait(_resample_to_16k(pcm16, self._in_rate))

    # Max samples per gRPC message: 1s. The NIM rejects buffers >10s, and 1s
    # keeps messages small enough to interleave with the returning frames.
    _WRITE_CHUNK_SAMPLES = A2F_SAMPLE_RATE

    async def _paced_writer(self) -> None:
        # Coalescing writer: one gRPC write per small audio frame drowns the
        # event loop and makes time-to-first-frame scale with reply length.
        # Draining the queue into ~1s chunks cuts writes by ~100x.
        try:
            done = False
            while not done:
                buf = [await self._write_queue.get()]
                if buf[0] is None:
                    return
                while True:
                    try:
                        nxt = self._write_queue.get_nowait()
                    except asyncio.QueueEmpty:
                        break
                    if nxt is None:
                        done = True
                        break
                    buf.append(nxt)
                data = np.concatenate(buf)
                for i in range(0, len(data), self._WRITE_CHUNK_SAMPLES):
                    chunk = data[i : i + self._WRITE_CHUNK_SAMPLES]
                    await self._stream.write(
                        AudioStream(
                            audio_with_emotion=AudioWithEmotion(audio_buffer=chunk.tobytes())
                        )
                    )
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.warning("A2F writer failed: %s", exc)

    async def finish(self) -> int:
        """Flush queued audio, signal end of clip, drain remaining frames.

        The shared channel stays open for the next clip's stream.
        """
        self._real_audio.set()
        if self._prime_task is not None:
            await asyncio.wait([self._prime_task])
        if self._writer_task is not None:
            self._write_queue.put_nowait(None)  # sentinel: writer exits after the queue
            await asyncio.wait([self._writer_task])
        await self._stream.write(AudioStream(end_of_audio=AudioStream.EndOfAudio()))
        await self._read_task
        return self.frames_total

    async def abort(self) -> None:
        """Tear down mid-clip (interruption). Keeps the shared channel."""
        self._real_audio.set()
        for task in (self._prime_task, self._writer_task, self._read_task):
            if task is not None and not task.done():
                task.cancel()
        if self._stream is not None:
            self._stream.cancel()

    async def _read_loop(self) -> None:
        names_sent = False
        batch: list[list[float]] = []
        batch_limit = _FIRST_BATCH_FRAMES

        async def flush(names: list[str] | None = None) -> None:
            nonlocal names_sent, batch, batch_limit
            if not batch and names_sent:
                return
            await self._on_batch(None if names_sent else names, batch)
            names_sent = True
            batch_limit = _BATCH_FRAMES
            self.frames_total += len(batch)
            batch = []

        header_names: list[str] | None = None
        while True:
            message = await self._stream.read()
            if message == grpc.aio.EOF:
                break
            if message.HasField("animation_data_stream_header"):
                header = message.animation_data_stream_header
                header_names = list(header.skel_animation_header.blend_shapes)
                # Publish names immediately (empty frames) — this "arms" the
                # frontend clip before any weight data arrives.
                await flush(header_names)
            elif message.HasField("animation_data"):
                for bs in message.animation_data.skel_animation.blend_shape_weights:
                    # Shift time codes back by the priming silence and drop the
                    # neutral silence-era frames entirely.
                    t = bs.time_code - self._silence_secs
                    if t < -0.05:
                        continue
                    # 3-decimal weights keep payloads ~3x smaller; sub-0.001
                    # morph deltas are not visible on the avatar.
                    batch.append([round(max(t, 0.0), 3), *(round(v, 3) for v in bs.values)])
                if len(batch) >= batch_limit:
                    await flush(header_names)
            elif message.HasField("status"):
                if message.status.code == 3:  # ERROR
                    raise RuntimeError(f"A2F error: {message.status.message}")
        await flush(header_names)


class A2FClient:
    """Factory for per-clip A2F streaming sessions over one shared channel."""

    def __init__(self, target: str, api_key: str = "", tls_ca_file: str = "") -> None:
        # grpcs:// = TLS (production edge proxy); grpc:// or bare = plaintext.
        self._secure = target.startswith("grpcs://")
        authority = target.split("://", 1)[1] if "://" in target else target
        if self._secure and ":" not in authority:
            authority += ":443"
        self._target = authority
        self._tls_ca_file = tls_ca_file
        self._metadata: tuple | None = (
            (("authorization", f"Bearer {api_key}"),) if api_key else None
        )
        self._channel = None

    def _get_channel(self):
        if self._channel is None:
            options = [
                # Keep the connection alive between utterances.
                ("grpc.keepalive_time_ms", 30000),
                ("grpc.keepalive_timeout_ms", 10000),
                ("grpc.keepalive_permit_without_calls", 1),
            ]
            if self._secure:
                root_certs = None
                if self._tls_ca_file:
                    with open(self._tls_ca_file, "rb") as f:
                        root_certs = f.read()
                self._channel = grpc.aio.secure_channel(
                    self._target,
                    grpc.ssl_channel_credentials(root_certificates=root_certs),
                    options=options,
                )
            else:
                self._channel = grpc.aio.insecure_channel(self._target, options=options)
        return self._channel

    async def warmup(self) -> None:
        """Dial the channel ahead of the first utterance (fire at startup)."""
        try:
            await asyncio.wait_for(self._get_channel().channel_ready(), timeout=15)
            logger.info("A2F channel warmed up (%s)", self._target)
        except Exception as exc:
            logger.warning("A2F channel warmup failed: %s", exc)

    async def open_stream(self, sample_rate: int, on_batch: OnBatch) -> A2FStreamSession:
        session = A2FStreamSession(sample_rate, on_batch, metadata=self._metadata)
        try:
            await session.start(self._get_channel())
        except Exception:
            # A broken channel should not poison future utterances — reset so
            # the next open dials fresh.
            if self._channel is not None:
                ch, self._channel = self._channel, None
                try:
                    await ch.close()
                except Exception:
                    pass
            raise
        return session

    async def close(self) -> None:
        if self._channel is not None:
            ch, self._channel = self._channel, None
            try:
                await ch.close()
            except Exception:
                pass

    async def process_utterance(
        self, pcm16: bytes, sample_rate: int
    ) -> tuple[list[str], list[list[float]]]:
        """Batch helper (used by the smoke test): whole utterance in, frames out."""
        all_names: list[str] = []
        all_frames: list[list[float]] = []

        async def collect(names: list[str] | None, frames: list[list[float]]) -> None:
            if names:
                all_names.extend(names)
            all_frames.extend(frames)

        session = await self.open_stream(sample_rate, collect)
        await session.write(pcm16)
        await session.finish()
        return all_names, all_frames
