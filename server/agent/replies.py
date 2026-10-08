"""Fixed lines spoken without the LLM (server/prompts/replies.toml)."""

from __future__ import annotations

from .. import config
from ..personas import default_persona, get_persona
from ..prompts import get_prompts


def canned(name: str, lang: str, avatar: str | None = None) -> str:
    """A line for the presenter and language, falling back to the default / English.

    Keyed by presenter because the Urdu verb carries the speaker's gender, and these
    lines never pass through the gender agreement fix.
    """
    table = get_prompts().replies[name]
    lines_by_lang = table.get(get_persona(avatar).id) or table[default_persona().id]
    return lines_by_lang.get(lang) or lines_by_lang["en"]


def pitch_override(lang: str, avatar: str | None = None) -> str | None:
    """The presenter's fixed pitch line while MARI_PITCH_ONLY is on.

    None for a presenter with no pitch line rather than falling back to the female one,
    which names Maryam and carries the feminine Urdu verb.
    """
    if not config.pitch_only():
        return None
    lines_by_lang = get_prompts().replies["pitch"].get(get_persona(avatar).id)
    return lines_by_lang.get(lang) if lines_by_lang else None
