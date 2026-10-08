"""Guards the turn's pipelining, which no snapshot can see.

A reply is spoken sentence by sentence, and each sentence's TTS starts as soon as the
responder yields it — so sentence N+1 renders while N is still being sent and the LLM
is still streaming. Nothing about the frames on the wire shows that: a refactor that
quietly made synthesis serial would pass every other test and simply be slower, which
is the regression the kiosk can least afford.

The checks here are about ORDER and OVERLAP, counted exactly, with wall-clock timing
only as a second-line guard (margins are wide, so a loaded CI box does not fail it).
"""

from __future__ import annotations

import asyncio
import time

import pytest

from server.agent import speech
from server.agent import turn as turn_module
from server.agent.turn import run_reply

# Five sentences, so a serial run is clearly separable from a pipelined one.
SENTENCES = [
    "First sentence here.",
    "Second sentence here.",
    "Third sentence here.",
    "Fourth sentence here.",
    "Fifth sentence here.",
]
REPLY = " ".join(SENTENCES)

# Per-stage fake cost. Long enough to dominate scheduling noise, short enough that
# the whole module runs in about a second.
#
# TTS is the slower stage, as in production: Uplift takes several hundred ms for a
# sentence while the LLM yields one every couple of hundred. That ordering is what
# makes synthesis overlap at all — with the two equal, each sentence's audio is
# ready exactly as the next is yielded and nothing ever runs in parallel.
LLM_SENTENCE_DELAY = 0.04
TTS_DELAY = 0.08


class RecordingSock:
    """Records what was sent and when, relative to the turn's start."""

    def __init__(self) -> None:
        self.events: list[tuple[float, str]] = []
        self._t0 = time.perf_counter()

    def _mark(self, label: str) -> None:
        self.events.append((time.perf_counter() - self._t0, label))

    async def send_json(self, payload: dict) -> None:
        kind = payload.get("type", "?")
        detail = payload.get("text", "") if kind == "reply" else ""
        self._mark(f"{kind}:{detail}".rstrip(":"))

    async def send_bytes(self, data: bytes) -> None:
        self._mark("audio")

    def labels(self) -> list[str]:
        return [label for _, label in self.events]

    def at(self, label: str) -> float:
        for when, seen in self.events:
            if seen == label:
                return when
        raise AssertionError(f"{label} never sent; got {self.labels()}")


class TTSProbe:
    """A fake TTS that reports how many calls were ever in flight at once."""

    def __init__(self, delay: float = TTS_DELAY) -> None:
        self.delay = delay
        self.in_flight = 0
        self.max_in_flight = 0
        self.started: list[str] = []
        self.finished: list[str] = []

    async def speak(self, text: str, lang: str, avatar_id: str = "female"):
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        self.started.append(text)
        try:
            await asyncio.sleep(self.delay)
        finally:
            self.in_flight -= 1
        self.finished.append(text)
        return b"RIFFfake", "audio/wav"


@pytest.fixture
def pipeline(monkeypatch):
    """A turn whose LLM and TTS are faked with fixed, measurable costs."""
    from server import avatar
    from server import config as settings

    async def fake_respond_sentences(transcript, lang, history, avatar_id):
        for sentence in SENTENCES:
            await asyncio.sleep(LLM_SENTENCE_DELAY)
            yield sentence, False

    monkeypatch.setattr(turn_module, "respond_sentences", fake_respond_sentences)
    monkeypatch.setattr(settings, "FORCE_DEMO", False)
    # tts_ready gates whether synthesis is attempted at all.
    monkeypatch.setattr(settings, "UPLIFT_KEY", "u")
    monkeypatch.setattr(settings, "EN_TTS", "uplift")
    monkeypatch.setattr(avatar, "_client", None)
    monkeypatch.setattr(avatar, "_resolved", True)

    probe = TTSProbe()
    monkeypatch.setattr(speech, "speak", probe.speak)
    monkeypatch.setattr(turn_module.speech, "speak", probe.speak)
    return probe


def _run(sock) -> None:
    asyncio.run(run_reply(sock, "a question", "en", avatar_id="female"))


def test_synthesis_overlaps_sending(pipeline) -> None:
    """Synthesis must run ahead: more than one sentence in flight at a time."""
    sock = RecordingSock()
    _run(sock)

    assert pipeline.started == SENTENCES, "every sentence must be synthesized once, in order"
    assert pipeline.max_in_flight > 1, (
        "TTS never overlapped — synthesis has become serial, which costs the visitor "
        f"one TTS round trip per sentence (max in flight was {pipeline.max_in_flight})"
    )


def test_lookahead_is_bounded(pipeline) -> None:
    """...but not unboundedly: an interrupted turn must not waste TTS calls."""
    sock = RecordingSock()
    _run(sock)

    assert pipeline.max_in_flight <= turn_module._LOOKAHEAD, (
        f"more than _LOOKAHEAD ({turn_module._LOOKAHEAD}) sentences were synthesized at "
        f"once ({pipeline.max_in_flight}); an interrupted turn wastes that many calls"
    )


def test_next_sentence_starts_before_previous_audio_is_sent(pipeline) -> None:
    """The ordering that makes the overlap useful, asserted directly."""
    sock = RecordingSock()
    _run(sock)

    first_audio = sock.at("audio")
    # By the time the first audio frame goes out, the second sentence's TTS must
    # already have been started, or each sentence pays full synthesis latency.
    second_started_by_then = SENTENCES[1] in pipeline.started[:2]
    assert second_started_by_then, (
        f"sentence 2 had not started synthesizing when sentence 1's audio was sent "
        f"at {first_audio * 1000:.0f} ms; started order was {pipeline.started}"
    )


def test_frames_stay_in_order(pipeline) -> None:
    """Pipelining must not reorder what the browser receives."""
    sock = RecordingSock()
    _run(sock)

    expected = ["stt"]
    for sentence in SENTENCES:
        expected += [f"reply:{sentence}", "tts", "audio"]
    expected += ["done"]
    assert sock.labels() == expected


def test_first_audio_does_not_wait_for_the_whole_reply(pipeline) -> None:
    """Time to first audio must not scale with the number of sentences.

    Wide margin on purpose: this is a backstop for the exact checks above, not a
    benchmark. Serial synthesis of four sentences would land near
    4 x (LLM + TTS); one sentence's worth is the target.
    """
    sock = RecordingSock()
    _run(sock)

    first_audio = sock.at("audio")
    serial_budget = len(SENTENCES) * (LLM_SENTENCE_DELAY + TTS_DELAY)
    assert first_audio < serial_budget / 2, (
        f"first audio took {first_audio * 1000:.0f} ms; a pipelined turn should speak "
        f"after roughly one sentence ({(LLM_SENTENCE_DELAY + TTS_DELAY) * 1000:.0f} ms), "
        f"not after most of the reply"
    )


def test_total_turn_beats_serial_synthesis(pipeline) -> None:
    """The whole turn must gain from the overlap, not just the first sentence."""
    sock = RecordingSock()
    started = time.perf_counter()
    _run(sock)
    total = time.perf_counter() - started

    serial_budget = len(SENTENCES) * (LLM_SENTENCE_DELAY + TTS_DELAY)
    assert total < serial_budget * 0.85, (
        f"turn took {total * 1000:.0f} ms against a serial cost of "
        f"{serial_budget * 1000:.0f} ms — the pipelining has stopped paying off"
    )
