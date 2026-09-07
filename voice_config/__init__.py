"""Voice/language configuration for the MARI kiosk — everything that shapes what the
avatar *says*, kept out of the pipeline code that decides *when* it says it.

    prompts/*.md         persona, rules and greetings, per language
    addresses.py         addresses, contact details, formulae and symbol abbreviations
    glossary.py          ABBR → full-form pairs mined from the knowledge base
    names.py             spoken forms for people's names, ranks and honours
    urdu_normalise.py    spoken-form fixes for what the Uplift voice mispronounces

The prompt files hold exactly the text that previously lived as string literals in
``server/knowledge.py``; that module now loads them through :func:`load_prompt` and
falls back to its own copy if a file is missing, so a bad edit here degrades to the old
behaviour instead of breaking the kiosk.
"""

from __future__ import annotations

from pathlib import Path

from .addresses import spoken_addresses
from .glossary import extract_glossary, find_glossary_matches, format_glossary_block
from .names import spoken_names_and_ranks
from .urdu_normalise import normalise_for_uplift, spoken_urls

PROMPT_DIR = Path(__file__).resolve().parent / "prompts"

__all__ = [
    "PROMPT_DIR",
    "load_prompt",
    "extract_glossary",
    "find_glossary_matches",
    "format_glossary_block",
    "normalise_for_uplift",
    "spoken_names_and_ranks",
    "spoken_urls",
    "spoken_addresses",
]


def load_prompt(name: str) -> str | None:
    """Read ``prompts/<name>.md``, or None if it is missing or unreadable.

    Returning None rather than raising is deliberate: every caller has a working
    in-code fallback, and a kiosk that keeps answering with a slightly stale prompt is
    better than one that fails to start because a file was renamed.
    """
    path = PROMPT_DIR / f"{name}.md"
    try:
        text = path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError):
        return None
    return text or None
