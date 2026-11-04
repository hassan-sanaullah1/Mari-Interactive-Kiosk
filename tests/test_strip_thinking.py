"""Strip <think> reasoning blocks that Qwen 3.5 sometimes leaks into replies."""

from __future__ import annotations

import pytest

from server.agent.reply_fixes import strip_thinking
from server.agent.responder import _strip_think_stream


@pytest.mark.parametrize(
    "raw,expected",
    [
        # clean reply, no change
        ("Mari Gas Field was discovered in 1957.", "Mari Gas Field was discovered in 1957."),
        # complete think block before the reply
        (
            "<think>I should talk about gas.</think>Mari Gas Field is in Sindh.",
            "Mari Gas Field is in Sindh.",
        ),
        # think block with markdown and newlines inside
        (
            "<think>\n1. **Analyze** the question.\n2. Stay on topic.\n</think>\nHello!",
            "Hello!",
        ),
        # dangling open tag (stream cut off)
        (
            "Hello! <think>This is reasoning that never closes",
            "Hello!",
        ),
        # no think tags at all
        ("السلام علیکم", "السلام علیکم"),
        # empty reply
        ("", ""),
        # think block is the entire reply
        ("<think>reasoning only</think>", ""),
    ],
)
def test_strip_thinking(raw: str, expected: str) -> None:
    assert strip_thinking(raw) == expected


class TestStripThinkStream:
    """The streaming variant tracks state across calls."""

    def test_complete_block_in_one_chunk(self) -> None:
        buf, inside = _strip_think_stream(
            "Start. <think>hidden</think>End.", False
        )
        assert buf == "Start. End."
        assert not inside

    def test_block_split_across_chunks(self) -> None:
        buf1, inside = _strip_think_stream("Hello <think>start of", False)
        assert buf1 == "Hello "
        assert inside

        buf2, inside = _strip_think_stream(" reasoning</think> world.", inside)
        assert buf2 == " world."
        assert not inside

    def test_no_tags(self) -> None:
        buf, inside = _strip_think_stream("plain text", False)
        assert buf == "plain text"
        assert not inside

    def test_dangling_open(self) -> None:
        buf, inside = _strip_think_stream("text <think>reasoning...", False)
        assert buf == "text "
        assert inside
