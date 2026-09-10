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
def test_co2_is_named_not_spelled(written: str) -> None:
    """"CO₂" was heard as "seagull dough"; "CO2" became "COtwo". Spacing it to
    "C O two" fixed both but is not what anyone says out loud — a formula is a
    compound with a name, so it is named."""
    said = _spoken(f"We produce food-grade {written}.", "en")
    assert "carbon dioxide" in said
    assert "COtwo" not in said and "₂" not in said and "C O two" not in said


def test_co2_in_urdu_is_urdu() -> None:
    """"C O 2" was the worst reading of all: the Latin letters were said in English
    and the digit in Urdu, giving "C-O-do"."""
    said = spoken_addresses("ہم food-grade CO₂ بناتے ہیں۔", "ur")
    assert "کاربن ڈائی آکسائیڈ" in said
    assert "C O" not in said


@pytest.mark.parametrize(
    "written,expected",
    [("CH4", "methane"), ("H2S", "hydrogen sulphide"), ("SO2", "sulphur dioxide")],
)
def test_other_formulae_are_named_too(written: str, expected: str) -> None:
    assert expected in _spoken(f"We monitor {written} levels.", "en")


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

@pytest.mark.parametrize("written", ["MD/CEO", "MD & CEO", "CEO / Managing Director"])
def test_title_pairs_are_separated_in_english(written: str) -> None:
    """"MD/CEO" was heard as "MD/C8 August"; even "MD and CEO" collided across the "and"
    ("ESDM didn't see EO"). Hyphenating the letters reads back as "MD and CEO"."""
    said = _spoken(f"The {written} is Faheem Haider.", "en")
    assert "C-E-O" in said and "/" not in said


def test_title_pairs_are_separated_in_urdu() -> None:
    """The hyphenation above is an ENGLISH fix — it makes an English voice read the
    letters apart. In Urdu the pair is written in Urdu script instead, which needs no
    such trick: Latin letters in an Urdu sentence were the problem, not the cure."""
    said = _spoken("MD/CEO فہیم حیدر ہیں۔", "ur")
    assert "ایم ڈی اور سی ای او" in said
    assert "M-D" not in said


def test_a_doubled_title_pair_stays_short() -> None:
    """§3.1.7 says the pair twice in one sentence — "Faheem Haider (MD/CEO) serves as
    Chairman and MD/CEO". Expanding to six words twice was worse than the problem."""
    said = _spoken("Faheem Haider (MD/CEO) serves as Chairman and MD/CEO.", "en")
    assert said.count("M-D and C-E-O") == 2
    assert "Managing Director and Chief Executive Officer" not in said


def test_compound_chairman_md_ceo_does_not_say_and_twice() -> None:
    said = _spoken("Chairman/MD-CEO of Tuzgi Minerals.", "en")
    assert "and M-D C-E-O" in said and "and and" not in said


def test_a_lone_initialism_is_left_alone() -> None:
    """Only a *pair* joined by a separator breaks; "the CEO" on its own is fine."""
    assert _spoken("He is the CEO of the company.", "en") == "He is the CEO of the company."


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


def test_a_city_is_required_before_a_postcode() -> None:
    """The bug: any 5-digit run was announced as a postcode.

    Every ISO certification in the knowledge base is five digits, so the kiosk said
    "ISO postal code one four zero zero one" out loud for ISO 14001.
    """
    said = _spoken("We hold ISO 14001 certification.", "en")
    assert "postal code" not in said
    assert "fourteen thousand one" in said


@pytest.mark.parametrize("standard", ["ISO 9001", "ISO 14001", "ISO 26000", "ISO 27001",
                                      "ISO 45001", "OHSAS 18001"])
def test_no_standard_in_the_corpus_is_read_as_a_postcode(standard: str) -> None:
    assert "postal code" not in _spoken(f"Certified to {standard}.", "en")


def test_the_urdu_voice_does_not_announce_a_postcode_either() -> None:
    assert "پوسٹل کوڈ" not in spoken_addresses("ہم ISO 14001 سرٹیفائیڈ ہیں۔", "ur")


@pytest.mark.parametrize(
    "text,city",
    [
        ("Islamabad – 44000, Pakistan", "Islamabad"),
        ("Karachi – 75600; Tel (+92) 21 111-410-410", "Karachi"),
        ("Islamabad 44000", "Islamabad"),          # separator is optional
        ("Islamabad, 44000", "Islamabad"),
    ],
)
def test_a_real_postcode_still_gets_its_label(text: str, city: str) -> None:
    said = _spoken(text, "en")
    # The city itself is respelled by the places table; what this test guards is that
    # the postcode still gets its label and is read digit by digit.
    assert "postal code" in said


def test_the_edition_year_of_a_standard_is_not_run_into_its_number() -> None:
    """"ISO 45001:2018" left the colon in, so the two numbers ran together."""
    said = _spoken("Certified to ISO 45001:2018.", "en")
    assert "forty five thousand one, twenty eighteen" in said
    assert ":" not in said


def test_the_edition_year_uses_an_urdu_comma_in_urdu_mode() -> None:
    assert "، 2018" in spoken_addresses("ISO 45001:2018 سرٹیفائیڈ۔", "ur")


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
