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

Those three are what this module fixes, and nothing else. Every rule is verified by
``tests/test_urdu_normalise.py``.
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


def normalise_for_uplift(text: str, lang: str = "ur") -> str:
    """Rewrite an Urdu reply for the things Uplift mispronounces.

    Only runs on Urdu text. English replies keep Latin URLs and Roman numerals, which
    the voice handles acceptably in English mode and which the English number
    spell-out in ``server/providers/tts.py`` already covers.
    """
    if not text or lang != "ur" or not _ARABIC_RE.search(text):
        return text

    text = _ROMAN_RE.sub(_roman_to_digits, text)
    text = spoken_urls(text, "ur")
    text = _fix_slashes(text)
    return text
