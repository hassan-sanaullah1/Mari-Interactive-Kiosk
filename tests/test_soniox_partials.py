"""The Soniox streaming transcript must survive a message that carries no tokens.

The kiosk's symptom was: the visitor speaks, sees their words appear as live
captions, and then gets silence — no reply at all. The captions come from the
partial stream, but the reply is driven by what ``finish()`` returns, and those
two had drifted apart: any message with no usable tokens blanked the standing
partial, so an utterance that had not finalized yet came back as "".

An empty transcript is not a small loss — ``run_reply`` answers it with
``{done, spoken:false}`` without ever calling the LLM, so the whole turn is gone.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from server.providers.stt import SonioxStream


class _FakeWS:
    """Stands in for the Soniox websocket: replays a scripted message list."""

    def __init__(self, messages: list[dict]) -> None:
        self._messages = [json.dumps(m) for m in messages]
        self.sent: list = []

    def __aiter__(self):
        async def gen():
            for m in self._messages:
                yield m
        return gen()

    async def send(self, data) -> None:
        self.sent.append(data)

    async def close(self) -> None:
        pass


def _partial(text: str) -> dict:
    return {"tokens": [{"text": text, "is_final": False}]}


def _final(text: str) -> dict:
    return {"tokens": [{"text": text, "is_final": True}]}


async def _transcript(messages: list[dict]) -> str:
    stream = SonioxStream(lang="ur")
    stream.ws = _FakeWS(messages)
    await stream._read()
    return await stream.finish(grace=0)


@pytest.mark.parametrize("tail", [
    pytest.param({"tokens": []}, id="keepalive-with-no-tokens"),
    pytest.param({"tokens": [{"text": "<end>", "is_final": False}]}, id="filtered-marker-only"),
    pytest.param({}, id="message-with-no-tokens-key"),
])
def test_a_tokenless_message_does_not_erase_the_partial(tail: dict) -> None:
    """The bug: these arrive after the speech and blanked ``last_partial``, so the
    turn that the visitor had just watched appear on screen was thrown away."""
    said = asyncio.run(_transcript([_partial("السلام"), _partial("السلام علیکم"), tail]))
    assert said == "السلام علیکم"


def test_finalized_tokens_still_replace_the_partial() -> None:
    """The normal path must be unchanged: once Soniox finalizes a span, the partial
    that was standing in for it is dropped rather than repeated."""
    said = asyncio.run(_transcript([
        _partial("السلام علیکم"),
        _final("السلام علیکم"),
        _partial(" ماری"),
        _final(" ماری انرجیز"),
    ]))
    assert said == "السلام علیکم ماری انرجیز"


def test_a_turn_that_really_was_silent_still_comes_back_empty() -> None:
    """The fix must not invent text. Silence has to stay empty, so the reply path
    can speak its "I didn't catch that" line."""
    assert asyncio.run(_transcript([{"tokens": []}])) == ""


def test_partial_is_kept_when_finals_never_arrive() -> None:
    """The case finish()'s grace is built around: the utterance is only ever a
    partial, because Soniox emits its finals ~1s after end-of-audio. That text is
    the turn, and it has to survive."""
    said = asyncio.run(_transcript([_partial("ماری انرجیز کے ورٹیکلز")]))
    assert said == "ماری انرجیز کے ورٹیکلز"
