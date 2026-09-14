"""Fixed lines spoken without the LLM (server/prompts/replies.toml)."""

from __future__ import annotations

from .. import config as C
from ..prompts import get_prompts


def canned(name: str, lang: str, avatar: str = "female") -> str:
    """A line for the presenter and language, falling back to female / English.

    Keyed by presenter because the Urdu verb carries the speaker's gender, and these
    lines never pass through the gender agreement fix.
    """
    table = get_prompts().replies[name]
    persona = table.get(avatar) or table["female"]
    return persona.get(lang) or persona["en"]


def pitch_override(lang: str, avatar: str) -> str | None:
    """The fixed pitch line while MARI_PITCH_ONLY is on, for the female rig only."""
    if not C.pitch_only():
        return None
    if avatar == "female":
        return get_prompts().replies["pitch"]["female"].get(lang)
    return None
