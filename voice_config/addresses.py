"""Addresses, contact details and symbol-bearing abbreviations, for both languages.

Everything here was picked by round-tripping the live Uplift voice (TTS → Soniox STT)
and keeping only the spelling that came back right. What the voice does untreated:

    "CO₂"            → "seagull dough"        the subscript is read as a word
    "CO2"            → "COtwo"                the number spell-out glues it on
                     → "C-O-do" (ur)          Latin letters in English, digit in Urdu
    "Ext. 483"       → "x483"                 "Ext" is read as the letter x
    "G-10/4"         → "G-ten/four" (en) and "ٹی جا سلاش ۴" (ur, says "slash")
    "44000"          → "forty four thousand"  a postcode is not a quantity
    "3rd Road"       → "Teen Ardi Road"       the ordinal is read as letters
    "MD and CEO"     → "ESDM didn't see EO"   initialisms collide across the "and"

The address rules are deliberately scoped: an Islamabad sector reads "G ten four" with
the slash silent, but a bare "24/7" or "2024/25" elsewhere in a reply must keep its
slash meaning, so sector handling only fires on the sector pattern itself.
"""

from __future__ import annotations

import re

# ── 1. Chemical formulae ────────────────────────────────────────────
# "CO₂" is read as a word ("seagull dough"); "CO2" is caught by the English number
# spell-out and becomes "COtwo".
#
# Spacing the characters apart ("C O 2") fixed those, but it was never what a person
# says, and in Urdu it is actively wrong: the voice reads the Latin letters in English
# and then the digit in Urdu, giving "C-O-do". A formula is a compound with a NAME —
# nobody says "C O 2" out loud — so each one is named instead, per language. That fixes
# the English reading and the Urdu one with the same rule.
_FORMULA_SUB = str.maketrans("₀₁₂₃₄₅₆₇₈₉", "0123456789")
# The trailing ``([A-Z])?`` is what lets "H2S" match: without it the lookahead below
# rejected any formula that ends in a letter rather than at a word boundary.
_FORMULA_RE = re.compile(r"\b(CO|NO|SO|CH|H|N)([₀-₉]|(?<=[A-Z])\d)([A-Z])?(?![\d\w])")

_FORMULA_NAMES: dict[str, dict[str, str]] = {
    "CO2": {"en": "carbon dioxide", "ur": "کاربن ڈائی آکسائیڈ"},
    "CO": {"en": "carbon monoxide", "ur": "کاربن مونو آکسائیڈ"},
    "CH4": {"en": "methane", "ur": "میتھین"},
    "H2": {"en": "hydrogen", "ur": "ہائیڈروجن"},
    "H2S": {"en": "hydrogen sulphide", "ur": "ہائیڈروجن سلفائیڈ"},
    "N2": {"en": "nitrogen", "ur": "نائٹروجن"},
    "N2O": {"en": "nitrous oxide", "ur": "نائٹرس آکسائیڈ"},
    "NO2": {"en": "nitrogen dioxide", "ur": "نائٹروجن ڈائی آکسائیڈ"},
    "SO2": {"en": "sulphur dioxide", "ur": "سلفر ڈائی آکسائیڈ"},
}


def _say_formula(match: re.Match[str], lang: str = "en") -> str:
    """"CO₂" → "carbon dioxide" / "کاربن ڈائی آکسائیڈ"."""
    letters, digit = match.group(1), match.group(2).translate(_FORMULA_SUB)
    tail = match.group(3) or ""
    named = _FORMULA_NAMES.get(f"{letters}{digit}{tail}")
    if named:
        return named["ur" if lang == "ur" else "en"]
    # An unknown formula keeps the old spacing, which at least stops the number pass
    # gluing the digit onto the letters.
    return " ".join(letters + tail) + " " + digit


# The model sometimes spells "CO2" out as Urdu letter names instead of the Latin
# formula — "سی او 2" ("C", "O", digit) rather than "CO2" — which _FORMULA_RE above
# does not match at all, so it fell through untouched and was read letter by letter
# with the digit glued on ("C-O-do"). Only "CO"/"CO2" occur spelled out this way in
# the corpus, so this is a fixed pair rather than a general letter-name parser.
_SPELLED_CO_RE = re.compile(r"\bسی\s+او\s*([۰-۹2])?\b")


