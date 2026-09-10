"""Spoken forms for Pakistani place, field and programme names — both languages.

``names.py`` fixes the people in the knowledge base. This file is the same trick for
everything else that is Urdu- or Pashto-origin and written in Latin script: gas fields,
districts, formations, wells and the CSR programme names. The corpus is 100% Latin, so
in English mode the Urdu-first Uplift voice reads all of them with English phonetics —
"Daharki" (13×), "Sujawal" (7×), "Ghazij" (7×), "Spinwam" (5×), "Waziristan" (12×) —
and none of them were covered by any existing pass.

Why this is a separate table from ``names.py``:

*   A place name is not a person. ``_NAMES_FOR_ENGLISH`` is a per-language list because
    the round trip found some names better in Latin and some in Urdu script. For an
    Urdu-origin *toponym* there is no such split — the Urdu spelling is what the word
    actually is, and the same spelling is right in an English sentence and an Urdu one.
    So this table applies in both languages, like ``ماڑی`` in ``providers/tts.py``.
*   Only the TTS payload changes. The visitor still reads the Latin spelling on screen.

**These entries have not been round-tripped.** ``voice_config/README.md`` asks for
Uplift → Soniox verification before a rule is added, and that is still the right bar;
this table was built from the corpus instead, after the kiosk was reported mispronouncing
English-mode names. The transliterations are conventional Urdu spellings, so the risk is
a wrong *vowel*, not a wrong word — but anything here that a round trip shows was already
correct in Latin should be deleted, exactly as the comment in ``names.py`` says.

An earlier version of this file held back the names a reader would recognise —
"Pakistan", "Islamabad", "Karachi", "Sindh", "Balochistan", "Karakoram" — on the
grounds that an English voice "already handles" them. That was wrong, and it was the
biggest hole in the table: **familiarity to a reader is not pronunciation to a voice.**
The engine applies English phonetics to Latin script whether or not the word is famous,
so "Karakoram" and "Pakistan" (60× in the corpus, the most frequent of all of them)
were mangled exactly like "Sujawal" was. Recognisability was never the test; script is.

Still deliberately absent, on the opposite and much narrower ground that they are not
Urdu words at all: genuinely foreign names the voice should say in English —
"Lockhart" (a formation named after a Briton), "Neptune", "Miyawaki", "Chevening",
"Dundee", "Wolverhampton", "Soho", "PwC", "Ferguson". Pinned in
``tests/test_places.py``.
"""

from __future__ import annotations

import re

