"""An empty transcript has two very different causes, and only one wants an answer.

The kiosk runs hands-free: every reply re-opens the mic. So a turn can end with an
empty transcript because the visitor spoke and STT lost it, or simply because nobody
was there. Answering the second case made the kiosk apologise to an empty room, which
re-opened the mic, which timed out again — an apology every eight seconds, forever.

The browser's VAD already knows which happened; ``spoke`` carries that to the server.
"""

from __future__ import annotations

import asyncio

import pytest

from server import app as A


class _Sock:
    """Records what run_reply sends, standing in for the WebSocket."""

    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send_json(self, payload: dict) -> None:
        self.sent.append(payload)

    async def send_bytes(self, data: bytes) -> None:
        self.sent.append({"type": "_bytes", "len": len(data)})


def _run(spoke: bool, lang: str = "ur") -> list[dict]:
    sock = _Sock()
    asyncio.run(A.run_reply(sock, "", lang, echo_transcript=True, spoke=spoke))
    return sock.sent


def test_a_silent_turn_says_nothing_at_all() -> None:
    """Nobody spoke: the turn closes out quietly, as it did before the apology
    existed. This is the hands-free loop idling, not a failure."""
    sent = _run(spoke=False)
    assert not [m for m in sent if m.get("type") == "reply"]
    assert sent[-1] == {"type": "done", "spoken": False}


@pytest.mark.parametrize("lang", ["ur", "en"])
def test_a_lost_transcript_is_apologised_for(lang: str) -> None:
    """They did speak and STT came back empty — that is worth saying out loud,
    or the kiosk looks broken to someone standing in front of it."""
    replies = [m for m in _run(spoke=True, lang=lang) if m.get("type") == "reply"]
    assert len(replies) == 1
    assert replies[0]["demo"] is True
    assert replies[0]["text"] == A.NO_SPEECH_REPLY["female"][lang]


def test_the_apology_is_the_default_for_an_older_browser() -> None:
    """A client that sends a bare {"end"} with no ``spoke`` keeps the behaviour it
    had rather than falling silent — the flag defaults to True server-side."""
    sock = _Sock()
    asyncio.run(A.run_reply(sock, "", "ur", echo_transcript=True))
    assert [m for m in sock.sent if m.get("type") == "reply"]


def test_the_male_presenter_apologises_in_his_own_gender() -> None:
    """The Urdu verb carries the speaker's gender, and this line bypasses the LLM,
    so it has to be picked per persona rather than left to the agreement pass."""
    sock = _Sock()
    asyncio.run(A.run_reply(sock, "", "ur", avatar_id="male", spoke=True))
    said = [m for m in sock.sent if m.get("type") == "reply"][0]["text"]
    assert "سکا" in said and "سکی" not in said
