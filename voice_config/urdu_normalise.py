"""Spoken-form fixes for the Uplift voice, for gaps Uplift does NOT cover itself.

The reference implementation this is adapted from targeted MMS-TTS/ElevenLabs, which
could not read Western digits in an Urdu sentence at all — so most of it was a
digits-to-Urdu-words converter ("127" → "ایک سو ستائیس").

Uplift does not need that. Round-tripping Uplift through Soniox STT shows digits,
decimals, percentages, "24/7", years and phone numbers all coming back correctly, and
"127" and "ایک سو ستائیس" synthesise to the same audio. Porting the converter would have
duplicated work the engine already does — and would have fought the English number
spell-out in ``server/providers/tts.py``, which exists for the opposite reason (the
Urdu-first voice reads bare digits in Urdu, which is wrong in English mode).

The same round-trip did expose three things Uplift gets wrong, all of which occur in the
Mari Energies knowledge base:

    "Tier III"             → "تھی رومن تھری"        Roman numerals, letter by letter
    "تیل/گیس"              → "تیل فلیش گیس"          the slash is read as "flash"
    "marienergies.com.pk"  → "میرین عجیز کام پی کے"  a bare URL is mangled

Those three are what the Urdu-only pass fixes, and nothing else.

:func:`spoken_formats` is separate and runs in BOTH languages. It covers the report
formats and symbols that occur in ``server/data/mari_energies_knowledge_base.md`` and
that neither voice reads correctly — fiscal years, DD/MM/YYYY dates, ratio multiples,
well identifiers and the symbols ~ − §. Those are structural rather than phonetic, so
unlike the three fixes above they are not engine-specific; every one leaves the digits
in place for the English spell-out in ``server/providers/tts.py`` to read.

Every rule is verified by ``tests/test_tts_spoken.py``.
"""

from __future__ import annotations

import re

# Urdu/Arabic script — used to decide whether a fix applies to this text at all.
_ARABIC_RE = re.compile(r"[؀-ۿݐ-ݿﭐ-﷿ﹰ-﻿]")


# ── 1. Roman numerals ───────────────────────────────────────────────
# Uplift reads "III" as separate letters ("آئی آئی آئی"). Only the values that
# actually occur as tier/phase/annex markers are mapped; a bare "I" is deliberately
# absent, since it collides with the English pronoun and with initials.
_ROMAN_VALUES = {
    "II": "2", "III": "3", "IV": "4", "V": "5",
    "VI": "6", "VII": "7", "VIII": "8", "IX": "9", "X": "10",
}

# Anchored to a label so ordinary capitalised words are never touched. "Tier III",
# "Phase II", "مرحلہ III" all qualify; a stray "IV" in prose does not.
_ROMAN_LABEL = r"(?:Tier|Phase|Annex|Annexure|Category|Class|ٹیئر|مرحلہ|درجہ)"
_ROMAN_RE = re.compile(
    rf"\b({_ROMAN_LABEL})(\s+)((?:{'|'.join(sorted(_ROMAN_VALUES, key=len, reverse=True))})(?:\s*/\s*(?:{'|'.join(sorted(_ROMAN_VALUES, key=len, reverse=True))}))*)\b"
)


def _roman_to_digits(match: re.Match[str]) -> str:
    """"Tier III/IV" → "Tier 3/4" — digits, which Uplift reads correctly."""
    label, gap, numerals = match.group(1), match.group(2), match.group(3)
    converted = "/".join(
        _ROMAN_VALUES.get(part.strip(), part.strip()) for part in numerals.split("/")
    )
    return f"{label}{gap}{converted}"


# ── 2. Slash ────────────────────────────────────────────────────────
# Uplift says "flash" for "/" between words. Numeric slashes ("24/7", "2024/25") are
# left alone — those it already reads as a ratio/range, and rewriting them to "اور"
# would change the meaning.
_WORD_SLASH_RE = re.compile(
    r"(?<=[\w؀-ۿ])\s*/\s*(?=[\w؀-ۿ])"
)
_NUMERIC_SLASH_RE = re.compile(r"\d\s*/\s*\d")


def _fix_slashes(text: str) -> str:
    """Replace word/word slashes with "اور"; leave numeric slashes untouched."""
    out, last = [], 0
    for m in _WORD_SLASH_RE.finditer(text):
        # A slash sitting between two digits is a ratio, not a conjunction.
        window = text[max(0, m.start() - 1): m.end() + 1]
        if _NUMERIC_SLASH_RE.search(window):
            continue
        out.append(text[last:m.start()])
        out.append(" اور ")
        last = m.end()
    out.append(text[last:])
    return "".join(out)


