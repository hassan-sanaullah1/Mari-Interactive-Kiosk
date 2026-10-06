"""Addresses, contact details, formulae and symbol-bearing abbreviations.

Every expectation was chosen by round-tripping the live Uplift voice
(TTS → Soniox STT). What the voice did untreated is quoted next to each case.

The negative cases at the bottom matter as much as the positive ones: several of these
rules sit right next to patterns that must keep their existing behaviour ("24/7" is not
an Islamabad sector; a financial figure is not a postcode).
"""

from __future__ import annotations

import pytest

from server.normalization import normalize_for_tts
from server.normalization import spoken_addresses


# ── chemical formulae ───────────────────────────────────────────────

@pytest.mark.parametrize("written", ["CO₂", "CO2"])
def test_co2_is_named_not_spelled(written: str) -> None:
    """"CO₂" was heard as "seagull dough"; "CO2" became "COtwo". Spacing it to
    "C O two" fixed both but is not what anyone says out loud — a formula is a
    compound with a name, so it is named."""
    said = normalize_for_tts(f"We produce food-grade {written}.", "en")
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
    assert expected in normalize_for_tts(f"We monitor {written} levels.", "en")


# ── ampersand initialisms ───────────────────────────────────────────

def test_e_and_p_in_english() -> None:
    """Untreated the Urdu voice said "ایم ای این پی"."""
    assert "exploration and production" in normalize_for_tts("We provide E&P services.", "en")


def test_e_and_p_in_urdu() -> None:
    said = normalize_for_tts("ہم E&P خدمات فراہم کرتے ہیں۔", "ur")
    assert "E&P" not in said


def test_hr_and_r() -> None:
    assert "H R and R" in normalize_for_tts("The HR&R Committee met.", "en")


# ── slashed title pairs ─────────────────────────────────────────────

@pytest.mark.parametrize("written", ["MD/CEO", "MD & CEO", "CEO / Managing Director"])
def test_title_pairs_are_separated_in_english(written: str) -> None:
    """"MD/CEO" was heard as "MD/C8 August"; even "MD and CEO" collided across the "and"
    ("ESDM didn't see EO"). Hyphenating the letters reads back as "MD and CEO"."""
    said = normalize_for_tts(f"The {written} is Faheem Haider.", "en")
    assert "C-E-O" in said and "/" not in said


def test_title_pairs_are_separated_in_urdu() -> None:
    """The hyphenation above is an ENGLISH fix — it makes an English voice read the
    letters apart. In Urdu the pair is written in Urdu script instead, which needs no
    such trick: Latin letters in an Urdu sentence were the problem, not the cure."""
    said = normalize_for_tts("MD/CEO فہیم حیدر ہیں۔", "ur")
    assert "ایم ڈی اور سی ای او" in said
    assert "M-D" not in said


def test_a_doubled_title_pair_stays_short() -> None:
    """§3.1.7 says the pair twice in one sentence — "Faheem Haider (MD/CEO) serves as
    Chairman and MD/CEO". Expanding to six words twice was worse than the problem."""
    said = normalize_for_tts("Faheem Haider (MD/CEO) serves as Chairman and MD/CEO.", "en")
    assert said.count("M-D and C-E-O") == 2
    assert "Managing Director and Chief Executive Officer" not in said


def test_compound_chairman_md_ceo_does_not_say_and_twice() -> None:
    said = normalize_for_tts("Chairman/MD-CEO of Tuzgi Minerals.", "en")
    assert "and M-D C-E-O" in said and "and and" not in said


def test_a_lone_initialism_is_left_alone() -> None:
    """Only a *pair* joined by a separator breaks; "the CEO" on its own is fine."""
    assert normalize_for_tts("He is the CEO of the company.", "en") == "He is the CEO of the company."


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
    said = normalize_for_tts("Islamabad – 44000, Pakistan", "en")
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
    said = normalize_for_tts("We hold ISO 14001 certification.", "en")
    assert "postal code" not in said
    assert "fourteen thousand one" in said


@pytest.mark.parametrize("standard", ["ISO 9001", "ISO 14001", "ISO 26000", "ISO 27001",
                                      "ISO 45001", "OHSAS 18001"])
def test_no_standard_in_the_corpus_is_read_as_a_postcode(standard: str) -> None:
    assert "postal code" not in normalize_for_tts(f"Certified to {standard}.", "en")


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
    said = normalize_for_tts(text, "en")
    # The city itself is respelled by the places table; what this test guards is that
    # the postcode still gets its label and is read digit by digit.
    assert "postal code" in said


