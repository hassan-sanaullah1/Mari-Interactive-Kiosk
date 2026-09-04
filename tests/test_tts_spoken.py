"""How a reply is rewritten for the voice.

Uplift's voice is Urdu-first and reads bare digits in Urdu, so an English reply
containing "65.14" was spoken with Urdu numbers. English replies therefore spell
their numbers out; Urdu replies must keep the digits, where that reading is right.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.providers.tts import _say_int, _spoken  # noqa: E402


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Net profit was PKR 65.14 billion.", "sixty five point one four billion rupees"),
        ("The workforce is 1,760 people.", "one thousand seven hundred and sixty"),
        ("Discovered in 1954.", "nineteen fifty four"),
        ("Listed in 2025.", "twenty twenty five"),
        ("Back in 2000.", "two thousand"),
        ("Capacity is 127 KBOEPD.", "one hundred and twenty seven"),
        ("A 20-year ratio.", "twenty-year"),
    ],
)
def test_english_numbers_are_spelled_out(text: str, expected: str) -> None:
    assert expected in _spoken(text, "en")


def test_english_leaves_no_bare_digits() -> None:
    """Any digit reaching the Urdu-first voice would be read in Urdu."""
    said = _spoken("Net profit PKR 65.14 billion, 1,760 staff, founded 1954.", "en")
    assert not any(ch.isdigit() for ch in said), said


@pytest.mark.parametrize(
    "text",
    [
        "خالص منافع 65.14 بلین روپے رہا۔",
        "گیس فیلڈ 1954 میں دریافت ہوا۔",
        "ملازمین کی تعداد 1,760 ہے۔",
    ],
)
def test_urdu_digits_are_left_alone(text: str) -> None:
    """Urdu mode wants the Urdu reading, so the digits must survive untouched."""
    assert _spoken(text, "ur") == text


def test_phone_numbers_are_read_digit_by_digit() -> None:
    """A dialling code is an identifier, not a quantity."""
    said = _spoken("Call 051-111 410 410.", "en")
    assert "one hundred and eleven" not in said
    assert "zero five one" in said


def test_acronyms_apply_in_both_languages() -> None:
    assert "M P C L" in _spoken("MPCL results", "en")
    assert "M P C L" in _spoken("MPCL کی رپورٹ", "ur")


def test_mari_is_said_with_the_retroflex_flap() -> None:
    """"Mari" is spelled with ر in both scripts, but said with ڑ, not a tapped ر."""
    assert "ماڑی" in _spoken("MARI welcomes you to Mari Energies.", "en")
    assert "ماڑی" in _spoken("آپ ماری ہیں — Mari Energies کی نمائندگی کرتی ہیں۔", "ur")


def test_mari_respelling_does_not_touch_unrelated_words() -> None:
    assert _spoken("مریم آج نہیں آئیں۔", "ur") == "مریم آج نہیں آئیں۔"


@pytest.mark.parametrize(
    "n,said",
    [(0, "zero"), (13, "thirteen"), (21, "twenty one"), (101, "one hundred and one"),
     (3000, "three thousand"), (952, "nine hundred and fifty two")],
)
def test_say_int(n: int, said: str) -> None:
    assert _say_int(n) == said
