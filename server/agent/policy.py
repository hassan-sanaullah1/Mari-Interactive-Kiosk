"""What the kiosk says when it is not going to ask the LLM.

The kiosk must always speak. Three things can stand in for a real answer, and they are
checked in this order:

    1. the pitch line, while MARI_PITCH_ONLY is on (a recording aid)
    2. the demo line, when no LLM is configured
    3. the demo line again, when the LLM was configured but failed

This decision used to be written out at each call site, which is how ``/chat`` and the
streaming path drifted into disagreeing about when a reply counts as a demo.
"""

from __future__ import annotations

from dataclasses import dataclass

from .. import config
from .replies import canned, pitch_override


@dataclass(frozen=True, slots=True)
class Fallback:
    """A reply to speak instead of asking the LLM."""

    text: str
    # True when the visitor is hearing a stand-in rather than a real answer. The
    # browser shows it unchanged either way; this is for the caller's own reporting.
    is_demo: bool


def fallback_reply(lang: str, avatar: str | None = None) -> Fallback | None:
    """The stand-in for this turn, or None to go ahead and ask the LLM."""
    if (pitch := pitch_override(lang, avatar)) is not None:
        # A fixed pitch is a real, intended answer, not a degraded one.
        return Fallback(pitch, is_demo=False)
    if not config.llm_ready():
        return Fallback(canned("demo", lang, avatar), is_demo=True)
    return None


def failure_reply(lang: str, avatar: str | None = None) -> Fallback:
    """The stand-in after the LLM was asked and did not answer."""
    return Fallback(canned("demo", lang, avatar), is_demo=True)