def _say_spelled_co(match: re.Match[str]) -> str:
    digit = (match.group(1) or "").translate(_FORMULA_SUB)
    return _FORMULA_NAMES["CO2" if digit == "2" else "CO"]["ur"]


# ── 2. Ampersand initialisms ────────────────────────────────────────
# "E&P" survives in English but becomes "ایم ای این پی" in Urdu, and "HR&R" is run
# together into "H9R" in both. Spelling the ampersand as "and" with the letters spaced
# is what the voice reads back correctly.
_AMP_ABBR = {
    "E&P": {"en": "E and P", "ur": "ای اینڈ پی"},
    "HR&R": {"en": "H R and R", "ur": "ایچ آر اینڈ آر"},
    "HSE&Q": {"en": "H S E and Q", "ur": "ایچ ایس ای اینڈ کیو"},
    "R&D": {"en": "R and D", "ur": "آر اینڈ ڈی"},
    "M&A": {"en": "M and A", "ur": "ایم اینڈ اے"},
    "P&L": {"en": "P and L", "ur": "پی اینڈ ایل"},
}
_AMP_RE = re.compile("|".join(re.escape(k) for k in sorted(_AMP_ABBR, key=len, reverse=True)))


# ── 3. Slashed initialism pairs ─────────────────────────────────────
# "MD/CEO" is read as one run-on token ("MD/C8 August"), and a plain "MD and CEO" still
# collides across the "and" ("ESDM didn't see EO"). Hyphenating the letters gives the
# voice the separation it needs — "M-D and C-E-O" reads back as "MD and CEO" in English
# and "ایم ڈی اور سی ای او" in Urdu.
#
# Spelling the titles out in full ("Managing Director and Chief Executive Officer") also
# works, but the knowledge base repeats the pair inside a single sentence — §3.1.7 is
# "Faheem Haider (MD/CEO) serves as Chairman and MD/CEO" — and six words twice in one
# breath is far worse to listen to than the initialism it replaced. The short form keeps
# a doubled mention bearable.
_TITLE_LETTERS = {
    "MD": "M-D", "CEO": "C-E-O", "CFO": "C-F-O", "COO": "C-O-O",
    "CTO": "C-T-O", "CIO": "C-I-O", "CISO": "C-I-S-O",
    # "Chairman/MD-CEO" is one role written as a compound; expanding both halves with
    # "and" would say "and" twice in a row ("Chairman and M-D and C-E-O").
    "MD-CEO": "M-D C-E-O",
}
# Matches "MD/CEO", "MD & CEO", "CEO / Managing Director", "Chairman/MD-CEO" — every
# separator and ordering the corpus actually uses.
_SPELLED_TITLE = r"Managing Director|Chief Executive Officer|Chairman"
_TITLE_PAIR_RE = re.compile(
    rf"\b({'|'.join(sorted(_TITLE_LETTERS, key=len, reverse=True))}|{_SPELLED_TITLE})"
    rf"\s*[/&]\s*"
    rf"({'|'.join(sorted(_TITLE_LETTERS, key=len, reverse=True))}|{_SPELLED_TITLE})\b"
)
# A lone initialism is fine as-is; only a *pair* joined by a separator breaks, so single
# occurrences are deliberately left alone.
_AND = {"en": "and", "ur": "اور"}


def _say_title(token: str) -> str:
    return _TITLE_LETTERS.get(token, token)


# ── 4. Islamabad sectors ────────────────────────────────────────────
# "G-10/4" is a sector name, not a fraction: the slash is silent and the numbers are
# said in English in both languages ("G ten four"). Scoped tightly to the sector shape
# so "24/7" and "2024/25" elsewhere keep their own handling.
_SECTOR_RE = re.compile(r"\b([A-Z])[-\s]?(\d{1,2})\s*/\s*(\d{1,2})\b")
_TEENS = ("zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine",
          "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen",
          "seventeen", "eighteen", "nineteen")


