"""Addresses, contact details and symbol-bearing abbreviations, for both languages.

Everything here was picked by round-tripping the live Uplift voice (TTS → Soniox STT)
and keeping only the spelling that came back right. What the voice does untreated:

    "CO₂"            → "seagull dough"        the subscript is read as a word
    "CO2"            → "COtwo"                the number spell-out glues it on
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
# spell-out and becomes "COtwo". Spacing the letters and the digit apart makes the voice
# say "C O 2", which is what a listener expects. Runs before the number pass.
_FORMULA_SUB = str.maketrans("₀₁₂₃₄₅₆₇₈₉", "0123456789")
_FORMULA_RE = re.compile(r"\b(CO|NO|SO|CH|H|N)([₀-₉]|(?<=[A-Z])\d)(?![\d\w])")


def _say_formula(match: re.Match[str]) -> str:
    letters, digit = match.group(1), match.group(2).translate(_FORMULA_SUB)
    return " ".join(letters) + " " + digit


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
# "MD/CEO" is read as one run-on token. Splitting on "and" is right, but the letters
# also need room: "the MD and CEO" came back as "ESDM didn't see EO". Spelling each
# title out in full is the only form the voice says cleanly every time.
_TITLE_WORDS = {
    "MD": {"en": "Managing Director", "ur": "منیجنگ ڈائریکٹر"},
    "CEO": {"en": "Chief Executive Officer", "ur": "چیف ایگزیکٹو آفیسر"},
    "CFO": {"en": "Chief Financial Officer", "ur": "چیف فنانشل آفیسر"},
    "COO": {"en": "Chief Operating Officer", "ur": "چیف آپریٹنگ آفیسر"},
    "CTO": {"en": "Chief Technology Officer", "ur": "چیف ٹیکنالوجی آفیسر"},
    "CIO": {"en": "Chief Information Officer", "ur": "چیف انفارمیشن آفیسر"},
    "CISO": {"en": "Chief Information Security Officer", "ur": "چیف انفارمیشن سیکیورٹی آفیسر"},
}
_TITLE_PAIR_RE = re.compile(
    rf"\b({'|'.join(_TITLE_WORDS)})\s*[/&]\s*({'|'.join(_TITLE_WORDS)})\b"
)
_AND = {"en": "and", "ur": "اور"}


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
_POSTCODE_RE = re.compile(r"(?<![\d-])(?:[–—-]\s*)?\b(\d{5})\b(?!\s*(?:million|billion|thousand))")
_POSTAL_LABEL = {"en": "postal code", "ur": "پوسٹل کوڈ"}
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

    text = _FORMULA_RE.sub(_say_formula, text)
    text = _AMP_RE.sub(lambda m: _AMP_ABBR[m.group(0)][key], text)
    text = _TITLE_PAIR_RE.sub(
        lambda m: f"{_TITLE_WORDS[m.group(1)][key]} {_AND[key]} {_TITLE_WORDS[m.group(2)][key]}",
        text,
    )
    text = _SECTOR_RE.sub(_say_sector, text)

    digits = _DIGIT_WORDS[key]
    text = _POSTCODE_RE.sub(
        lambda m: f"{_POSTAL_LABEL[key]} " + " ".join(digits[int(d)] for d in m.group(1)),
        text,
    )

    text = _ORDINAL_RE.sub(lambda m: _ORDINALS[m.group(1).lower()][key], text)
    for pattern, replacement in _CONTACT[key]:
        text = pattern.sub(replacement, text)
    if key == "en":
        text = _PREFIX_RE.sub(r"\1 ", text)
    return text
