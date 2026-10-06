"""STT hearing "Mari" as "Mary"/"Marry"/"Merry" — server/providers/stt.py.

The engines are biased toward the right word with a vocabulary hint (Soniox's
"context" field, Whisper's "initial_prompt"), but a homophone this close still slips
through sometimes. This is a kiosk that only ever discusses Mari Energies, so a
post-transcription correction catches what the hint misses — narrowly enough that an
unrelated sentence about a person named Mary is never touched.

Run: python -m pytest tests/ -q
"""

from __future__ import annotations

import pytest

from server.providers.stt import _fix_misheard_mari


# ── followed by a word from the company's own name ──────────────────

@pytest.mark.parametrize(
    "text,expected",
    [
        ("Tell me about Mary Energies", "Tell me about Mari Energies"),
        ("What is Marry Petroleum?", "What is Mari Petroleum?"),
        ("Explain Merry Gas Field to me", "Explain Mari Gas Field to me"),
        ("What is Mary's history?", "What is Mari's history?"),
        ("Mary Services handles drilling", "Mari Services handles drilling"),
        ("Mary Minerals mines copper", "Mari Minerals mines copper"),
        # Once the vocabulary hint nudges the decoder away from the common "Mary" but
        # it still doesn't land on "Mari", it reaches for another real word with a
        # similar sound instead — "Māori" (macron on the "a"; also comes back
        # unaccented) or "Mardi" (a light intrusive d).
        ("Tell me about Maori Energies", "Tell me about Mari Energies"),
        ("Tell me about Māori Energies", "Tell me about Mari Energies"),
        ("What is Mardi Petroleum?", "What is Mari Petroleum?"),
        ("What is Maori's history?", "What is Mari's history?"),
    ],
)
def test_mari_followed_by_company_word_is_corrected(text: str, expected: str) -> None:
    assert _fix_misheard_mari(text, "en") == expected


# ── standing in for the company on its own ──────────────────────────

@pytest.mark.parametrize(
    "text,expected",
    [
        ("Tell me about Mari", "Tell me about Mari"),
        ("Tell me about Mary", "Tell me about Mari"),
        ("What is Mary?", "What is Mari?"),
        ("What's Mary?", "What's Mari?"),
        ("Who owns Merry?", "Who owns Mari?"),
        ("Tell me Mary story", "Tell me Mari story"),
        ("Tell me about Maori", "Tell me about Mari"),
        ("Tell me about Mardi", "Tell me about Mari"),
        ("What is Maori?", "What is Mari?"),
        ("Who owns Mardi?", "Who owns Mari?"),
    ],
)
def test_bare_mari_in_a_kiosk_question_is_corrected(text: str, expected: str) -> None:
    assert _fix_misheard_mari(text, "en") == expected


@pytest.mark.parametrize(
    "text",
    ["The Maori people of New Zealand", "We celebrated Mardi Gras",
     "Tell me about Mardi Gras"],
)
def test_maori_and_mardi_gras_as_real_words_are_left_alone(text: str) -> None:
    """"Maori" and "Mardi Gras" are real, common phrases in their own right — the
    correction must not fire just because the sound-alike appears; it needs the
    company-context anchor too, and "Mardi Gras" specifically is excluded outright."""
    assert _fix_misheard_mari(text, "en") == text


# ── what must NOT change ─────────────────────────────────────────────

@pytest.mark.parametrize(
    "text",
    [
        "Call Mary tomorrow",
        "Hi Mary, how are you?",
        "My name is Mary",
        "Who is Mary Smith",
        "Mary had a little lamb",
    ],
)
def test_an_unrelated_mary_is_left_alone(text: str) -> None:
    """The whole point: a sentence that is not asking about this kiosk's company must
    reach the LLM exactly as the visitor said it."""
    assert _fix_misheard_mari(text, "en") == text


# ── Urdu ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "text,expected",
    [
        ("میری انرجیز کیا ہے؟", "ماری انرجیز کیا ہے؟"),
        ("میری کے بارے میں بتائیں", "ماری کے بارے میں بتائیں"),
        ("میری کیا ہے؟", "ماری کیا ہے؟"),
        ("میری کون ہے؟", "ماری کون ہے؟"),
    ],
)
def test_urdu_mari_is_corrected(text: str, expected: str) -> None:
    assert _fix_misheard_mari(text, "ur") == expected


@pytest.mark.parametrize(
    "text",
    ["میری بہن آج نہیں آئی", "یہ میری کتاب ہے"],
)
def test_urdu_possessive_meri_is_left_alone(text: str) -> None:
    """"میری" also means "my" — the genuine possessive must survive untouched."""
    assert _fix_misheard_mari(text, "ur") == text


def test_empty_text_is_a_no_op() -> None:
    assert _fix_misheard_mari("", "en") == ""
    assert _fix_misheard_mari("", "ur") == ""
