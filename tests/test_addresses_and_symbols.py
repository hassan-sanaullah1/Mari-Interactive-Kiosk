"""Addresses, contact details, formulae and symbol-bearing abbreviations.

Every expectation was chosen by round-tripping the live Uplift voice
(TTS → Soniox STT). What the voice did untreated is quoted next to each case.

The negative cases at the bottom matter as much as the positive ones: several of these
rules sit right next to patterns that must keep their existing behaviour ("24/7" is not
an Islamabad sector; a financial figure is not a postcode).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.providers.tts import _spoken  # noqa: E402
from voice_config.addresses import spoken_addresses  # noqa: E402


# ── chemical formulae ───────────────────────────────────────────────

@pytest.mark.parametrize("written", ["CO₂", "CO2"])
def test_co2_is_said_c_o_two(written: str) -> None:
    """"CO₂" was heard as "seagull dough"; "CO2" became "COtwo"."""
    said = _spoken(f"We produce food-grade {written}.", "en")
    assert "C O two" in said
    assert "COtwo" not in said and "₂" not in said


def test_co2_in_urdu_too() -> None:
    assert "C O 2" in spoken_addresses("ہم food-grade CO₂ بناتے ہیں۔", "ur")


# ── ampersand initialisms ───────────────────────────────────────────

def test_e_and_p_in_english() -> None:
    """Untreated the Urdu voice said "ایم ای این پی"."""
    assert "exploration and production" in _spoken("We provide E&P services.", "en")


def test_e_and_p_in_urdu() -> None:
    said = _spoken("ہم E&P خدمات فراہم کرتے ہیں۔", "ur")
    assert "E&P" not in said


def test_hr_and_r() -> None:
    assert "H R and R" in _spoken("The HR&R Committee met.", "en")


# ── slashed title pairs ─────────────────────────────────────────────

@pytest.mark.parametrize("written", ["MD/CEO", "MD & CEO"])
def test_title_pairs_are_spelled_out_in_english(written: str) -> None:
    """"MD/CEO" was heard as "MD/C8 August"; even "MD and CEO" collided across the
    "and" ("ESDM didn't see EO"), so each title is spelled out in full."""
    said = _spoken(f"The {written} is Faheem Haider.", "en")
    assert "Managing Director and Chief Executive Officer" in said


def test_title_pairs_are_spelled_out_in_urdu() -> None:
    said = _spoken("MD/CEO فہیم حیدر ہیں۔", "ur")
    assert "منیجنگ ڈائریکٹر اور چیف ایگزیکٹو آفیسر" in said


# ── Islamabad sectors ───────────────────────────────────────────────

@pytest.mark.parametrize("lang", ["en", "ur"])
def test_sector_is_english_numbers_with_a_silent_slash(lang: str) -> None:
    """"G-10/4" was "G-ten/four" in English and "ٹی جا سلاش ۴" in Urdu — the Urdu voice
    said the word "slash". A sector is read "G ten four" in both languages."""
    said = spoken_addresses("Our office is in G-10/4, Islamabad.", lang)
    assert "G ten four" in said
    assert "/" not in said


# ── postcodes ───────────────────────────────────────────────────────

def test_postcode_is_digits_not_a_quantity() -> None:
    """"44000" was read "forty four thousand"."""
    said = _spoken("Islamabad – 44000, Pakistan", "en")
    assert "postal code four four zero zero zero" in said
    assert "thousand" not in said


def test_postcode_in_urdu() -> None:
    said = spoken_addresses("اسلام آباد – 44000", "ur")
    assert "پوسٹل کوڈ چار چار صفر صفر صفر" in said


# ── ordinals, contact details ───────────────────────────────────────

def test_street_ordinal() -> None:
    """"3rd Road" was heard as "Teen Ardi Road" / "3 آر ڈی روڈ"."""
    assert "Third Road" in _spoken("21 Mauve Area, 3rd Road", "en")
    # "Road" itself stays Latin — the voice reads that correctly ("تھرڈ روڈ" came back
    # from the round trip); only the ordinal needed rewriting.
    assert "تھرڈ" in spoken_addresses("21 Mauve Area, 3rd Road", "ur")


def test_extension_is_a_word_and_its_number_is_digits() -> None:
    """"Ext. 483" was heard as "x483"; the number is an identifier, not a quantity."""
    said = _spoken("Tel: 111-410-410 (Ext. 483).", "en")
    assert "extension four eight three" in said
    assert "Ext" not in said and "four hundred" not in said


def test_extension_in_urdu() -> None:
    said = spoken_addresses("(Ext. 483)", "ur")
    assert "ایکسٹینشن چار آٹھ تین" in said


def test_po_box_and_tel_are_spelled_out() -> None:
    said = _spoken("P.O. Box 1614; Tel: 123", "en")
    assert "Post Office Box" in said and "Telephone" in said


# ── hyphenated prefixes ─────────────────────────────────────────────

def test_anti_prefix_is_split_in_english() -> None:
    """"anti-corruption" lost its final vowel and was heard as "ant"."""
    assert "anti corruption" in _spoken("Our anti-corruption policy.", "en")


def test_anti_prefix_is_left_alone_in_urdu() -> None:
    """The Urdu voice already says "اینٹی کرپشن" correctly; spacing it made it WORSE
    ("این ڈی کرپشن"), so the rule is English-only."""
    assert "anti-corruption" in _spoken("ہماری anti-corruption پالیسی سخت ہے۔", "ur")


# ── what must NOT change ────────────────────────────────────────────

@pytest.mark.parametrize(
    "lang,text,must_keep",
    [
        ("ur", "ہم 24/7 دستیاب ہیں۔", "24/7"),          # a ratio, not a sector
        ("ur", "2024/25 کے دوران۔", "2024/25"),          # a financial year
        ("ur", "منافع 65.14 ارب روپے۔", "65.14"),        # Urdu keeps its digits
        ("ur", "Tier III/IV سرٹیفائیڈ۔", "Tier 3/4"),    # roman-numeral rule still wins
    ],
)
def test_existing_behaviour_is_untouched(lang: str, text: str, must_keep: str) -> None:
    assert must_keep in _spoken(text, lang)


def test_financial_figures_are_not_treated_as_postcodes() -> None:
    said = _spoken("Net profit was PKR 65.14 billion and 1,760 staff in 1954.", "en")
    assert "sixty five point one four" in said
    assert "nineteen fifty four" in said
    assert "postal code" not in said


def test_five_digit_quantity_with_a_scale_word_is_still_a_quantity() -> None:
    assert "postal code" not in _spoken("about 12500 million cubic feet", "en")


def test_po_box_number_is_digits_not_a_quantity() -> None:
    """A box number is an identifier, like the postcode and the extension."""
    said = _spoken("P.O. Box 1614, Islamabad", "en")
    assert "Post Office Box one six one four" in said
    assert "thousand" not in said