# ── fields, wells, formations and districts ─────────────────────────
# Longest first at match time, so "Mughal Kot" wins over a bare "Kot" and
# "Sui Main Limestone" is not broken up by the "Sui" entry.
_PLACES: dict[str, str] = {
    # Gas fields and processing sites
    "Daharki": "ڈھرکی",
    "Sujawal": "سجاول",
    "Ghotki": "گھوٹکی",
    "Kandhkot": "کندھ کوٹ",
    "Sachal": "سچل",
    "Bhitai": "بھٹائی",
    "Halini": "ہالینی",
    "Zarghun": "زرغون",
    "Pirkoh": "پیرکوہ",
    "Sanghar": "سانگھڑ",
    # Formations and reservoirs. "Ghazij" and "Goru" are formation names that occur
    # far more often than any well that carries them.
    "Ghazij": "غازیج",
    "Goru": "گورو",
    "Habib Rahi": "حبیب راہی",
    "Mughal Kot": "مغل کوٹ",
    "Rani Kot": "رانی کوٹ",
    "Sui": "سوئی",
    "Kawagarh": "کاواگڑھ",
    "Samanasuk": "سمانہ سک",
    "Hangu": "ہنگو",
    "Dughan": "دوغان",
    "Chiltan": "چلتن",
    # Wells and blocks — Pashto-origin names from the Waziristan and Karak acreage
    "Spinwam": "سپین وام",
    "Shewa": "شیوہ",
    "Shawal": "شوال",
    "Maiwand": "میوند",
    "Pateji": "پٹیجی",
    "Jhim": "جھم",
    "Karak": "کرک",
    # Provinces and major cities.
    #
    # "Pakistan" is the one name here that must NOT be written in Urdu script.
    #
    # The ماڑی/مریم trick — hand the Urdu-first voice Urdu letters and it reaches for
    # Pakistani phonemes — works on most names in this table but fails on this one:
    # round-tripping "پاکستان" gave "pakesten", and sometimes the voice fell back to
    # reading the Urdu letters out one at a time. Two different failures, both worse
    # than leaving the word alone, and neither is what an accent request wanted.
    #
    # A Latin respelling gets the accent without ever handing the engine Urdu script:
    # "Paakistaan" lengthens the two /aː/ vowels the way a Pakistani speaker does,
    # while staying in the alphabet the voice reads reliably. The trailing "-stan" is
    # left as-is because that syllable is already said correctly.
    #
    # The derived forms need their own entries: the table is \b-anchored, so the
    # possessive "Pakistan's" is already covered (the boundary falls before the
    # apostrophe), but "Pakistani" is not — the trailing "i" is a word character, so
    # the boundary never lands after "Pakistan". Listed first so longest-first matching
    # takes the adjective whole rather than leaving a stranded "i".
    "Pakistanis": "Paakistaanis",
    "Pakistani": "Paakistaani",
    "Pakistan": "Paakistaan",
    "Sindh": "سندھ",
    "Punjab": "پنجاب",
    "Balochistan": "بلوچستان",
    "Khyber Pakhtunkhwa": "خیبر پختونخوا",
    "Pakhtunkhwa": "پختونخوا",
    "Khyber": "خیبر",
    "Islamabad": "اسلام آباد",
    "Karachi": "کراچی",
    "Lahore": "لاہور",
    # Ranges and deserts. "Indus" is deliberately absent for two reasons: it is an
    # English word the voice reads correctly, and the entry it had ("سندھ دریا") was a
    # TRANSLATION — "the Sindh river" — not a respelling. This table exists to change
    # how a name sounds, never which name is said.
    "Karakoram": "قراقرم",
    "Suleiman": "سلیمان",
    "Thar": "تھر",
    # Districts, regions and towns
    "Waziristan": "وزیرستان",
    "Bannu": "بنوں",
    "Daud Khel": "داؤد خیل",
    "Bijjar": "بجار",
    "Laghari": "لغاری",
    "Reko Diq": "ریکو ڈک",
    "Ziarat": "زیارت",
    "Quetta": "کوئٹہ",
    "Hyderabad": "حیدرآباد",
    "Jhelum": "جہلم",
    "Dadu": "دادو",
    "Kabirwala": "کبیروالا",
    "Khipro": "کھپرو",
    "Sukkur": "سکھر",
    "Peshawar": "پشاور",
    "Rawalpindi": "راولپنڈی",
    "Makran": "مکران",
    "Mach": "مچھ",
    "Okara": "اوکاڑہ",
    "Aligarh": "علی گڑھ",
    "Nandpur": "نندپور",
    "Pab": "پاب",
    # Address localities. "Chowk" and "Cantt" are ordinary Urdu words used as address
    # elements, and neither survives an English reading.
    "Bijjar Chowk": "بجار چوک",
    "Chowk": "چوک",
    # "Cantt" is deliberately absent: "چھاؤنی" is the Urdu WORD for a cantonment, not
    # a way of saying "Cantt", and substituting it changes what the address says.
    "Jinnah": "جناح",
    "Azadi": "آزادی",
    # Minerals ventures
    "Tuzgi": "توزگی",
    "Ammuri": "عموری",
}

# ── programme and institution names ─────────────────────────────────
# The CSR programmes are Urdu phrases written in Latin, and read as English they are
# not words at all. "Dastarkhwan" is spelled two ways in the corpus (§12.5.4 vs
# §14.3.2); both are mapped to the one correct spoken form.
_PROGRAMMES: dict[str, str] = {
    "Mobile Dastarkhwan": "موبائل دسترخوان",
    "Mobile Dastarkhawn": "موبائل دسترخوان",
    "Dastarkhwan": "دسترخوان",
    "Dastarkhawn": "دسترخوان",
    "Roshan Mustaqbil": "روشن مستقبل",
    "Kissan Dost": "کسان دوست",
    "Sehat Umeed": "صحت امید",
    "Gharonda": "گھروندا",
    "Sehar": "سحر",
    "Naya Pakistan": "نیا پاکستان",
    # "Fauji" is the most frequent Urdu word in the corpus (25×) — the Fauji
    # Foundation group that holds the majority stake — and "Askari" and "Meezan"
    # are the banks alongside it.
    "Fauji": "فوجی",
    "Askari": "عسکری",
    "Meezan": "میزان",
    "Faysal": "فیصل",
    # "Maroc" is deliberately absent: "مراکش" is Morocco, the country. The company is
    # "Pakistan Maroc Phosphate", and renaming it is not a pronunciation fix.
    # The rest of the banking and partner list, all Urdu/Arabic-origin. "Al Baraka"
    # and "Alhaj" carry the Arabic article, which an English voice reads as the
    # English word "al".
    "Alfalah": "الفلاح",
    "Al Baraka": "البرکہ",
    "Alhaj": "الحاج",
    "BankIslami": "بینک اسلامی",
    "Habib": "حبیب",
    "Attock": "اٹک",
    "Engro": "اینگرو",
    "Ghani": "غنی",
    "Noor": "نور",
    "Kehkashan": "کہکشاں",
    "Panni": "پنی",
    "Sehat": "صحت",
    "Umeed": "امید",
    "Bhitai": "بھٹائی",
    "Corplink": "کارپلنک",
    "Fatima": "فاطمہ",
    "Kabirwala": "کبیروالا",
    "Portia": "پورشیا",
    "Orient": "اورینٹ",
    "Paramount": "پیراماؤنٹ",
    "Stanvac": "اسٹینویک",
    "Clifton": "کلفٹن",
    "Ramadan": "رمضان",
    "EZShifa": "ای زیڈ شفا",
    "Pak-Turk": "پاک ترک",
    "Pak Arab": "پاک عرب",
    # The two spellings of the school's name in the corpus, and the programme names.
    "Noor-e-Sehar": "نور سحر",
    "Noor-Sehar": "نور سحر",
    "Gharonda": "گھروندا",
    "Dad Laghari": "داد لغاری",
}