# ── 3. Bare URLs ────────────────────────────────────────────────────
# A written domain is not readable aloud in either language. The voice runs the label
# together into a different word and swallows the dots entirely:
#
#     English  "marienergies.com.pk"  → "marionettes.com.pk"
#              "mariservices.com.pk"  → "narrowservices.bk"
#              "linkedin.com"         → "Wing 10 Calm"
#     Urdu     "marienergies.com.pk"  → "میری انرجیز کام پی کے"   (no "ڈاٹ" at all)
#
# Saying the dot as a word fixes both, and splitting the label into its real words
# ("marienergies" → "Mari Energies") stops the voice guessing at a single long token.
# The label is looked up rather than split heuristically, because only the corpus knows
# that "mariservices" is two words and "linkedin" is one.
_DOMAIN_LABELS = {
    "marienergies": {"en": "Mari Energies", "ur": "ماڑی انرجیز"},
    "mariservices": {"en": "Mari Services", "ur": "ماڑی سروسز"},
    "sky47": {"en": "Sky Forty Seven", "ur": "اسکائی فورٹی سیون"},
    "linkedin": {"en": "LinkedIn", "ur": "لنکڈان"},
}

# Suffix pieces, said one at a time with an explicit "dot" between them.
_TLD_WORDS = {
    "com": {"en": "com", "ur": "کام"},
    "pk": {"en": "P K", "ur": "پی کے"},
    "org": {"en": "org", "ur": "آرگ"},
    "net": {"en": "net", "ur": "نیٹ"},
    "gov": {"en": "gov", "ur": "گو"},
    "edu": {"en": "edu", "ur": "ایجو"},
}

_DOT = {"en": "dot", "ur": "ڈاٹ"}
_WWW = {"en": "double u double u double u", "ur": "ڈبلیو ڈبلیو ڈبلیو"}

_URL_RE = re.compile(
    r"\b(?:(www)\.)?"
    rf"({'|'.join(sorted(_DOMAIN_LABELS, key=len, reverse=True))})"
    rf"((?:\.(?:{'|'.join(_TLD_WORDS)}))+)\b",
    re.IGNORECASE,
)


def _say_domain(match: re.Match[str], lang: str) -> str:
    """"marienergies.com.pk" → "Mari Energies dot com dot P K"."""
    www, label, suffix = match.group(1), match.group(2).lower(), match.group(3)
    dot = _DOT[lang]
    parts: list[str] = []
    if www:
        parts += [_WWW[lang], dot]
    parts.append(_DOMAIN_LABELS[label][lang])
    for piece in suffix.strip(".").split("."):
        parts += [dot, _TLD_WORDS[piece.lower()][lang]]
    return " ".join(parts)


def spoken_urls(text: str, lang: str = "en") -> str:
    """Rewrite bare domains so the dots are actually said. Used in both languages."""
    key = "ur" if lang == "ur" else "en"
    return _URL_RE.sub(lambda m: _say_domain(m, key), text)


# ── 4. Report formats and symbols ───────────────────────────────────
# Everything below is measured against the shapes that actually occur in
# server/data/mari_energies_knowledge_base.md, and applies in BOTH languages: these
# are structural, not phonetic. Each rule leaves DIGITS in place rather than writing
# out words, so the English spell-out in server/providers/tts.py still does the
# reading and an Urdu reply keeps the digits Uplift already says correctly.
#
# The whole section runs AFTER voice_config.addresses, which claims the identifier
# shapes it owns first (the Islamabad sector "G-10/4" would otherwise be eaten by the
# well-name rule below), and BEFORE the number spell-out, for the reason the
# well/date rules exist at all: these are identifiers and dates, not quantities.

# "FY2024-25" (11×), "FY 2024-25", "FY24-25" and bare "FY2025". Glued to the number,
# the voice said "FYtwenty twenty four" — the label is not separated from the year at
# all. The hyphen becomes a spoken "to"/"تا" so the range reads as one period.
_FY_LABEL = {"en": "financial year", "ur": "مالی سال"}
_TO_WORD = {"en": "to", "ur": "تا"}
_FY_RE = re.compile(r"\bFY\s*(\d{2,4})(?:\s*[-–]\s*(\d{2,4}))?\b", re.IGNORECASE)

# A bare "2024-25" is the same fiscal period without its label, and is common in the
# corpus. Anchored to a 4-digit year followed by exactly 2 digits so that spans like
# "2017-2020" keep their own reading and "20-year"/"18-inch" (digits BEFORE the
# hyphen) are never touched — tests/test_tts_spoken.py pins "twenty-year".
# The trailing guard rejects a decimal ("2024-25.5") but must still allow the period
# that ends a sentence, so it tests for a digit AFTER the dot rather than the dot itself.
_NOT_PART_OF_A_NUMBER = r"(?![\d/-])(?!\.\d)"
_FY_BARE_RE = re.compile(rf"(?<![\d./-])(\d{{4}})\s*[-–]\s*(\d{{2}}){_NOT_PART_OF_A_NUMBER}")