def _say_small(n: int) -> str:
    if n < 20:
        return _TEENS[n]
    tens = ("", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety")
    return tens[n // 10] + (f" {_TEENS[n % 10]}" if n % 10 else "")


def _say_sector(match: re.Match[str]) -> str:
    letter, block, sub = match.group(1), int(match.group(2)), int(match.group(3))
    return f"{letter} {_say_small(block)} {_say_small(sub)}"


# ── 5. Postcodes ────────────────────────────────────────────────────
# "44000" is an identifier, not a quantity — "forty four thousand" is wrong. Said digit
# by digit, and labelled so the listener knows what the number is.
#
# The rule must see the CITY, not just five digits. Matching any bare 5-digit run made
# the voice announce "postal code" in front of every ISO certification in the corpus —
# "ISO postal code one four zero zero one" for ISO 14001, and the same for 26000, 27001
# and 45001. Both postcodes that actually exist in the knowledge base are written
# "<city> – <digits>" ("Islamabad – 44000", "Karachi – 75600"), so the city is the
# anchor. Anything else five digits long is left to the number spell-out, which reads a
# standard's number the way a person says it: "ISO fourteen thousand and one".
_CITY = (
    r"Islamabad|Karachi|Lahore|Rawalpindi|Peshawar|Quetta|Multan|Hyderabad|Sukkur|"
    r"Ghotki|Daharki|اسلام\s*آباد|کراچی|لاہور|راولپنڈی|پشاور|کوئٹہ|ملتان|حیدرآباد|"
    r"سکھر|گھوٹکی|ڈہرکی"
)
# The separator ("–", ",", or just a space) is consumed and re-emitted as a comma, so the
# voice pauses there instead of trying to say the dash.
_POSTCODE_RE = re.compile(
    rf"({_CITY})[\s,–—-]+(\d{{5}})\b(?!\s*(?:million|billion|thousand))"
)
_POSTAL_LABEL = {"en": "postal code", "ur": "پوسٹل کوڈ"}

# "ISO 45001:2018" — the colon separates the standard from the edition year, and the
# voice runs the two numbers together into one stumble. A comma makes it a pause; both
# numbers are then spelled out normally by the pass in server/providers/tts.py.
_STANDARD_EDITION_RE = re.compile(
    r"\b((?:ISO|IEC|OHSAS|ASTM|EN)(?:/[A-Z]{2,6})?\s*\d{4,5})\s*:\s*(\d{4})\b"
)
_DIGIT_WORDS = {
    "en": ("zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine"),
    "ur": ("صفر", "ایک", "دو", "تین", "چار", "پانچ", "چھ", "سات", "آٹھ", "نو"),
}


# ── 6. Ordinals in street names ─────────────────────────────────────
# "3rd Road" is read letter by letter ("3 آر ڈی روڈ" / "Teen Ardi Road").
_ORDINALS = {
    "1st": {"en": "First", "ur": "فرسٹ"}, "2nd": {"en": "Second", "ur": "سیکنڈ"},
    "3rd": {"en": "Third", "ur": "تھرڈ"}, "4th": {"en": "Fourth", "ur": "فورتھ"},
    "5th": {"en": "Fifth", "ur": "فففتھ"}, "6th": {"en": "Sixth", "ur": "سکستھ"},
    "7th": {"en": "Seventh", "ur": "سیونتھ"}, "8th": {"en": "Eighth", "ur": "ایتھ"},
    "9th": {"en": "Ninth", "ur": "نائنتھ"}, "10th": {"en": "Tenth", "ur": "ٹینتھ"},
}
_ORDINAL_RE = re.compile(rf"\b({'|'.join(_ORDINALS)})\b", re.IGNORECASE)


# ── 7. Contact-detail abbreviations ─────────────────────────────────
# "Ext." is read as the letter x ("x483"). "P.O. Box" and "Tel"/"Fax" are spelled out
# so the whole contact line reads as speech rather than as a form field.
_CONTACT = {
    "en": [
        (re.compile(r"\bExt\.?\s*(?=\d)", re.IGNORECASE), "extension "),
        # an extension is an identifier, not a quantity ("four hundred and eighty three")
        (re.compile(r"(?<=extension )(\d{2,5})\b"),
         lambda m: " ".join(_DIGIT_WORDS["en"][int(d)] for d in m.group(1))),
        (re.compile(r"\bP\.?\s?O\.?\s+Box\b", re.IGNORECASE), "Post Office Box"),
        # a box number is an identifier too ("one thousand six hundred and fourteen")
        (re.compile(r"(?<=Post Office Box )(\d{1,6})\b"),
         lambda m: " ".join(_DIGIT_WORDS["en"][int(d)] for d in m.group(1))),
        (re.compile(r"\bTel\.?(?=[\s:])", re.IGNORECASE), "Telephone"),
        (re.compile(r"\bFax\.?(?=[\s:])", re.IGNORECASE), "Fax"),
        (re.compile(r"\bUAN\b"), "U A N"),
    ],
    "ur": [
        (re.compile(r"\bExt\.?\s*(?=\d)", re.IGNORECASE), "ایکسٹینشن "),
        (re.compile(r"(?<=ایکسٹینشن )(\d{2,5})\b"),
         lambda m: " ".join(_DIGIT_WORDS["ur"][int(d)] for d in m.group(1))),
        (re.compile(r"\bP\.?\s?O\.?\s+Box\b", re.IGNORECASE), "پوسٹ آفس باکس"),
        (re.compile(r"(?<=پوسٹ آفس باکس )(\d{1,6})\b"),
         lambda m: " ".join(_DIGIT_WORDS["ur"][int(d)] for d in m.group(1))),
        (re.compile(r"\bTel\.?(?=[\s:])", re.IGNORECASE), "ٹیلیفون"),
        (re.compile(r"\bFax\.?(?=[\s:])", re.IGNORECASE), "فیکس"),
        (re.compile(r"\bUAN\b"), "یو اے این"),
    ],
}


# ── 8b. Urdu transliterations the model produces anyway ─────────────
# The Urdu prompt asks for "kiosk" in Latin letters, but a weaker instruction-follower
# (Qwen, where DeepSeek complied) writes "کائوسک"/"کیوسک" regardless. The user chose the
# Latin spelling because the Urdu one is said "kioosk", so this puts it back — a prompt
# rule cannot be relied on for something the listener hears every greeting.
_TRANSLIT_BACK = {
    "ur": [(re.compile(r"کائیوسک|کائوسک|کیوسک|کیوسْک"), "kiosk")],
    "en": [],
}

# ── 8. Hyphenated prefixes ──────────────────────────────────────────
# In ENGLISH the hyphen swallows the prefix's final vowel and "anti-corruption" is heard
# as "ant"; a space keeps the two words apart. Urdu mode is deliberately excluded — the
# voice already says "اینٹی کرپشن" correctly there, and spacing it made it WORSE
# ("این ڈی کرپشن"), so this rule is one of the few that is not applied to both.
_PREFIX_RE = re.compile(
    r"\b(anti|multi|semi|non|pre|post|co|re|sub|inter|intra|micro|macro|self|cross|ex)"
    r"-(?=[a-z])",
    re.IGNORECASE,
)


def spoken_addresses(text: str, lang: str = "en") -> str:
    """Rewrite addresses, contact details and symbol-bearing abbreviations for the voice.

    Runs BEFORE the English number spell-out in ``server/providers/tts.py``, because
    several of these rules exist precisely to stop that pass from turning an identifier
    (a postcode, a sector, "CO2") into a quantity.
    """
    if not text:
        return text
    key = "ur" if lang == "ur" else "en"

    text = _FORMULA_RE.sub(lambda m: _say_formula(m, lang), text)
    if key == "ur":
        text = _SPELLED_CO_RE.sub(lambda m: _say_spelled_co(m), text)
    text = _AMP_RE.sub(lambda m: _AMP_ABBR[m.group(0)][key], text)
    text = _TITLE_PAIR_RE.sub(
        lambda m: f"{_say_title(m.group(1))} {_AND[key]} {_say_title(m.group(2))}", text
    )
    text = _SECTOR_RE.sub(_say_sector, text)

    comma = "،" if key == "ur" else ","
    text = _STANDARD_EDITION_RE.sub(rf"\1{comma} \2", text)

    digits = _DIGIT_WORDS[key]
    text = _POSTCODE_RE.sub(
        lambda m: f"{m.group(1)}{comma} {_POSTAL_LABEL[key]} "
        + " ".join(digits[int(d)] for d in m.group(2)),
        text,
    )

    text = _ORDINAL_RE.sub(lambda m: _ORDINALS[m.group(1).lower()][key], text)
    for pattern, replacement in _CONTACT[key]:
        text = pattern.sub(replacement, text)
    for pattern, replacement in _TRANSLIT_BACK[key]:
        text = pattern.sub(replacement, text)
    if key == "en":
        text = _PREFIX_RE.sub(r"\1 ", text)
    return text