# ── the words the multiword keys are made of ────────────────────────
# The tables above match a whole phrase, and a reply does not always give one: it says
# "the Kot formation", "the Kissan Dost scheme", "Reko Diq" split across a clause. Each
# component word therefore gets its own entry, listed after the phrases so that the
# longest-first sort still lets "Mughal Kot" win over a bare "Kot".
_PARTS: dict[str, str] = {
    "Mughal": "مغل",
    "Kot": "کوٹ",
    "Rani": "رانی",
    "Kissan": "کسان",
    "Dost": "دوست",
    "Roshan": "روشن",
    "Mustaqbil": "مستقبل",
    "Reko": "ریکو",
    "Diq": "ڈک",
    "Daud": "داؤد",
    "Khel": "خیل",
    "Laghari": "لغاری",
    "Naya": "نیا",
    "Hilal": "ہلال",
    "Abu": "ابو",
    "Dhabi": "ظہبی",
    "Baraka": "برکہ",
    "Pak": "پاک",
    "Sehar": "سحر",
    "Esso": "ایسو",
    "Petroserv": "پیٹروسرو",
    "Infraavest": "انفراویسٹ",
    "Planetive": "پلانیٹو",
}

# ── Urdu spellings the model writes itself ──────────────────────────
# In Urdu mode the model does not always leave a name in Latin for the tables above to
# catch — it transliterates as it writes, and it does not always pick the spelling that
# reads correctly. "ڈہرکی" loses the aspiration of ڈھ, and "ساچل" stretches the first
# vowel of سچل. These map an Urdu variant onto the Urdu form the voice says correctly,
# so the same place sounds the same whichever spelling the model happened to produce.
_URDU_VARIANTS: dict[str, str] = {
    "ڈہرکی": "ڈھرکی",
    "ساچل": "سچل",
    "سجاؤل": "سجاول",
    # The Urdu prompt asks for acronyms in Latin so the acronym table in
    # providers/tts.py can reach them, but the model transliterates them anyway — and
    # when it does it sometimes reorders the letters, writing "این جی ایل" (N-G-L) for
    # LNG. A wrong acronym is a wrong fact, so the ones the corpus actually uses are
    # mapped back to the correct spoken form here as a backstop.
    "این جی ایل": "ایل این جی",
    "ایل این جی": "ایل این جی",
}

_ALL: dict[str, str] = {**_PLACES, **_PROGRAMMES, **_PARTS, **_URDU_VARIANTS}


def _pattern(entries: dict[str, str]) -> re.Pattern[str] | None:
    if not entries:
        return None
    keys = sorted(entries, key=len, reverse=True)
    return re.compile("|".join(rf"\b{re.escape(k)}\b" for k in keys))


_PLACE_RE = _pattern(_ALL)


def spoken_places(text: str, lang: str = "en") -> str:
    """Respell Urdu- and Pashto-origin proper nouns so the voice uses Urdu phonemes.

    Applies in both languages: the corpus is Latin-only, so an Urdu reply carries these
    names in Latin script too, and the Urdu-first voice mangles them there for the same
    reason it does in English.
    """
    if not text or _PLACE_RE is None:
        return text
    return _PLACE_RE.sub(lambda m: _ALL[m.group(0)], text)