# Dates are written DD/MM/YYYY in the corpus (17×). The slash survives every existing
# rule — the word/word fix below deliberately skips numeric slashes, since "24/7" and
# "2024/25" are ratios — so the voice read "24/06/2022" as "twenty four slash six".
_MONTHS = {
    "en": ("January", "February", "March", "April", "May", "June",
           "July", "August", "September", "October", "November", "December"),
    "ur": ("جنوری", "فروری", "مارچ", "اپریل", "مئی", "جون",
           "جولائی", "اگست", "ستمبر", "اکتوبر", "نومبر", "دسمبر"),
}
_DATE_RE = re.compile(r"\b(\d{1,2})\s*/\s*(\d{1,2})\s*/\s*(\d{4})\b")

# Financial ratios are written "2.81x" (9×). Glued to the "x" the number regex in
# tts.py does not fire at all, so the whole token was handed to the voice untouched
# and read as the letter "ex".
_TIMES_WORD = {"en": "times", "ur": "گنا"}
_RATIO_RE = re.compile(r"(?<=\d)\s*x\b")

# Well, field, block and lease identifiers: "Karakoram-01", "Soho-1", "Mari Deep-01",
# "Block-5", "Survey-31". The number spell-out read these as quantities and silently
# dropped the leading zero — "Karakoram-01" came out "Karakoram-one". Spacing the
# digits apart makes each one read on its own ("zero one"), which is how a well name
# is said. A digit BEFORE the hyphen ("20-year", "18-inch") is not an identifier and
# is deliberately excluded by requiring a letter there.
# "AM"/"PM" are excluded: an opening-hours range is written "9:00 AM-5:00 PM", which
# has exactly the shape this rule looks for, and it was eating the hyphen — leaving
# "nine AM five PM", two unconnected times instead of a span.
_WELL_RE = re.compile(r"\b(?!(?:AM|PM)\b)([A-Za-z][A-Za-z]*)-(\d{1,2})\b", re.IGNORECASE)

# Symbols the voice either reads as a word of its own or drops entirely.
_SYMBOL_WORDS = {
    "~": {"en": "approximately ", "ur": "تقریباً "},
    "−": {"en": "minus ", "ur": "منفی "},   # U+2212, not the ASCII hyphen
    "§": {"en": "section ", "ur": "سیکشن "},
}
_SYMBOL_RE = re.compile(r"[~−§](?=\s*[\d\w])")

# An en-dash between two numbers is a range ("93,000–113,000 BOEPD"), not a minus.
_RANGE_RE = re.compile(r"(?<=\d)\s*–\s*(?=\d)")

# A hyphenated span of two full years — board tenures, "2017-2020", "1975-2006" — is
# nine characters of digits and dashes, which is exactly the shape the phone-number
# rule in tts.py looks for. It was being read out as a dialling code, digit by digit
# ("two zero one seven two zero two zero"). Spelling the hyphen as "to" here settles
# the range before that rule ever sees it. Distinct from _FY_BARE_RE above, which
# takes a 4-digit year followed by only TWO digits ("2024-25").
_YEAR_RANGE_RE = re.compile(
    rf"(?<![\d./-])((?:1[89]|20)\d{{2}})\s*[-–]\s*((?:1[89]|20)\d{{2}}){_NOT_PART_OF_A_NUMBER}"
)


def _say_fy(match: re.Match[str], lang: str) -> str:
    start, end = match.group(1), match.group(2)
    said = f"{_FY_LABEL[lang]} {start}"
    return f"{said} {_TO_WORD[lang]} {end}" if end else said


def _say_date(match: re.Match[str], lang: str) -> str:
    """"24/06/2022" → "24 June 2022" — the month as a word, the slashes gone."""
    day, month, year = int(match.group(1)), int(match.group(2)), match.group(3)
    if not 1 <= month <= 12 or not 1 <= day <= 31:
        return match.group(0)
    return f"{day} {_MONTHS[lang][month - 1]} {year}"


def spoken_formats(text: str, lang: str = "en") -> str:
    """Rewrite report formats and symbols that neither voice reads correctly.

    Applies in both languages, and leaves digits alone — the English spell-out in
    ``server/providers/tts.py`` still reads them, and Urdu keeps them as written.
    """
    key = "ur" if lang == "ur" else "en"
    text = _FY_RE.sub(lambda m: _say_fy(m, key), text)
    text = _DATE_RE.sub(lambda m: _say_date(m, key), text)
    # Before _FY_BARE_RE: a full year-to-year span is not a fiscal pair.
    text = _YEAR_RANGE_RE.sub(rf"\1 {_TO_WORD[key]} \2", text)
    text = _FY_BARE_RE.sub(rf"\1 {_TO_WORD[key]} \2", text)
    text = _RANGE_RE.sub(f" {_TO_WORD[key]} ", text)
    text = _RATIO_RE.sub(f" {_TIMES_WORD[key]}", text)
    text = _WELL_RE.sub(lambda m: f"{m.group(1)} {' '.join(m.group(2))}", text)
    return _SYMBOL_RE.sub(lambda m: _SYMBOL_WORDS[m.group(0)][key], text)


