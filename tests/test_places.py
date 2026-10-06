"""Urdu- and Pashto-origin proper nouns (the places section of server/normalization.py).

The names section covers the people in the knowledge base; this covers everything else that is
Urdu-origin and written in Latin script — gas fields, districts, formations, wells and
the CSR programme names. The corpus is 100% Latin, so before this table the Urdu-first
voice read every one of them with English phonetics in both languages.

The negative cases carry as much weight as the positive ones: respelling a name the
voice already says correctly makes it worse, which is the lesson the names table records.

Run: python -m pytest tests/ -q
"""

from __future__ import annotations

from pathlib import Path

import pytest

from server.normalization import normalize_for_tts
from server.normalization import _ALL_PLACES, spoken_places


@pytest.mark.parametrize(
    "text,expected",
    [
        ("The Daharki field.", "ڈھرکی"),          # 13× — the most frequent field
        ("Our Sujawal Block.", "سجاول"),           # 7×
        ("The Ghazij formation.", "غازیج"),        # 7×
        ("A Shewa discovery.", "شیوہ"),            # 7×
        ("Spinwam acreage.", "سپین وام"),          # 5×
        ("In Waziristan.", "وزیرستان"),            # 12×
        ("Sachal complex.", "سچل"),
        ("Kawagarh formation.", "کاواگڑھ"),
        ("Zarghun Medical Camp.", "زرغون"),
    ],
)
def test_fields_and_places_are_respelled(text: str, expected: str) -> None:
    assert expected in normalize_for_tts(text, "en")


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Mari Kissan Dost Program.", "کسان دوست"),
        ("Mari Mobile Dastarkhwan.", "دسترخوان"),
        # The corpus spells it two ways (§12.5.4 vs §14.3.2); both must reach the
        # one correct spoken form.
        ("Mari Mobile Dastarkhawn.", "دسترخوان"),
        ("Roshan Mustaqbil Program.", "روشن مستقبل"),
        ("Fauji Foundation holds it.", "فوجی"),   # 25× — the majority shareholder
    ],
)
def test_programme_and_group_names_are_respelled(text: str, expected: str) -> None:
    assert expected in normalize_for_tts(text, "en")


def test_places_apply_in_urdu_too() -> None:
    """The corpus is Latin-only, so an Urdu reply carries these names in Latin script
    as well, and the voice mangles them there for the same reason."""
    assert "ڈھرکی" in normalize_for_tts("ہمارا Daharki فیلڈ ہے۔", "ur")


def test_a_well_identifier_keeps_its_number(sample: None = None) -> None:
    """Ordering guard: the formats pass splits "Spinwam-1" into "Spinwam 1" first,
    and its rule needs a Latin letter before the hyphen. If places ran earlier the
    name would already be Urdu script and the hyphen would survive unspoken."""
    said = normalize_for_tts("Spinwam-1 in Waziristan.", "en")
    assert "سپین وام one" in said
    assert "-" not in said


def test_the_brand_still_wins_over_a_place() -> None:
    """"Mari" has its own brand rule and is deliberately not in this table."""
    assert "ماڑی غازیج" in normalize_for_tts("Mari Ghazij-1 well.", "en")


@pytest.mark.parametrize(
    "name,urdu",
    [("Islamabad", "اسلام آباد"), ("Karachi", "کراچی"),
     ("Sindh", "سندھ"), ("Balochistan", "بلوچستان"), ("Karakoram", "قراقرم"),
     ("Punjab", "پنجاب"), ("Lahore", "لاہور")],
)
def test_familiar_names_are_respelled_too(name: str, urdu: str) -> None:
    """These were once held back as "internationally familiar", which was the biggest
    hole in the table. Familiarity to a READER is not pronunciation to a VOICE: the
    engine applies English phonetics to Latin script whether or not the word is famous,
    so "Karakoram" was mangled exactly like "Sujawal". Script is the test, not fame."""
    said = normalize_for_tts(f"We operate in {name} today.", "en")
    assert urdu in said and name not in said