def test_the_edition_year_of_a_standard_is_not_run_into_its_number() -> None:
    """"ISO 45001:2018" left the colon in, so the two numbers ran together."""
    said = normalize_for_tts("Certified to ISO 45001:2018.", "en")
    assert "forty five thousand one, twenty eighteen" in said
    assert ":" not in said


def test_the_edition_year_uses_an_urdu_comma_in_urdu_mode() -> None:
    assert "، 2018" in spoken_addresses("ISO 45001:2018 سرٹیفائیڈ۔", "ur")


# ── ordinals, contact details ───────────────────────────────────────

def test_street_ordinal() -> None:
    """"3rd Road" was heard as "Teen Ardi Road" / "3 آر ڈی روڈ"."""
    assert "Third Road" in normalize_for_tts("21 Mauve Area, 3rd Road", "en")
    # "Road" itself stays Latin — the voice reads that correctly ("تھرڈ روڈ" came back
    # from the round trip); only the ordinal needed rewriting.
    assert "تھرڈ" in spoken_addresses("21 Mauve Area, 3rd Road", "ur")


def test_extension_is_a_word_and_its_number_is_digits() -> None:
    """"Ext. 483" was heard as "x483"; the number is an identifier, not a quantity."""
    said = normalize_for_tts("Tel: 111-410-410 (Ext. 483).", "en")
    assert "extension four eight three" in said
    assert "Ext" not in said and "four hundred" not in said


def test_extension_in_urdu() -> None:
    said = spoken_addresses("(Ext. 483)", "ur")
    assert "ایکسٹینشن چار آٹھ تین" in said


def test_po_box_and_tel_are_spelled_out() -> None:
    said = normalize_for_tts("P.O. Box 1614; Tel: 123", "en")
    assert "Post Office Box" in said and "Telephone" in said


# ── hyphenated prefixes ─────────────────────────────────────────────

def test_anti_prefix_is_split_in_english() -> None:
    """"anti-corruption" lost its final vowel and was heard as "ant"."""
    assert "anti corruption" in normalize_for_tts("Our anti-corruption policy.", "en")


def test_anti_prefix_is_left_alone_in_urdu() -> None:
    """The Urdu voice already says "اینٹی کرپشن" correctly; spacing it made it WORSE
    ("این ڈی کرپشن"), so the rule is English-only."""
    assert "anti-corruption" in normalize_for_tts("ہماری anti-corruption پالیسی سخت ہے۔", "ur")


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
    assert must_keep in normalize_for_tts(text, lang)


def test_financial_figures_are_not_treated_as_postcodes() -> None:
    said = normalize_for_tts("Net profit was PKR 65.14 billion and 1,760 staff in 1954.", "en")
    assert "sixty five point one four" in said
    assert "nineteen fifty four" in said
    assert "postal code" not in said


def test_five_digit_quantity_with_a_scale_word_is_still_a_quantity() -> None:
    assert "postal code" not in normalize_for_tts("about 12500 million cubic feet", "en")


def test_po_box_number_is_digits_not_a_quantity() -> None:
    """A box number is an identifier, like the postcode and the extension."""
    said = normalize_for_tts("P.O. Box 1614, Islamabad", "en")
    assert "Post Office Box one six one four" in said
    assert "thousand" not in said


# ── every other initialism ──────────────────────────────────────────
# Round-tripped through the live voice, plain Latin capitals from the knowledge base came
# back as other words in both languages: "UBL" → "above", "IBA" → "Eber", "NTN" → "MTN",
# "PPL" → "TPL". English reads hyphenated letters correctly; Urdu reads Urdu letter names.

@pytest.mark.parametrize(
    "written,english,urdu",
    [("UET", "U-E-T", "یو ای ٹی"), ("UBL", "U-B-L", "یو بی ایل"),
     ("NTN", "N-T-N", "این ٹی این"), ("ACCA", "A-C-C-A", "اے سی سی اے"),
     ("SNGPL", "S-N-G-P-L", "ایس این جی پی ایل"), ("SLAs", "S-L-As", "ایس ایل اےز")],
)
def test_initialisms_are_spelled_for_the_voice(written: str, english: str, urdu: str) -> None:
    assert english in normalize_for_tts(f"It works with {written} today.", "en")
    assert urdu in normalize_for_tts(f"یہ {written} کے ساتھ ہے۔", "ur")