# ── 5. Urdu years ───────────────────────────────────────────────────
# Uplift reads a bare "1954" as a cardinal quantity — "ایک ہزار نو سو چون" — but a year
# in Urdu is said as a century pair: "انیس سو چون". The two readings are not
# interchangeable, and the corpus is full of founding dates and discovery years, so
# every 18xx/19xx year is written out here as words in the year style.
#
# 20xx years are deliberately left as digits: "دو ہزار چوبیس" IS the cardinal reading,
# which Uplift already produces correctly from "2024", and touching them would only
# risk the shapes (fiscal pairs, DD/MM/YYYY dates) that section 4 above owns.
_URDU_ONES = ("", "ایک", "دو", "تین", "چار", "پانچ", "چھ", "سات", "آٹھ", "نو")
# 10–99 has no regular pattern in Urdu; only the two-digit tails a year can take are
# needed, so the table is complete rather than composed.
_URDU_TENS_TAIL = (
    "دس", "گیارہ", "بارہ", "تیرہ", "چودہ", "پندرہ", "سولہ", "سترہ", "اٹھارہ", "انیس",
    "بیس", "اکیس", "بائیس", "تئیس", "چوبیس", "پچیس", "چھببیس", "ستائیس", "اٹھائیس", "انتیس",
    "تیس", "اکتیس", "بتیس", "تینتیس", "چونتیس", "پینتیس", "چھتیس", "سینتیس", "اڑتیس", "انتالیس",
    "چالیس", "اکتالیس", "بیالیس", "تینتالیس", "چوالیس", "پینتالیس", "چھیالیس", "سینتالیس", "اڑتالیس", "انچاس",
    "پچاس", "اکاون", "باون", "ترپن", "چون", "پچپن", "چھپن", "ستاون", "اٹھاون", "انسٹھ",
    "ساٹھ", "اکسٹھ", "باسٹھ", "تریسٹھ", "چوسٹھ", "پینسٹھ", "چھیاسٹھ", "سڑسٹھ", "اڑسٹھ", "انہتر",
    "ستر", "اکہتر", "بہتر", "تہتر", "چوہتر", "پچہتر", "چھہتر", "ستتر", "اٹھہتر", "اناسی",
    "اسی", "اکیاسی", "بیاسی", "تراسی", "چوراسی", "پچاسی", "چھیاسی", "ستاسی", "اٹھاسی", "نواسی",
    "نوے", "اکانوے", "بانوے", "ترانوے", "چورانوے", "پچانوے", "چھیانوے", "ستانوے", "اٹھانوے", "ننانوے",
)
# The same guards as the English year rule in server/providers/tts.py: not part of a
# longer digit run, not a decimal, and not glued to a hyphen or slash — a fiscal pair
# ("2024-25"), a date and a well number have already been rewritten by section 4 and
# must not be re-read here.
_URDU_YEAR_RE = re.compile(r"(?<![\d./-])(1[89])(\d{2})(?![\d./-])")


def _say_urdu_year(match: re.Match[str]) -> str:
    """"1954" → "انیس سو چون" — the century pair, not the cardinal count."""
    century, rest = int(match.group(1)), int(match.group(2))
    said = f"{_URDU_TENS_TAIL[century - 10]} سو"
    if rest == 0:
        # "1900" is "انیس سو" on its own — no tail to add.
        return said
    tail = _URDU_ONES[rest] if rest < 10 else _URDU_TENS_TAIL[rest - 10]
    return f"{said} {tail}"


def spoken_years(text: str) -> str:
    """Write 18xx/19xx years as Urdu words, in the year reading. Urdu replies only."""
    return _URDU_YEAR_RE.sub(_say_urdu_year, text)


def normalise_for_uplift(text: str, lang: str = "ur") -> str:
    """Rewrite an Urdu reply for the things Uplift mispronounces.

    Only runs on Urdu text. English replies keep Latin URLs and Roman numerals, which
    the voice handles acceptably in English mode and which the English number
    spell-out in ``server/providers/tts.py`` already covers.
    """
    if not text or lang != "ur" or not _ARABIC_RE.search(text):
        return text

    text = _ROMAN_RE.sub(_roman_to_digits, text)
    text = spoken_years(text)
    text = spoken_urls(text, "ur")
    text = _fix_slashes(text)
    return text
