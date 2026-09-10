"""What only an English reply gets wrong — voice_config/english_normalise.py.

The negative cases matter as much as the positive ones. Every rule here is English-only
because Urdu either does not reach the shape at all (a Latin legal suffix, "w.e.f.") or
because Uplift already reads it correctly in Urdu — the round trip recorded in
voice_config/README.md found percentages, "24/7" and dates all coming back right in an
Urdu sentence, so normalising them there would be the regression that file warns about.

Run: python -m pytest tests/ -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.providers.tts import _spoken  # noqa: E402
from voice_config.english_normalise import normalise_for_english  # noqa: E402


# ── percent ─────────────────────────────────────────────────────────

def test_percent_is_spoken() -> None:
    """33 in the corpus, and the sign is not a word to any voice: "33%" was handed
    over as "thirty three" and then silence."""
    assert "thirty three percent" in _spoken("Up 33% this year.", "en")


def test_percent_survives_the_number_spell_out() -> None:
    """The rule runs before the spell-out so the digits are still digits here."""
    assert "twelve percent" in _spoken("In FY2024-25 up 12%.", "en")


# ── slashes ─────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "text,expected",
    [
        ("Our AI/ML team.", "AI and ML"),
        ("The water/gas split.", "water and gas"),
        ("Pending additions/revisions.", "additions and revisions"),
    ],
)
def test_word_slashes_become_and(text: str, expected: str) -> None:
    """65 slashes in the corpus; the voice says the word "slash" for each one."""
    assert expected in _spoken(text, "en")


def test_24_7_is_an_idiom_not_a_ratio() -> None:
    """The one numeric slash that is neither a date nor a ratio."""
    assert "twenty four seven" in _spoken("Available 24/7 here.", "en")


def test_md_ceo_is_left_to_the_address_pass() -> None:
    """addresses.py already hyphenates the pair; this module must not reach it and
    turn it into "MD and CEO", which that module measured as worse."""
    assert "M-D and C-E-O" in _spoken("Faheem Haider (MD/CEO) spoke.", "en")


# ── clock times and colon ratios ────────────────────────────────────

@pytest.mark.parametrize(
    "text,expected",
    [
        ("Open 9:00 AM to 5:00 PM.", "nine AM to five PM"),   # a round hour drops :00
        ("Closes 5:30 PM daily.", "five thirty PM"),
    ],
)
def test_times_lose_the_colon(text: str, expected: str) -> None:
    assert expected in _spoken(text, "en")


def test_colon_ratio_reads_as_to() -> None:
    """The debt-to-equity pairs. Anchored to decimals on both sides, because the
    minutes bound alone is what stops the time rule eating "0.24:99.76" first."""
    said = _spoken("Debt ratio 0.24:99.76 today.", "en")
    assert "zero point two four to ninety nine point seven six" in said


def test_a_standards_revision_is_not_a_ratio() -> None:
    """"ISO 9001:2015" has no decimal after the colon, so neither the time rule nor
    the ratio rule may claim it; it keeps the reading it already had."""
    assert "ISO" in _spoken("We hold ISO 9001:2015.", "en")
    assert " to " not in _spoken("We hold ISO 9001:2015.", "en")


# ── legal suffixes and Latin abbreviations ──────────────────────────

@pytest.mark.parametrize(
    "text,expected",
    [
        ("Mari Petroleum Ltd today.", "Limited"),
        ("A (Pvt) Limited firm.", "Private"),
        ("Effective w.e.f. July.", "with effect from"),
        ("Assets e.g. wells.", "for example"),
        ("Gas vs. oil output.", "versus"),
        ("GST No: 07-01-2710.", "number"),
    ],
)
def test_abbreviations_are_expanded(text: str, expected: str) -> None:
    """Each is unreadable rather than merely awkward — "Pvt" has no vowel to fall
    back on — and each expansion is unambiguous."""
    assert expected in _spoken(text, "en")


# ── the brand ───────────────────────────────────────────────────────

def test_camel_cased_brand_gets_the_retroflex_flap() -> None:
    """"MariEnergies" (57×) beat the boundary-anchored ڑ rule that "Mari Energies"
    (6×) matched, so one company was said two ways."""
    assert "ماڑی Energies" in _spoken("MariEnergies grew fast.", "en")
    assert "ماڑی" in _spoken("Mari Petroleum Ltd today.", "en")


# ── what must NOT change ────────────────────────────────────────────

@pytest.mark.parametrize(
    "text,must_keep",
    [
        ("ہم 24/7 دستیاب ہیں۔", "24/7"),      # Uplift reads it correctly in Urdu
        ("منافع 33% رہا۔", "33%"),             # so are percentages
        ("2024/25 کے دوران۔", "2024/25"),      # a financial year, not a pair of words
    ],
)
def test_urdu_is_untouched(text: str, must_keep: str) -> None:
    """The module is a no-op on Urdu. Re-normalising what the voice already says
    correctly is the regression voice_config/README.md warns about."""
    assert must_keep in _spoken(text, "ur")


def test_the_function_itself_is_a_no_op_on_urdu() -> None:
    urdu = "ہم 24/7 دستیاب ہیں، منافع 33% رہا۔"
    assert normalise_for_english(urdu, "ur") == urdu


def test_english_numeric_slashes_are_not_pairs() -> None:
    """A slash between digits is a ratio or a date, never an "and"."""
    assert "and" not in _spoken("The 2024/25 period.", "en")


# ── opening hours ───────────────────────────────────────────────────

def test_a_time_range_is_a_span_not_two_times() -> None:
    """§16.2 writes office hours "9:00 AM-5:00 PM". The hyphen has the same shape as a
    well identifier ("Name-01"), and the formats pass was eating it — leaving
    "nine AM five PM", two unconnected times instead of a span."""
    said = _spoken("Office hours 9:00 AM-5:00 PM (PKT).", "en")
    assert "nine AM to five PM" in said


def test_a_well_identifier_still_keeps_its_number() -> None:
    """The exclusion above is anchored to AM/PM only, so identifiers are untouched."""
    assert "zero one" in _spoken("We drilled Karakoram-01 well.", "en")


def test_the_timezone_does_not_strand_urdu_inside_english() -> None:
    """"PKT" expanded to "Pakistan Standard Time" put the word "Pakistan" into an
    English phrase, which the places pass — running later — then respelled, giving
    "پاکستان Standard Time". An expansion must not contain a name a later pass owns."""
    said = _spoken("Office hours 9:00 AM to 5:00 PM (PKT).", "en")
    assert "پاکستان" not in said
    assert "PKT" not in said