def test_pakistan_gets_its_accent_without_urdu_script() -> None:
    """"Pakistan" is the one name in this table that must stay in the Latin alphabet.

    The ماڑی trick — hand the Urdu-first voice Urdu letters and it reaches for
    Pakistani phonemes — fails on this word specifically: "پاکستان" came back as
    "pakesten", and sometimes the voice read the Urdu letters out one at a time. A
    Latin respelling lengthens the two /aː/ vowels the way a Pakistani speaker does
    while staying in the alphabet this voice reads reliably.
    """
    said = normalize_for_tts("We operate across Pakistan today.", "en")
    assert "Paakistaan" in said
    # The failure mode this replaced: no Urdu script for this word, ever.
    assert "پاکستان" not in said


@pytest.mark.parametrize(
    "text,expected",
    [
        ("A Pakistani energy company.", "Paakistaani"),
        ("Pakistanis are proud.", "Paakistaanis"),
        # The possessive needs no entry of its own — the table is \b-anchored and the
        # boundary falls before the apostrophe — but it is pinned so that stays true.
        ("Pakistan's largest company.", "Paakistaan's"),
    ],
)
def test_the_derived_forms_get_the_accent_too(text: str, expected: str) -> None:
    """"Pakistani" was missed by the bare "Pakistan" entry: the trailing "i" is a word
    character, so the \\b boundary never lands after "Pakistan". Longest-first matching
    is what lets the adjective and plural win over the shorter key."""
    assert expected in normalize_for_tts(text, "en")


@pytest.mark.parametrize(
    "name",
    ["Lockhart", "Neptune", "Miyawaki", "Chevening", "Dundee", "Wolverhampton",
     # "Indus" is a translation risk, not an accent choice: the entry this table once
     # had for it ("سندھ دریا") was the words "the Sindh river", not a respelling — see
     # the note above test_indus_does_not_fire_inside_industry. Left out on that
     # narrower ground; unlike "Pakistan" it was never about accent versus mangling.
     "Indus"],
)
def test_genuinely_foreign_names_are_left_alone(name: str) -> None:
    """The narrow, and correct, ground for exclusion: these are not Urdu words at all,
    so the voice should say them in English. "Lockhart" is a formation named after a
    Briton, not a Pakistani place."""
    assert name in normalize_for_tts(f"We reached the {name} level today.", "en")
    assert name not in _ALL_PLACES


def test_indus_does_not_fire_inside_industry() -> None:
    """"Indus" is a substring of "industry"/"industrial", which occur far more often
    than the basin does. Whole-word anchoring is what keeps them apart."""
    said = normalize_for_tts("The industry and industrial output grew.", "en")
    assert "industry" in said and "industrial" in said


def test_longest_key_wins() -> None:
    """"Mughal Kot" must not be broken up by a shorter overlapping key."""
    assert "مغل کوٹ" in normalize_for_tts("The Mughal Kot Sst formation.", "en")


def test_unknown_text_is_untouched() -> None:
    assert spoken_places("Nothing to see here.") == "Nothing to see here."


# ── phrases and the words they are made of ──────────────────────────
# The tables match a whole phrase, and a reply does not always give one: it says "the
# Kot formation", "the Dost scheme", "Reko Diq" split across a clause. Each component
# word has its own entry, and longest-first matching keeps the phrase winning when the
# whole phrase is present.

@pytest.mark.parametrize(
    "phrase,part,phrase_urdu,part_urdu",
    [
        ("The Mughal Kot Sst formation.", "The Kot formation.", "مغل کوٹ", "کوٹ"),
        ("Mari Kissan Dost Program.", "The Dost scheme.", "کسان دوست", "دوست"),
        ("Roshan Mustaqbil Program.", "The Mustaqbil fund.", "روشن مستقبل", "مستقبل"),
    ],
)
def test_a_phrase_and_its_parts_both_work(
    phrase: str, part: str, phrase_urdu: str, part_urdu: str
) -> None:
    assert phrase_urdu in normalize_for_tts(phrase, "en")
    assert part_urdu in normalize_for_tts(part, "en")


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Reko Diq Mining.", "ریکو ڈک"),
        ("Daud Khel site.", "داؤد خیل"),
        ("Abu Dhabi office.", "ابو ظہبی"),
        ("Al Baraka Bank.", "البرکہ"),
        ("Bank Alfalah and Askari Bank.", "الفلاح"),
    ],
)
def test_partner_and_locality_names_are_respelled(text: str, expected: str) -> None:
    assert expected in normalize_for_tts(text, "en")


