"""Retrieval coverage for the knowledge base.

Guards the failure that prompted these tests: a question whose terms the expander
did not recognise silently retrieved the wrong sections, and the model then said it
had no information about something the knowledge base plainly covered.

Run: python -m pytest tests/ -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server import knowledge as K  # noqa: E402
from tests.retrieval_cases import CASES  # noqa: E402


def _matches(title: str, want: str) -> bool:
    return title.startswith(want) or f"› {want}" in title


@pytest.mark.parametrize("query,want", CASES)
def test_urdu_question_reaches_its_section(query: str, want: str) -> None:
    """Every Urdu question a visitor might ask lands on the section that answers it."""
    hits = K.search(query, 4)
    assert hits, f"no retrieval at all for {query!r}"
    assert any(_matches(h.title, want) for h in hits), (
        f"{query!r} wanted {want}, got {[h.title for h in hits]} "
        f"(expanded to {K._expand(query)})"
    )


@pytest.mark.parametrize("chunk", K.CHUNKS, ids=lambda c: c.title[:60])
def test_section_is_reachable_by_its_own_heading(chunk: K.Chunk) -> None:
    """No section is orphaned: its own heading must retrieve it."""
    lead = chunk.title.split(" › ")[-1]
    assert chunk.title in [h.title for h in K.search(lead, 3)]


def test_no_multiword_glossary_keys() -> None:
    """GLOSSARY is matched word by word, so a spaced key would never fire."""
    assert not [k for k in K.GLOSSARY if " " in k]


def test_bare_question_words_do_not_false_match() -> None:
    """A contentless question expands to nothing rather than dragging in section 1."""
    assert K._expand("یہ کیا ہے؟") == []


def test_urdu_sentence_punctuation_does_not_block_lookup() -> None:
    """۔ and ؟ must not be glued onto the word being looked up."""
    assert K._expand("ریکروٹمنٹ؟") == K._expand("ریکروٹمنٹ")


def test_spelled_out_acronyms_are_rebuilt() -> None:
    """Urdu spells acronyms letter by letter; the KB contains them joined."""
    assert "psx" in K._expand("پی ایس ایکس")
    assert "eps" in K._expand("ای پی ایس")