@pytest.mark.parametrize(
    "written,urdu", [("LUMS", "لمز"), ("PARCO", "پارکو"), ("GEM", "جیم")]
)
def test_acronyms_said_as_words_are_not_spelled_out(written: str, urdu: str) -> None:
    assert normalize_for_tts(f"It works with {written} today.", "en") == \
        f"It works with {written} today."
    assert urdu in normalize_for_tts(f"یہ {written} کے ساتھ ہے۔", "ur")


def test_triple_a_rating() -> None:
    assert "triple A" in normalize_for_tts("Rated AAA long term.", "en")
    assert "ٹرپل اے" in normalize_for_tts("ریٹنگ AAA ہے۔", "ur")


@pytest.mark.parametrize("lang", ["en", "ur"])
def test_capitalised_words_and_roman_numerals_are_not_initialisms(lang: str) -> None:
    said = normalize_for_tts("THIS IS NOT a drill.", lang)
    assert "THIS IS NOT" in said
    assert "Tier 3" in normalize_for_tts("یہ Tier III ڈیٹا سینٹر ہے۔", "ur")


def test_measured_english_initialisms_stay_latin() -> None:
    assert normalize_for_tts("The CEO leads AI and HR.", "en") == "The CEO leads AI and HR."


def test_urdu_spaced_ampersand_is_said_as_and() -> None:
    """"ایم ڈی & سی ای او" came back as "ایم ڈی ایم پسند سی ای او"."""
    said = normalize_for_tts("جو Fauji Foundation کے MD & CEO بھی ہیں۔", "ur")
    assert "ایم ڈی اور سی ای او" in said and "&" not in said


# ── units ───────────────────────────────────────────────────────────
# A unit symbol was read as its letters: "kW" as "K W", and "MW"/"TB" were spelled by the
# initialism pass. Round-tripped, the spelled-out names came back as the symbol.

@pytest.mark.parametrize(
    "text,english,urdu",
    [
        ("Racks take 50kW.", "fifty kilowatts", "50 کلو واٹ"),
        ("Racks take 50 KW.", "fifty kilowatts", "50 کلو واٹ"),
        ("Density in kW per rack.", "kilowatts per rack", "کلو واٹ"),
        ("Up to 30 kW/rack.", "thirty kilowatts per rack", "30 کلو واٹ فی"),
        ("It makes 20 GWh.", "twenty gigawatt hours", "20 گیگا واٹ آور"),
        ("On an 11 kV line at 50 Hz.", "eleven kilovolt line at fifty hertz", "11 کلو وولٹ"),
        ("Stored at 25°C.", "twenty five degrees Celsius", "25 ڈگری سینٹی گریڈ"),
        ("It holds 500 TB.", "five hundred terabytes", "500 terabyte"),
        ("It covers 12 km².", "twelve square kilometres", "12 مربع کلومیٹر"),
        ("It saves 826,580 kg.", "kilograms", "826,580 کلوگرام"),
        ("Sold at 5 MMBtu.", "five million B-T-U", "5 ملین بی ٹی یو"),
    ],
)
def test_units_are_said_by_name(text: str, english: str, urdu: str) -> None:
    assert english in normalize_for_tts(text, "en")
    assert urdu in normalize_for_tts(f"{text} ہے۔", "ur")


@pytest.mark.parametrize(
    "text,expected",
    [("one 1 kW rack", "one kilowatt rack"), ("a 50-kW rack", "fifty kilowatt rack"),
     ("a 100 MW plant", "one hundred megawatt plant")],
)
def test_a_unit_used_as_an_adjective_is_singular(text: str, expected: str) -> None:
    assert expected in normalize_for_tts(text, "en")


def test_urdu_letter_spelling_of_a_unit() -> None:
    """The model writes the symbol as Urdu letter names: «50 کے ڈبلیو»."""
    said = normalize_for_tts("ہر ریک 50 کے ڈبلیو تک لیتا ہے۔", "ur")
    assert "50 کلو واٹ" in said and "ڈبلیو" not in said


@pytest.mark.parametrize("text", ["It runs on 4G.", "The TB programme treated 300 people."])
def test_symbols_without_a_number_are_left_to_other_rules(text: str) -> None:
    said = normalize_for_tts(text, "en")
    assert "gigabyte" not in said and "terabyte" not in said