def test_no_local_origin_word_in_the_corpus_is_left_in_latin() -> None:
    """A sweep of the whole knowledge base, not a spot check. Every capitalised token
    that is not an English dictionary word, an abbreviation handled elsewhere, or a
    genuinely foreign name must reach the voice in Urdu script."""
    import collections
    import re

    kb = (Path(__file__).resolve().parent.parent
          / "server" / "data" / "mari_energies_knowledge_base.md").read_text()
    try:
        english = {w.strip().capitalize()
                   for w in open("/usr/share/dict/words") if len(w.strip()) > 2}
    except OSError:  # pragma: no cover - the dictionary is not installed everywhere
        pytest.skip("no system word list to separate English from local names")

    # Report vocabulary, abbreviations owned by other passes, and non-Urdu names.
    allowed = {
        "Pvt", "Retd", "Hons", "Lst", "Sst", "Ext", "Pre", "Sustainability",
        "Condensate", "Defence", "Rebranding", "Shareholding", "Decarbonization",
        "Whistleblowing", "Geoscientists", "Tagline", "Commerciality", "Analytics",
        "Digitalization", "Recordable", "Bowsers", "Onymous", "Trainings", "Abled",
        "Centre", "Financials", "Newsroom", "Recognitions", "Ipieca", "Miyawaki",
        "Chevening", "Dundee", "Wolverhampton", "Lockhart", "Malik",
        # "Indus" is a translation risk (see test_genuinely_foreign_names_are_left_alone
        # above); "Cantt"/"Maroc" are the same. "Pakistan" is NOT here — it is
        # deliberately respelled for the accent, and this sweep should keep catching it
        # if that entry is ever removed again.
        "Indus", "Cantt", "Maroc",
        # Sky47 cloud/AI vocabulary (§3.1.3): a Chinese vendor, an open-source
        # project and a model family. Foreign brand names, not local words —
        # the voice should say them as written, like "Lockhart" above.
        "Huawei", "Kubernetes", "Pangu",
    }
    words = collections.Counter(re.findall(r"\b[A-Z][a-z]{2,}\b", kb))
    missed = [
        w for w in words
        if w not in english and w not in allowed
        and not any(ord(c) > 0x600 for c in normalize_for_tts(f"About {w} today.", "en"))
    ]
    assert not missed, f"still read as English: {sorted(missed)}"


# ── Urdu spellings the model writes itself ──────────────────────────

@pytest.mark.parametrize(
    "written,expected",
    [("ڈہرکی میں گیس", "ڈھرکی"), ("ساچل گیس پروسیسنگ", "سچل")],
)
def test_urdu_spelling_variants_are_normalised(written: str, expected: str) -> None:
    """In Urdu mode the model transliterates as it writes rather than leaving the name
    in Latin, and it does not always pick the spelling that reads correctly: "ڈہرکی"
    loses the aspiration of ڈھ. The same place must sound the same whichever spelling
    the model happened to produce."""
    assert expected in normalize_for_tts(written, "ur")


def test_a_reordered_urdu_acronym_is_corrected() -> None:
    """The Urdu prompt asks for acronyms in Latin, but the model transliterates them
    anyway — and sometimes reorders the letters, writing "این جی ایل" (N-G-L) for LNG.
    A wrong acronym is a wrong fact, so every spelling converges on the right one."""
    for written in ("این جی ایل", "ایل این جی", "LNG"):
        assert "ایل این جی" in normalize_for_tts(f"GEM Energy {written} بناتی ہے۔", "ur")
