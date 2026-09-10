"""Spoken-form fixes for the English reply, for gaps the Urdu passes do not cover.

The kiosk's other normalisers are either Urdu-only (``urdu_normalise``) or shared by
both languages (``addresses``, ``names``, ``spoken_formats``). What was left over is a
set of failures that only an English reply can have, because they are things Urdu text
simply does not contain: a bare ``%``, a word/word slash, an English legal suffix, a
Latin abbreviation, a clock time.

Every rule below was reproduced by running ``server.providers.tts._spoken`` over the
shapes that occur in ``server/data/mari_energies_knowledge_base.md``, and the counts in
the comments are occurrences in that file:

    "Up 33%"          → "thirty three%"        the sign was never spoken at all
    "AI/ML"           → "AI slash ML"          no English word-slash rule existed
    "Mari ... Ltd"    → "L T D"                read as three letters
    "w.e.f. July"     → letter soup
    "9:00 AM"         → "nine colon zero AM"

This runs AFTER ``spoken_addresses`` — which owns "MD/CEO" and the Islamabad sectors,
both slash-shaped — and BEFORE the number spell-out, so that "33%" is already
"33 percent" by the time the digits are read.
"""

from __future__ import annotations

import re

# ── 1. Percent ──────────────────────────────────────────────────────
# 33 occurrences, and the single clearest failure: the sign is not a word to any
# voice, so "33%" was handed over as "thirty three" followed by silence.
_PERCENT_RE = re.compile(r"\s*%")


# ── 2. Word/word slashes ────────────────────────────────────────────
# 65 slashes in the corpus. Eight are "MD/CEO", which voice_config.addresses has
# already rewritten by the time this runs; the rest are ordinary pairs — "AI/ML",
# "water/gas", "additions/revisions", "technical/commercial" — where the voice says
# the word "slash". This mirrors _fix_slashes in urdu_normalise.py, including its
# central exception: a slash between digits is a ratio or a date ("2024/25"), and
# rewriting it would change the meaning.
_WORD_SLASH_RE = re.compile(r"(?<=[A-Za-z])\s*/\s*(?=[A-Za-z])")

# "24/7" is the one numeric slash that is neither: it is an idiom, and "twenty
# four/seven" is how the voice read it. Handled before the digits are spelled out.
_24_7_RE = re.compile(r"\b24\s*/\s*7\b")


# ── 3. Clock times ──────────────────────────────────────────────────
# 12 colon-times, all office hours ("9:00 AM–5:00 PM"). The colon was read out, and
# ":00" became "zero". A round hour drops its minutes the way a speaker does.
# Minutes are [0-5]\d, not any two digits: without that bound this rule matched the
# "24:99" inside the debt ratio "0.24:99.76" and consumed it as a clock time.
_TIME_RE = re.compile(r"\b(\d{1,2}):([0-5]\d)\s*(AM|PM|am|pm)?")

# Opening hours are written "9:00 AM-5:00 PM" — a hyphen between two times, with no
# space around it. Nothing spoke that hyphen: the reply came out "nine AM five PM",
# two unconnected times rather than a span. The generic number-range rule cannot help,
# because by the time it runs the times either side are already words, not digits.
# Anchored to a meridiem on the left so an ordinary hyphenated word is never touched.
_TIME_RANGE_RE = re.compile(r"(?<=[AP]M)\s*[-–]\s*(?=\d{1,2}:[0-5]\d)", re.IGNORECASE)

# A ratio written with a colon and decimals on both sides — the debt-to-equity pairs,
# "0.24:99.76". Anchored to decimals so that a standard's revision ("ISO 9001:2015")
# and anything else colon-shaped is left for the reading it already gets.
_RATIO_RE = re.compile(r"(?<=\d)\s*:\s*(?=\d+\.\d)")


# ── 4. Legal and corporate suffixes ─────────────────────────────────
# "Ltd" 19×, "Pvt" 12×. Both are read letter by letter, and "Pvt" has no vowel to
# fall back on. The full words are what a person says out loud anyway.
_SUFFIXES = {
    r"\bLtd\b\.?": "Limited",
    r"\bPvt\b\.?": "Private",
    r"\bCo\.": "Company",
}


# ── 5. Latin abbreviations ──────────────────────────────────────────
# Low counts individually — "w.e.f." 4×, "e.g." and "vs." once each — but each one is
# unreadable rather than merely awkward, and the expansion is unambiguous.
_LATIN_ABBR = {
    r"\bw\.e\.f\.": "with effect from",
    r"\be\.g\.": "for example",
    r"\bi\.e\.": "that is",
    r"\bvs\.?(?=\s)": "versus",
    r"\betc\.": "et cetera",
    r"\bapprox\.": "approximately",
    r"\bincl\.": "including",
    # "GST No: 07-01-2710" — the colon form as well as the period form.
    r"\bNo[.:](?=\s*\d)": "number",
}

_SUFFIX_RULES = tuple((re.compile(p), r) for p, r in _SUFFIXES.items())
_ABBR_RULES = tuple((re.compile(p, re.IGNORECASE), r) for p, r in _LATIN_ABBR.items())


def _say_time(match: re.Match[str]) -> str:
    """"9:00 AM" → "9 AM"; "5:30 PM" → "5 30 PM". The colon is never spoken."""
    hour, minute, meridiem = match.group(1), match.group(2), match.group(3)
    said = hour if minute == "00" else f"{hour} {minute}"
    return f"{said} {meridiem}" if meridiem else said


def normalise_for_english(text: str, lang: str = "en") -> str:
    """Rewrite an English reply for the things only an English reply gets wrong.

    A no-op on Urdu, which reaches none of these shapes: it has no bare ``%``, no
    Latin legal suffix and no ``w.e.f.``, and its slashes are already handled by
    ``urdu_normalise._fix_slashes``.
    """
    if not text or lang == "ur":
        return text

    text = _24_7_RE.sub("24 7", text)
    text = _PERCENT_RE.sub(" percent", text)
    # Before _TIME_RE, which rewrites the times either side into words and would leave
    # the hyphen with no digits around it for this rule to see.
    text = _TIME_RANGE_RE.sub(" to ", text)
    text = _TIME_RE.sub(_say_time, text)
    text = _RATIO_RE.sub(" to ", text)
    for pattern, replacement in _SUFFIX_RULES:
        text = pattern.sub(replacement, text)
    for pattern, replacement in _ABBR_RULES:
        text = pattern.sub(replacement, text)
    # Last: the pairs above ("w.e.f.", "No:") must be settled before a stray slash
    # between two of their letters could be rewritten into an "and".
    return _WORD_SLASH_RE.sub(" and ", text)
