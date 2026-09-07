"""Fact-level retrieval: the small specific things, not just section topics.

tests/test_retrieval.py only ever asked heading-shaped questions, so it passed while
questions about a *detail inside* a section — a person's name, a well, a registration
number — retrieved nothing and MARI fell back to "I don't have that information".
These cases assert the answer text actually reaches the prompt.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server import knowledge as K  # noqa: E402

# (question, a string that must appear in the retrieved context to answer it)
URDU_FACTS = [
    ("این ٹی این نمبر کیا ہے؟", "1414673"),
    ("جی ایس ٹی نمبر", "2710"),
    ("رجسٹریشن نمبر", "00012471"),
    ("شیئرز رجسٹرار کون ہے؟", "Corplink"),
    ("بینک پارٹنرز کون سے ہیں؟", "Meezan"),
    ("لیگل ایڈوائزر کون ہے؟", "Panni"),
    ("سی ایف او کون ہے؟", "Nabeel"),
    ("فری فلوٹ کتنا ہے؟", "free float"),
    ("آیلہ مجید کون ہیں؟", "Ayla"),
    ("بھٹائی سکس", "Bhitai"),
    ("سیڈ پروگرام", "SEED"),
    ("وزیرستان بلاک", "Waziristan"),
    ("ڈہرکی فیلڈ", "Daharki"),
    ("غنی کیمیکل", "Ghani"),
    ("سجاول بلاک", "Sujawal"),
    ("کریڈٹ ریٹنگ", "AAA"),
    ("فہیم حیدر کون ہیں؟", "Faheem"),
]

ENGLISH_FACTS = [
    ("what is the NTN number", "1414673"),
    ("who is the shares registrar", "Corplink"),
    ("which banks are partners", "Meezan"),
    ("legal advisor", "Panni"),
    ("who is the CFO", "Nabeel"),
    ("Soho-1 well", "Soho"),
    ("reserves to production ratio", "20 years"),
    ("credit rating", "AAA"),
    ("Ayla Majid", "Ayla"),
    ("SEED program", "SEED"),
    ("head office address", "Mauve"),
    ("market capitalization", "753"),
]


@pytest.mark.parametrize("query,answer", URDU_FACTS)
def test_urdu_fact_reaches_the_prompt(query: str, answer: str) -> None:
    context = K.context_for(query)
    assert answer.lower() in context.lower(), (
        f"{query!r} expanded to {K._expand(query)} and retrieved "
        f"{[c.title for c in K.search(query)]}"
    )


@pytest.mark.parametrize("query,answer", ENGLISH_FACTS)
def test_english_fact_reaches_the_prompt(query: str, answer: str) -> None:
    assert answer.lower() in K.context_for(query).lower()


@pytest.mark.parametrize(
    "urdu,expected",
    [("مجید", "majid"), ("بھٹائی", "bhitai"), ("کارپلنک", "corplink"),
     ("نبیل", "nabeel"), ("رجسٹرار", "registrar"), ("ڈہرکی", "daharki"),
     ("فوجی", "fauji"), ("غنی", "ghani")],
)
def test_names_are_matched_by_sound(urdu: str, expected: str) -> None:
    """Proper nouns are unbounded, so they are matched phonetically, not from a list."""
    assert expected in K._sounds_like(urdu)


def test_sound_matching_stays_exact() -> None:
    """No fuzzy tolerance: an earlier edit-distance version matched درخت to 'direct'."""
    assert "direct" not in K._sounds_like("درخت")
    assert "dsra" not in K._sounds_like("آڈیٹر")


def test_typed_words_outrank_inferred_topics() -> None:
    """A glossary expansion must not outvote the specific term it came with."""
    weights = K._expand_weighted("ڈہرکی فیلڈ")
    assert weights["daharki"] > weights["development"]
