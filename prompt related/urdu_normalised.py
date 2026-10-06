"""Urdu text normalizer for TTS.

Converts English digits, numbers, common abbreviations, and symbols
that may appear in Urdu text into their Urdu script equivalents so
the MMS-TTS (or ElevenLabs) model can pronounce them correctly.

This acts as a safety net — the LLM system prompt already asks for
Urdu numerals, but models don't always comply.
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterable

# ── Arabic / Urdu script detection ──────────────────────────────────
_ARABIC_RE = re.compile(r"[\u0600-\u06FF\u0750-\u077F\uFB50-\uFDFF\uFE70-\uFEFF]")

# The LLM is told to write numbers in Western digits (0-9), but sometimes
# writes Urdu/Persian digit glyphs instead (e.g. "24/7" as Indic digits).
# Every digit-pattern regex below only matches ASCII digits, so an Indic
# form silently fails the phrase-level replacements (like "24/7") and falls
# through to the generic per-number converter -- which DOES handle Indic
# digits (Python's int() accepts them) but leaves literal symbols like "/"
# behind, which the TTS voice then reads aloud as "slash". Normalizing to
# ASCII digits up front fixes this for every rule at once.
_INDIC_DIGIT_MAP = str.maketrans(
    "\u0660\u0661\u0662\u0663\u0664\u0665\u0666\u0667\u0668\u0669"
    "\u06F0\u06F1\u06F2\u06F3\u06F4\u06F5\u06F6\u06F7\u06F8\u06F9",
    "01234567890123456789",
)

# The LLM sometimes writes round thousands with an English-style comma
# separator ("1,000", "3,000") instead of plain digits. The number regex
# below only matches contiguous digits, so a comma splits "1,000" into two
# separate matches: "1" and "000" -- and "000" alone evaluates to zero, so
# the result comes out as "\u0627\u06CC\u06A9\u060C\u0635\u0641\u0631" (one, zero) instead of "\u0627\u06CC\u06A9 \u06C1\u0632\u0627\u0631" (one
# thousand). Strip the separator commas before any other digit processing.
_THOUSANDS_SEPARATOR_RE = re.compile(r"(?<=\d),(?=\d{3}\b)")

# ── Urdu digit names (0-99) ─────────────────────────────────────────
_ONES: dict[int, str] = {
    0: "صفر",
    1: "ایک",
    2: "دو",
    3: "تین",
    4: "چار",
    5: "پانچ",
    6: "چھ",
    7: "سات",
    8: "آٹھ",
    9: "نو",
    10: "دس",
    11: "گیارہ",
    12: "بارہ",
    13: "تیرہ",
    14: "چودہ",
    15: "پندرہ",
    16: "سولہ",
    17: "سترہ",
    18: "اٹھارہ",
    19: "انیس",
    20: "بیس",
    21: "اکیس",
    22: "بائیس",
    23: "تئیس",
    24: "چوبیس",
    25: "پچیس",
    26: "چھبیس",
    27: "ستائیس",
    28: "اٹھائیس",
    29: "انتیس",
    30: "تیس",
    31: "اکتیس",
    32: "بتیس",
    33: "تینتیس",
    34: "چونتیس",
    35: "پینتیس",
    36: "چھتیس",
    37: "سینتیس",
    38: "اڑتیس",
    39: "انتالیس",
    40: "چالیس",
    41: "اکتالیس",
    42: "بیالیس",
    43: "تینتالیس",
    44: "چوالیس",
    45: "پینتالیس",
    46: "چھیالیس",
    47: "سینتالیس",
    48: "اڑتالیس",
    49: "انچاس",
    50: "پچاس",
    51: "اکاون",
    52: "باون",
    53: "تریپن",
    54: "چون",
    55: "پچپن",
    56: "چھپن",
    57: "ستاون",
    58: "اٹھاون",
    59: "انسٹھ",
    60: "ساٹھ",
    61: "اکسٹھ",
    62: "باسٹھ",
    63: "تریسٹھ",
    64: "چونسٹھ",
    65: "پینسٹھ",
    66: "چھیاسٹھ",
    67: "سڑسٹھ",
    68: "اڑسٹھ",
    69: "انہتر",
    70: "ستر",
    71: "اکہتر",
    72: "بہتر",
    73: "تیہتر",
    74: "چوہتر",
    75: "پچہتر",
    76: "چھہتر",
    77: "ستہتر",
    78: "اٹہتر",
    79: "اناسی",
    80: "اسی",
    81: "اکیاسی",
    82: "بیاسی",
    83: "تراسی",
    84: "چوراسی",
    85: "پچاسی",
    86: "چھیاسی",
    87: "ستاسی",
    88: "اٹھاسی",
    89: "نواسی",
    90: "نوے",
    91: "اکانوے",
    92: "بانوے",
    93: "ترانوے",
    94: "چورانوے",
    95: "پچانوے",
    96: "چھیانوے",
    97: "ستانوے",
    98: "اٹھانوے",
    99: "ننانوے",
}

# ── Scale words (South Asian numbering) ─────────────────────────────
_SCALES: list[tuple[int, str]] = [
    (10_00_00_00_000, "کھرب"),
    (1_00_00_00_000, "ارب"),
    (1_00_00_000, "کروڑ"),
    (1_00_000, "لاکھ"),
    (1_000, "ہزار"),
    (100, "سو"),
]


def _int_to_urdu(n: int) -> str:
    """Convert a non-negative integer to Urdu words."""
    if n < 0:
        return "منفی " + _int_to_urdu(-n)
    if n < 100:
        return _ONES[n]

    parts: list[str] = []
    for value, label in _SCALES:
        if n >= value:
            count = n // value
            n %= value
            if count == 1 and value == 100:
                parts.append(label)  # "سو" not "ایک سو"
            else:
                parts.append(f"{_int_to_urdu(count)} {label}")

    if n > 0:
        parts.append(_ONES[n])

    return " ".join(parts)


def _decimal_to_urdu(decimal_part: str) -> str:
    """Read the fractional part as a whole number, not digit-by-digit.

    Leading zeros are read individually so 0.05 ≠ 0.5.

        "98"  → "اٹھانوے"       (ninety-eight, not "nine eight")
        "05"  → "صفر پانچ"      (leading zero preserved)
        "982" → "نو سو بیاسی"
    """
    digits = "".join(d for d in decimal_part if d.isdigit())
    if not digits:
        return ""
    stripped = digits.lstrip("0")
    leading_zeros = len(digits) - len(stripped)
    words = [_ONES[0]] * leading_zeros
    if stripped:
        words.append(_int_to_urdu(int(stripped)))
    return " ".join(words)


def _number_to_urdu(text: str) -> str:
    """Convert a numeric string (integer or decimal) to Urdu words.

    Examples:
        "47"     → "سینتالیس"
        "1.6"    → "ایک اعشاریہ چھ"
        "99.98"  → "ننانوے اعشاریہ اٹھانوے"
    """
    if "." in text:
        integer_part, decimal_part = text.split(".", 1)
        int_val = int(integer_part) if integer_part else 0
        urdu_int = _int_to_urdu(int_val)
        urdu_decimal = _decimal_to_urdu(decimal_part)
        if not urdu_decimal:
            return urdu_int
        return f"{urdu_int} اعشاریہ {urdu_decimal}"

    return _int_to_urdu(int(text))


# ── Regex patterns ──────────────────────────────────────────────────
# "Sky 47" is the brand name, not a quantity — the generic number converter
# below turns "47" into the native-count word "سینتالیس", but the brand name
# is always spoken "Sky Forty Seven" (see _SKY47_SPOKEN).
# Must run before the generic number replacement.
#
# Uses explicit lookarounds instead of \b: Python's \b treats Arabic/Urdu
# letters as word characters, so "Sky 47" directly glued to a following
# Urdu word with no space (e.g. "Sky 47کا نمائندہ", a common LLM slip right
# where English switches back to Urdu script) would NOT have a boundary
# after "47" and the whole regex would silently fail to match -- falling
# through to the generic number converter below, which turns just the "47"
# into "سینتالیس" while "Sky" is left untouched (heard as "Sky" + "سینتالیس"
# instead of the intended "Sky Forty Seven"). Only Latin letters/digits on
# either side should block the match; Arabic script should not.
_SKY47_RE = re.compile(r"(?<![A-Za-z0-9])Sky\s*-?\s*47(?![A-Za-z0-9])", re.IGNORECASE)

# The single canonical spoken form of the brand -- deliberately LATIN script,
# even in an otherwise all-Urdu sentence.
#
# Urdu-script respellings were tried first and rejected by the client: both
# "سکائی فورٹی سیون" and the prosthetic-alif "اسکائی فورٹی سیون" come out
# mispronounced. Uplift reads plain English words embedded in Urdu text
# correctly, so the fix is the same one already used for "Managed" and
# "Sovereign" -- stop transliterating and let the English G2P handle it.
#
# Written out as words rather than "Sky47" because the digits would otherwise
# reach the generic number converter downstream.
_SKY47_SPOKEN = "Sky Forty Seven"

# The brand written in URDU script rather than Latin, which is what the system
# prompt actually asks the LLM for — so this, not _SKY47_RE above, is the form
# that shows up in the overwhelming majority of real output.
#
# Failures this fixes, all reported from live calls:
#   1) "سکائی 47" — the Latin-only _SKY47_RE never sees it, so the bare "47"
#      falls through to the generic number converter and is spoken as the
#      native count word "سینتالیس" ("forty-seven" as a quantity). That is the
#      "sky سینتالیس" the client heard.
#   2) "سکائی فورٹی سیون" / "اسکائی فورٹی سیون" — right words, but any
#      Urdu-script spelling of "Sky" is mispronounced by this voice.
#
# "سینتالیس" is included as an input alternative to catch the case where an
# earlier normalization pass (or the LLM itself) already converted the number.
# The optional leading alif covers both "سکائی" and "اسکائی".
_SKY47_URDU_RE = re.compile(r"ا?سکائی\s*(?:فورٹی\s*سیون|سینتالیس|47)")

# A bare Urdu-script "سکائی" with no number after it. In this domain the word
# only ever refers to the company, and the brand is never spoken as just
# "Sky" — it is always the full "Sky Forty Seven". Runs after _SKY47_URDU_RE so
# a form that already carries its number is handled by the more specific rule
# first, and excludes an immediately following "فورٹی"/"سیون" so a partial
# match can never double-expand.
_SKY_BARE_URDU_RE = re.compile(r"ا?سکائی(?!\s*(?:فورٹی|سیون|سینتالیس|47))")

# The Mari group (Sky47's parent companies: Mari Technologies, Mari Energies,
# Mari Petroleum, Mari Minerals) is ALWAYS written in Latin script and never
# transliterated -- the same rule the brand name itself follows.
#
# The LLM sometimes translates the name out of the knowledge base into Urdu
# instead of copying it verbatim, which is far worse than a merely clumsy
# transliteration: "میری" is the everyday Urdu word for "my", so
# "Mari Technologies" is heard as "MY Technologies", and "ماری" alone means
# "struck". Either way the company name disappears entirely.
#
# NOTE: an earlier version did the OPPOSITE -- it rewrote Latin "Mari" into
# "ماری" so Uplift's English G2P wouldn't read it as the English name "Mary".
# That respelling was removed deliberately: the client wants the group name in
# English script throughout. If "Mary" resurfaces in the audio, fix it with a
# LATIN respelling (e.g. "Maari") rather than by reintroducing Urdu script.
_MARI_SUFFIX_EN: dict[str, str] = {
    "ٹیکنالوجیز": "Technologies",
    "ٹیکنالوجی": "Technologies",
    "انرجیز": "Energies",
    "انرجی": "Energies",
    "منرلز": "Minerals",
    "منرل": "Minerals",
    "پیٹرولیم": "Petroleum",
}
# Longest-first so "ٹیکنالوجیز" is preferred over the shorter "ٹیکنالوجی".
_MARI_SUFFIX_ALT = "|".join(
    list(sorted(_MARI_SUFFIX_EN, key=len, reverse=True))
    + ["Technologies", "Energies", "Minerals", "Petroleum"]
)
# Requires a company suffix, so the ordinary Urdu words "میری" ("my") and
# "ماری" ("struck") are never touched on their own.
_MARI_URDU_RE = re.compile(
    rf"(?:میری|ماری|مری)\s*({_MARI_SUFFIX_ALT})", re.IGNORECASE
)

# Sky47's CEO's name must always be spoken as the Urdu transliteration
# "حسن عباس" -- Uplift's English G2P doesn't pronounce the Latin spelling
# well no matter how it's respelled, so Latin script is never wanted here at
# all. But the LLM sometimes hallucinates a different, wrong-sounding name
# instead ("ہسین عباس", i.e. "Husain Abbas"), and sometimes writes it in
# Latin script anyway. Catch known-wrong first-name variants (never "حسن"
# itself -- that one is correct and must be left alone) and force them back
# to the correct Urdu spelling, the same deterministic-backstop pattern used
# above for "Mari".
_HASSAN_ABBAS_WRONG_RE = re.compile(
    r"(?:حسین|ہسین|حسان|ہسن|ہسان)\s+عباس"
)

# Force the Latin spelling (in either the bare KB form "Hassan Abbas" or the
# earlier "Hassan Abbaas" pronunciation respelling) back to the Urdu
# transliteration -- Latin is never wanted for this name, only "حسن عباس".
_HASSAN_ABBAS_LATIN_RE = re.compile(
    r"(?<![A-Za-z0-9])Hassan\s+Abba+s(?![A-Za-z0-9])", re.IGNORECASE
)

# Sky47's Chairman is Retired Lieutenant General Anwar Ali Haider. The previous
# Chairman, Faheem Haider, has been removed from the knowledge base entirely --
# so any occurrence of that name in model output is now, by definition, a
# hallucination from the LLM's own priors rather than something it read in the
# retrieved context. Naming the wrong person as Chairman of the company is the
# single worst factual error this agent can make in front of a visitor, so it
# gets a deterministic backstop here rather than relying on the prompt alone.
# Both the Latin spelling and the Urdu transliterations the LLM invents for it
# are caught, and both collapse to the correct name.
_WRONG_CHAIRMAN_RE = re.compile(
    r"(?<![A-Za-z0-9])Faheem\s+Ha?[iy]?der(?![A-Za-z0-9])"
    r"|فہیم\s+حیدر",
    re.IGNORECASE,
)
_CHAIRMAN_NAME = "Anwar Ali Haider"

# Casual interjection openers the LLM sometimes slips in despite the system
# prompt guardrail (e.g. "ارے، سلام!"). Stripped only from the very first
# chunk of a new utterance (see urdu_text_tts_transform) so a legitimate
# mid-sentence "ارے" is never touched.
_LEADING_INTERJECTION_RE = re.compile(
    r"^\s*(?:ارے\s+واہ|اری\s+بھائی|ارے|اری|ہاں\s+تو)\s*[،,۔!؟]?\s*"
)


def strip_leading_interjection(text: str) -> str:
    """Remove a casual interjection opener from the start of an utterance."""
    return _LEADING_INTERJECTION_RE.sub("", text, count=1)


# ── Streaming cut safety ────────────────────────────────────────────
# Every rule in this file is a regex over a contiguous string, so a pattern is
# only recognized when all of its tokens are in the SAME chunk. The streaming
# transform below cuts the buffer at a whitespace boundary -- but whitespace is
# exactly what separates the tokens of "Sky 47", "Tier III/IV" and
# "(Managed Services)", so cutting there splits those patterns apart and each
# half then falls through to the wrong rule (or to Uplift untouched, which
# spells "III" out letter-by-letter as "I I I"). Holding back more characters
# does NOT help -- the cut always lands on a space no matter how far back it is.
#
# So: after picking a candidate cut, refuse it if the text about to be released
# ENDS with a token that could be the opening half of a multi-token pattern, and
# walk the cut further left until it's safe. Worst case the pattern is held back
# one extra token, which costs a few ms of latency and nothing else.
_CUT_GLUE_TAIL_RE = re.compile(
    r"(?:"
    r"[A-Za-z]*\d+"                            # "47", "24", "50", "Sky47" -> unit/brand/slash follows
    r"|Sky|Tier|Mari|Hassan|Abba+s"            # Latin pattern openers
    r"|Faheem|Anwar"                           # Chairman-name openers
    r"|ٹیئر|ٹائر|ٹائیر|ٹیئیر|ٹیر|تئیر"           # every Tier spelling (see _TIER_LABEL)
    r"|سکائی|اسکائی|فورٹی|این"                   # Urdu pattern openers ("این ویڈیا")
    r"|میری|ماری|مری"                            # Mari group ("... میری" | "ٹیکنالوجیز ...")
    r"|اسکیل|سکیل"                               # tagline "Scalable" ("اسکیل" | "ایبل" follows)
    r"|حسن|حسین|ہسین|حسان|ہسن|ہسان"             # CEO first-name variants ("... عباس" follows)
    r"|I{1,3}|IV|VI{0,3}|IX|X|XI{1,3}|XIV|XV|XVI{1,3}|XIX|XX"   # Roman numerals
    r"|MW|kW|KW|kWh|KWh|GB|TB|MB"              # units that trail a number
    r"|/"                                      # dangling slash ("24/" | "7")
    r")\s*$",
    re.IGNORECASE,
)

# If no safe cut exists we keep buffering, which would stall the stream forever
# on pathological input. Past this many characters, release at the plain
# whitespace cut and accept the (very unlikely) split.
_MAX_HELD_CHARS = 400


def find_safe_cut(buffer: str, min_tail: int) -> int:
    """Index to split ``buffer`` at without breaking a multi-token pattern.

    Returns -1 when the buffer should be held and re-checked after more input.
    """
    cut = buffer.rfind(" ", 0, len(buffer) - min_tail)
    fallback = cut

    while cut > 0:
        head = buffer[:cut]
        if (
            # not mid-pattern ("... Sky" | "47 ...")
            not _CUT_GLUE_TAIL_RE.search(head)
            # not inside an unclosed gloss ("... سروسز (Managed" | "Services) ...")
            and head.count("(") <= head.count(")")
            # not straddling a slash ("... hot" | "/cold ...")
            and not buffer[cut:].lstrip().startswith("/")
        ):
            return cut
        cut = buffer.rfind(" ", 0, cut)

    return fallback if len(buffer) > _MAX_HELD_CHARS else -1


# Drop a parenthetical gloss that trails a spelled-out form, so the avatar
# never speaks BOTH forms together, e.g. "سیکیورٹی آپریشنز سینٹر (SOC)" →
# "سیکیورٹی آپریشنز سینٹر", "ہواوی (Huawei)" → "ہواوی", or "منیجڈ سروسز
# (Managed Services)" → "منیجڈ سروسز". This covers short abbreviations
# (SOC, API), single English words the LLM glosses right after
# transliterating them into Urdu (Huawei, Series, Containerization), AND
# multi-word English terms/phrases (Managed Services, Data Center) -- either
# way the parenthetical is pure repetition of what was just said, not new
# information. An earlier version only matched a single token (no spaces),
# on the theory that a multi-word form in parentheses was more likely
# genuine new content -- but real UpliftAI output showed the LLM glossing
# whole multi-word terms this way too (e.g. after writing "منیجڈ سروسز",
# appending "(Managed Services)"), so multi-word Latin-script phrases are
# now stripped as well.
_PAREN_ABBR_RE = re.compile(r"\s*\(([A-Za-z][A-Za-z0-9 ./+&-]{0,60})\)")

# English loanwords that UpliftAI's Urdu voice mispronounces. Maps the spelling
# the LLM produces → a respelling the voice reads correctly. These are
# voice-specific and must be verified by listening to the live UpliftAI voice;
# add entries here as clients report more mispronounced words.
#
# NOTE: "Managed" was tried here as a phonetic Urdu respelling (مینِجڈ) but
# never sounded right despite several iterations (man-jid, mana-jid, ...).
# The fix instead lives in the system prompt: it's now on the "always keep in
# English script" list, so the LLM never transliterates it into Urdu at all —
# Uplift reads plain English words embedded in Urdu text correctly (same as
# it already does for the "Sky 47" brand name), so no respelling is needed.
#
# Each vendor name below is listed with BOTH its Latin spelling and the Urdu
# mis-transliterations the LLM invents for it, all collapsing to one verified
# Urdu spelling — the LLM is inconsistent about which script it uses for a
# given proper noun, so pinning only one form leaves the other broken.
_URDU_TTS_PRONUNCIATION_FIXES: dict[str, str] = {
    # "NVIDIA" (in-VID-ee-uh). Critically, it is all-caps, so WITHOUT an entry
    # here it falls through to _ENGLISH_ABBR_RE's acronym branch and is spelled
    # out letter-by-letter as "این وی آئی ڈی آئی اے" ("N-V-I-D-I-A") — verified
    # against the current normalizer. It's a word, not an acronym.
    "NVIDIA": "اِنویڈیا",
    "اینویڈیا": "اِنویڈیا",
    "این ویڈیا": "اِنویڈیا",
    "نویڈیا": "اِنویڈیا",
    # "Huawei" (HWAH-way). The LLM's usual transliteration "ہواوی" ends in a
    # ye that reads as "-wee" instead of "-way".
    "Huawei": "ہواوے",
    "ہواوی": "ہواوے",
    # "Kubernetes" (koo-ber-NET-eez). Too long for _ENGLISH_ABBR_RE to touch,
    # so the Latin spelling reaches Uplift's English G2P unchanged and comes
    # out with the stress in the wrong place.
    "Kubernetes": "کیوبرنیٹیز",
    "کیوبرنیٹس": "کیوبرنیٹیز",
    "کوبرنیٹیز": "کیوبرنیٹیز",
    "کبرنیٹیز": "کیوبرنیٹیز",
    "کبرنیٹس": "کیوبرنیٹیز",
}

# Each canonical spelling is also registered as a key mapping to ITSELF. That
# makes the pass idempotent, which it is not otherwise: a target can end with a
# shorter key ("اِنویڈیا" ends with "نویڈیا"), and the lookarounds below are
# deliberately Latin-only, so the leading "اِ" does not block the shorter key
# from matching inside the finished word — text already holding the correct
# spelling would be rewritten into "اِاِنویڈیا", compounding on every pass.
# Registering the canonical form means longest-first ordering matches it first
# and rewrites it to itself. Derived automatically so adding a term later can't
# reintroduce the bug.
#
# re.IGNORECASE means the matched text may differ in case from the key
# ("Nvidia" vs "NVIDIA"), so the lookup is keyed case-insensitively.
_PRONUNCIATION_FIX_LOOKUP: dict[str, str] = {
    **{canonical.casefold(): canonical
       for canonical in _URDU_TTS_PRONUNCIATION_FIXES.values()},
    **{spelling.casefold(): replacement
       for spelling, replacement in _URDU_TTS_PRONUNCIATION_FIXES.items()},
}

# Applied as ONE alternation in a single pass rather than a replace-per-entry
# loop, so a substitution is never re-scanned by a later entry, and so that
# longest-key-first ordering picks the most specific spelling when two keys
# overlap ("اینویڈیا" before "نویڈیا").
#
# The lookarounds are Latin-only on purpose (see _SKY47_RE): Arabic script must
# stay allowed on both sides so "NVIDIAکے" — the LLM's common no-space switch
# back into Urdu — still matches.
_PRONUNCIATION_FIX_RE: re.Pattern[str] | None = (
    re.compile(
        r"(?<![A-Za-z0-9])("
        + "|".join(
            re.escape(spelling)
            for spelling in sorted(_PRONUNCIATION_FIX_LOOKUP, key=len, reverse=True)
        )
        + r")(?![A-Za-z0-9])",
        re.IGNORECASE,
    )
    if _PRONUNCIATION_FIX_LOOKUP  # an empty join would match the empty string everywhere
    else None
)

# Some terms sound wrong no matter how they're spelled in Urdu script, so the
# system prompt tells the LLM to always write them in English instead. But
# prompt instructions aren't 100% reliable — the LLM sometimes transliterates
# them into Urdu script anyway (e.g. "Managed" -> "مینجڈ"). This is a
# deterministic backstop: catch the LLM's own Urdu spellings of these specific
# terms and force them back to English so Uplift pronounces them correctly
# (the same way it already handles English words like the "Sky 47" brand name).
# Verified against real LLM output; add more variants here as they're observed.
_FORCE_ENGLISH_TERMS: dict[str, str] = {
    "مینجڈ": "Managed",
    "مینیجڈ": "Managed",
    "مینجمنٹ": "Management",
    "مینیجمنٹ": "Management",
    "کنٹینرائزڈ": "Containerized",
    "کنٹینرائزیشن": "Containerization",
    # "Sovereign" -- core to Sky47's own positioning ("sovereign digital
    # infrastructure"), so it comes up often. The LLM's self-invented
    # transliteration is garbled/unpronounceable ("سوزورن"); catch the
    # observed spelling plus plausible variants.
    "سوزورن": "Sovereign",
    "سورورن": "Sovereign",
    "ساورن": "Sovereign",
    "سوزرن": "Sovereign",
    "سوورن": "Sovereign",
    "ساورین": "Sovereign",
    # "Colocation" -- one of Sky47's five core service pillars (Sky47 Space).
    # The LLM's self-invented transliteration splits the word in a way that
    # reads as the unrelated, much more common loanword "لوکیشن" ("location")
    # with a stray "کو" ("to"/"co") in front, so it comes out sounding like
    # "to location" instead of "Colocation" -- and risks being confused with
    # plain "location" rather than the specific colocation service in the RAG
    # knowledge base. Catch both the spaced and unspaced spellings.
    "کو لوکیشن": "Colocation",
    "کولوکیشن": "Colocation",
}

# The company tagline "Secure. Scalable. Sovereign." is always spoken in
# English -- its Urdu transliterations are mispronounced by the voice. These
# force the transliterated forms of "Secure" and "Scalable" back to English
# ("Sovereign" is already covered by _FORCE_ENGLISH_TERMS above).
#
# Kept as regexes, NOT _FORCE_ENGLISH_TERMS substring entries, specifically
# because "سیکیور" (Secure) is a prefix of the unrelated, legitimate word
# "سیکیورٹی" (Security) -- used elsewhere, e.g. the SECaaS expansion "سیکیورٹی
# ایز اے سروس". A plain substring replace would corrupt it into "Secureٹی".
# The trailing lookahead excludes a following Urdu LETTER so only the
# standalone word matches -- but NOT the whole Arabic block `[؀-ۿ]`, because
# that block also holds the punctuation ("۔"، "،") that ends the tagline;
# guarding against those would stop "سیکیور۔" (Secure.) from ever matching.
# `_URDU_LETTER` is letters only.
#
# Ordered longest-first: "Scalability" before "Scalable" so the shorter word's
# regex can't consume the stem and strand the "ٹی" suffix.
_URDU_LETTER = "ء-يٹ-ۓەۺ-ۿ"
_TAGLINE_WORD_FIXES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"ا?سکیل\s*ایبلٹی"), "Scalability"),
    (re.compile(r"ا?سکیلیبلٹی"), "Scalability"),
    (re.compile(r"ا?سکیل\s*ایبل"), "Scalable"),
    (re.compile(r"ا?سکیلیبل"), "Scalable"),
    (re.compile(rf"سیکیور(?![{_URDU_LETTER}])"), "Secure"),
    (re.compile(rf"سکیور(?![{_URDU_LETTER}])"), "Secure"),
]


# Hyphenated / spaced spellings of the "as a Service" family. The knowledge
# base and the LLM both write these inconsistently ("AIaaS", "AI-aaS",
# "GPU-as-a-Service", "Security-as-a-Service"), and only the unhyphenated
# single-token form is in _ABBR_MAP. A hyphen splits the token, so "AI-aaS"
# reaches _ENGLISH_ABBR_RE as two pieces: "AI" (expanded to "اے آئی") plus a
# stray "aaS" that matches nothing and is handed to Uplift raw. Collapse both
# spellings to their canonical form first so the map lookup can do its job.
_AAS_JOIN_RE = re.compile(r"(?<![A-Za-z0-9])([A-Za-z]{1,6})[\s-]+aaS(?![A-Za-z0-9])")
_AS_A_SERVICE_HYPHEN_RE = re.compile(r"[\s-]as[\s-]a[\s-]Service(?![A-Za-z0-9])", re.IGNORECASE)

# "24/7" → special phrase (must run before generic number replacement)
# Lookarounds instead of \b — see _SKY47_RE comment: Arabic letters count as
# \w, so "24/7" glued to a following Urdu word with no space would otherwise
# silently fail to match.
_24_7_RE = re.compile(r"(?<![A-Za-z0-9])24\s*/\s*7(?![A-Za-z0-9])")

# Data-center Tier classifications — must run before the generic Roman-numeral
# and number replacers to avoid "III" being consumed as a bare abbreviation.
# Ordered longest-match first: "III/IV" before "III" and "IV".
#
# Lookarounds instead of \b — see _SKY47_RE comment: without this, "Tier
# III/IV" directly glued to a following Urdu word (e.g. "Tier III/IVکا",
# no space) would have no boundary after "IV" and the whole match would
# silently fail, leaving the Roman numerals to fall through untouched to
# Uplift's own TTS engine, which reads them out letter-by-letter.
# Tier numbers are always spoken as ENGLISH loanwords ("ٹیئر تھری", "ٹیئر فور"),
# never as the native Urdu count words ("ٹیئر تین", "ٹیئر چار"). "Tier 3" is a
# proper classification name, not a quantity of three things, so the native
# count word sounds wrong the same way "Sky سینتالیس" does for the brand.
_ENGLISH_NUMBER_URDU: dict[int, str] = {
    1: "ون", 2: "ٹو", 3: "تھری", 4: "فور", 5: "فائیو",
    6: "سکس", 7: "سیون", 8: "ایٹ", 9: "نائن", 10: "ٹین",
    11: "الیون", 12: "ٹویلو", 13: "تھرٹین", 14: "فورٹین", 15: "ففٹین",
    16: "سکسٹین", 17: "سیونٹین", 18: "ایٹھین", 19: "نائنٹین", 20: "ٹوئنٹی",
}

# Accepts the tier number as a Roman numeral OR an Arabic digit, optionally as
# a slash pair ("Tier III/IV", "Tier 3/4"). The digit form matters: the system
# prompt tells the LLM to write numbers as Western digits, so "Tier 3" is a
# form it produces regularly -- and an earlier version of this regex matched
# Roman numerals only, letting the bare "3" fall through to the generic number
# converter below and come out as the native count word "تین".
#
# `\s*` rather than `\s+` after the label so "Tier3"/"ٹیئر3" (no space) matches.
# Alternation is ordered longest-first ("III" before "II" before "I", "IV"
# before "I") because Python's alternation is first-match, not longest-match.
#
# Lookarounds instead of \b — see _SKY47_RE comment: without this, "Tier
# III/IV" directly glued to a following Urdu word (e.g. "Tier III/IVکا",
# no space) would have no boundary after "IV" and the whole match would
# silently fail, leaving the Roman numerals to fall through untouched to
# Uplift's own TTS engine, which reads them out letter-by-letter.
_TIER_TOKEN = r"III|IV|II|I|[1-9]|1[0-9]|20"

# The LLM transliterates "Tier" into Urdu inconsistently, and only ONE of its
# spellings is pronounced correctly by Uplift: "ٹیئر". The others are actively
# wrong rather than merely clumsy -- "ٹائر" is the ordinary Urdu word for
# "tyre", so a Tier III data center is announced as a *tyre* three data center.
# Every observed variant is listed here and all of them are rewritten to the
# one correct spelling. Kept as a shared constant because three separate
# patterns below must stay in sync with it; when they drifted apart, the
# streaming cut-guard didn't know about "ٹائر" and split it off from its
# numeral, which stranded the label unconverted.
_TIER_LABEL = r"Tier|ٹیئر|ٹائر|ٹائیر|ٹیئیر|ٹیر|تئیر|ٹِیئر"
_TIER_SPOKEN = "ٹیئر"

_TIER_RE = re.compile(
    rf"(?<![A-Za-z0-9])(?:{_TIER_LABEL})\s*"
    rf"({_TIER_TOKEN})"
    rf"(?:\s*/\s*({_TIER_TOKEN}))?"
    r"(?![A-Za-z0-9])",
    re.IGNORECASE,
)

# A tier label with no number after it -- either the LLM wrote it bare, or a
# streaming chunk boundary separated it from its numeral despite the cut-guard.
# Without this the wrong spelling survives to TTS on its own ("ٹائر" -> "tyre").
# Runs after _TIER_RE so a label that still has its number is handled by the
# more specific rule first. "Tier" in Latin is excluded: Uplift reads the
# English word correctly, and rewriting it would fight the system prompt's
# keep-English-terms-in-English rule.
# Lookarounds exclude Arabic script on both sides so a short variant like "ٹیر"
# can only match as a standalone word, never inside a longer unrelated one.
_TIER_BARE_LABEL_RE = re.compile(
    r"(?<![؀-ۿ])(?:ٹائیر|ٹیئیر|ٹائر|ٹیر|تئیر|ٹِیئر)(?![؀-ۿ])"
)

# Bare Roman numerals (no "Tier"/"ٹیئر" immediately before them, e.g. the LLM
# refers back to a tier already established earlier in the conversation).
# Without this, they'd fall through to the generic abbreviation handler,
# which treats any unrecognized all-caps token as an acronym and spells it
# out letter-by-letter ("III" -> "I I I" instead of "three"). Runs AFTER
# _TIER_RE so "Tier III/IV" is already handled by the time this applies.
#
# Lookarounds instead of \b — see _SKY47_RE comment: a bare "III"/"IV" glued
# to a following Urdu word with no space (e.g. "IIIکا") would otherwise have
# no boundary and fall through untouched, which is exactly the
# letter-by-letter mispronunciation this regex exists to prevent.
_BARE_ROMAN_RE = re.compile(
    r"(?<![A-Za-z0-9])(II|III|IV|V|VI|VII|VIII|IX|X|XI|XII|XIII|XIV|XV|XVI|XVII|XVIII|XIX|XX)(?![A-Za-z0-9])"
)
_ROMAN_NUMERAL_VALUES: dict[str, int] = {
    "II": 2, "III": 3, "IV": 4, "V": 5, "VI": 6, "VII": 7, "VIII": 8,
    "IX": 9, "X": 10, "XI": 11, "XII": 12, "XIII": 13, "XIV": 14,
    "XV": 15, "XVI": 16, "XVII": 17, "XVIII": 18, "XIX": 19, "XX": 20,
}


def _tier_number_word(token: str) -> str:
    """Spoken Urdu form of a tier number, given a Roman numeral or a digit.

    Always the English loanword ("تھری"), never the native count word ("تین") --
    see _ENGLISH_NUMBER_URDU.
    """
    upper = token.upper()
    value = _ROMAN_NUMERAL_VALUES.get(upper, 1 if upper == "I" else None)
    if value is None:
        value = int(token) if token.isdigit() else 0
    return _ENGLISH_NUMBER_URDU.get(value, token)

# Catch-all for a bare "/" left between two tokens after every more specific
# slash pattern above (24/7, Tier III/IV) has already had its chance to run.
# Uplift's Urdu voice has no native reading for "/" — it falls back to the
# English loanword "سلیش" ("slash"), which is read out loud for ANY leftover
# slash, not just numbers (e.g. "hot/cold" -> "ہاٹ سلیش کولڈ", or "24/7" ->
# "چوبیس سلیش سات" if it ever reaches this point un-replaced, such as when a
# streaming chunk boundary splits "24" and "/7" apart before _24_7_RE gets to
# see them together). "/" between two alternatives is read naturally in
# speech as "or" ("یا"), so replace it with that instead of leaving the raw
# symbol for Uplift to spell out. Deliberately generic (\w matches Arabic
# script too, same as Python's \b elsewhere in this file) so it also catches
# Urdu-only pairs like "گرم/ٹھنڈا". Only one slash per match is handled --
# chained slashes ("a/b/c") only get the first pair converted, which is an
# acceptable gap since that pattern doesn't occur in this domain outside the
# already-specially-handled "Tier III/IV".
_GENERIC_SLASH_RE = re.compile(r"(\w+)\s*/\s*(\w+)")

# Number with optional decimal, optionally followed by % or unit (MW, kW, GB, etc.)
# The space + unit are matched together as a single optional group so that when
# there is NO unit, the trailing space is left intact — otherwise "47 لوگ" would
# collapse to "سینتالیسلوگ" (words with no gap, which TTS runs together).
#
# Leading lookbehind instead of \b: Arabic/Urdu letters count as \w in Python's
# regex, so a number glued directly after an Urdu word with no space (e.g.
# "کا47") would have no boundary and silently fail to match otherwise.
_NUMBER_UNIT_RE = re.compile(
    r"(?<![A-Za-z0-9])(\d+(?:\.\d+)?)(?:\s*(%|٪|MW|kW|KW|GB|TB|MB|kWh|KWh))?\+?(?![A-Za-z0-9])"
)

# Standalone English letter sequences (abbreviations like AI, IoT, CEO)
# Increased max to 8 to catch longer abbrs like GPUaaS
#
# Lookarounds instead of \b — same reason as _NUMBER_UNIT_RE above: an
# abbreviation glued to Urdu script on either side (e.g. "کاAI" or "AIکا")
# would otherwise have no boundary and pass through unexpanded.
_ENGLISH_ABBR_RE = re.compile(r"(?<![A-Za-z0-9])([A-Za-z][A-Za-z0-9]{0,7})(?![A-Za-z0-9])")

# ── Common English abbreviations → Urdu phonetic ───────────────────
_ABBR_MAP: dict[str, str] = {
    "AI": "اے آئی",
    "IoT": "آئی او ٹی",
    "IOT": "آئی او ٹی",
    "IT": "آئی ٹی",
    "VIP": "وی آئی پی",
    "API": "اے پی آئی",
    "CEO": "سی ای او",
    "CTO": "سی ٹی او",
    "CFO": "سی ایف او",
    "COO": "سی او او",
    "HR": "ایچ آر",
    "PR": "پی آر",
    "HTML": "ایچ ٹی ایم ایل",
    "CSS": "سی ایس ایس",
    "URL": "یو آر ایل",
    "GPS": "جی پی ایس",
    "SIM": "سم",
    "SMS": "ایس ایم ایس",
    "WiFi": "وائی فائی",
    "WIFI": "وائی فائی",
    "OK": "اوکے",
    "PDF": "پی ڈی ایف",
    "USB": "یو ایس بی",
    "RAM": "ریم",
    "ROM": "روم",
    "CPU": "سی پی یو",
    "GPU": "جی پی یو",
    # ── "…aaS" service acronyms ──
    # All of these end in "as a Service" and must be spoken that way in full
    # ("ایز اے سروس"). Without an entry here they fall through to
    # _ENGLISH_ABBR_RE: the mixed-case spelling fails its `word.isupper()`
    # acronym check, so the raw Latin token reaches Uplift and is read as a
    # nonsense syllable. Both the mixed-case spelling and the all-caps variant
    # are registered, since the LLM is inconsistent about which it writes.
    "SaaS": "سافٹ ویئر ایز اے سروس",
    "SAAS": "سافٹ ویئر ایز اے سروس",
    "IaaS": "انفراسٹرکچر ایز اے سروس",
    "IAAS": "انفراسٹرکچر ایز اے سروس",
    "PaaS": "پلیٹ فارم ایز اے سروس",
    "PAAS": "پلیٹ فارم ایز اے سروس",
    "STaaS": "اسٹوریج ایز اے سروس",
    "STAAS": "اسٹوریج ایز اے سروس",
    "NaaS": "نیٹ ورک ایز اے سروس",
    "NAAS": "نیٹ ورک ایز اے سروس",
    "BaaS": "بیک اپ ایز اے سروس",
    "BAAS": "بیک اپ ایز اے سروس",
    "DRaaS": "ڈیزاسٹر ریکوری ایز اے سروس",
    "DRAAS": "ڈیزاسٹر ریکوری ایز اے سروس",
    "SECaaS": "سیکیورٹی ایز اے سروس",
    "SECAAS": "سیکیورٹی ایز اے سروس",
    "AIaaS": "اے آئی ایز اے سروس",
    "AIAAS": "اے آئی ایز اے سروس",
    "ERP": "ای آر پی",
    "CRM": "سی آر ایم",
    "UI": "یو آئی",
    "UX": "یو ایکس",
    "ML": "ایم ایل",
    "NLP": "این ایل پی",
    "KPI": "کے پی آئی",
    "ROI": "آر او آئی",
    "B2B": "بی ٹو بی",
    "B2C": "بی ٹو سی",
    "QA": "کیو اے",
    "DevOps": "ڈیو آپس",
    "DEVOPS": "ڈیو آپس",
    "AWS": "اے ڈبلیو ایس",
    "GCP": "جی سی پی",
    "MVP": "ایم وی پی",
    "FAQ": "ایف اے کیو",
    "SEO": "ایس ای او",
    "LLC": "ایل ایل سی",
    "USD": "یو ایس ڈی",
    "PKR": "پی کے آر",
    # ── Sky47 / data-center domain ──
    "DCIM": "ڈی سی آئی ایم",
    "BMS": "بی ایم ایس",
    "SLA": "ایس ایل اے",
    # When the LLM writes the ABBREVIATION "NOC"/"SOC" it is spoken as a single
    # word ("nok"/"sok"), not spelled out letter-by-letter ("این او سی"). The
    # Urdu spellings below are real dictionary words the voice pronounces
    # cleanly (نوک = "point/tip", سوک chosen to rhyme). Verified spelling choice
    # with the client; adjust here if the live voice needs a different vowel.
    # The full form ("Network Operations Center") is intentionally left alone --
    # the LLM may use it when a caller needs the term explained.
    "NOC": "نوک",
    "SOC": "سوک",
    "HPC": "ایچ پی سی",
    "ISP": "آئی ایس پی",
    "SSD": "ایس ایس ڈی",
    "IOPS": "آئی او پی ایس",
    "RFID": "آر ایف آئی ڈی",
    "CCTV": "سی سی ٹی وی",
    "ISO": "آئی ایس او",
    "GPUaaS": "جی پی یو ایز اے سروس",
    "GPUAAS": "جی پی یو ایز اے سروس",
    "XaaS": "ایوری تھنگ ایز اے سروس",
    "XAAS": "ایوری تھنگ ایز اے سروس",
    "TAT": "ٹی اے ٹی",
    "FIFA": "فیفا",
    "VLAN": "وی لین",
    "VPN": "وی پی این",
    "DNS": "ڈی این ایس",
    "CDN": "سی ڈی این",
    "DDoS": "ڈی ڈاس",
    "DDOS": "ڈی ڈاس",
    "CISO": "سی آئی ایس او",
    "CIO": "سی آئی او",
    "VP": "وی پی",
}

# ── English letter → Urdu phonetic (for spelling out unknown abbrs) ─
_LETTER_URDU: dict[str, str] = {
    "A": "اے",
    "B": "بی",
    "C": "سی",
    "D": "ڈی",
    "E": "ای",
    "F": "ایف",
    "G": "جی",
    "H": "ایچ",
    "I": "آئی",
    "J": "جے",
    "K": "کے",
    "L": "ایل",
    "M": "ایم",
    "N": "این",
    "O": "او",
    "P": "پی",
    "Q": "کیو",
    "R": "آر",
    "S": "ایس",
    "T": "ٹی",
    "U": "یو",
    "V": "وی",
    "W": "ڈبلیو",
    "X": "ایکس",
    "Y": "وائی",
    "Z": "زیڈ",
}


# ── Unit suffixes → Urdu ────────────────────────────────────────────
_UNIT_MAP: dict[str, str] = {
    "%": "فیصد",
    "٪": "فیصد",
    "MW": "میگا واٹ",
    "kW": "کلو واٹ",
    "KW": "کلو واٹ",
    "kWh": "کلو واٹ آور",
    "KWh": "کلو واٹ آور",
    "GB": "جی بی",
    "TB": "ٹی بی",
    "MB": "ایم بی",
}


def _spell_out(word: str) -> str:
    """Spell out an English abbreviation letter-by-letter in Urdu."""
    return " ".join(_LETTER_URDU.get(ch.upper(), ch) for ch in word)


def _is_all_caps_or_known_abbr(word: str) -> bool:
    """Return True if the word looks like an abbreviation (all-caps or in map)."""
    return word in _ABBR_MAP or (word.isupper() and len(word) >= 2)


# ═══════════════════════════════════════════════════════════════════════
# Public API
# ═══════════════════════════════════════════════════════════════════════


def normalize_urdu_text(
    text: str, *, assume_urdu: bool = False
) -> tuple[str, list[tuple[str, str]]]:
    """Normalize English numerics and abbreviations in Urdu text.

    Only activates when the text contains Arabic/Urdu script characters, so the
    English agent's output is never Urdu-ized.

    That check is per-call, which is wrong for a STREAM: a single Urdu utterance
    routinely contains runs of consecutive Latin-only chunks ("... certified
    Tier III/IV Data Center Facility ..."), and those chunks would skip
    normalization entirely even though the utterance around them is Urdu -- the
    exact reason "Tier III/IV" was intermittently spelled out letter-by-letter.
    ``assume_urdu`` lets the streaming caller latch the decision once for the
    whole utterance instead of re-deciding it per chunk.

    Returns:
        (normalized_text, list_of_changes) where each change is (original, replacement).
    """
    if not text or (not assume_urdu and not _ARABIC_RE.search(text)):
        return text, []

    changes: list[tuple[str, str]] = []

    # -1) Normalize any Indic digit glyphs to ASCII digits FIRST, so every
    # digit-pattern rule below (24/7, Sky 47, numbers, %, units) works
    # uniformly regardless of which digit form the LLM used. str.translate()
    # is cheap even when there's nothing to replace, so just always run it
    # (NOTE: an earlier version pre-checked membership via `ch in
    # _INDIC_DIGIT_MAP`, but maketrans() dicts are keyed by codepoint *ints*,
    # not characters, so that check silently always evaluated False).
    translated = text.translate(_INDIC_DIGIT_MAP)
    if translated != text:
        changes.append((text, translated))
        text = translated

    # -1b) Strip thousands-separator commas ("1,000" -> "1000") for the same
    # reason as above -- see _THOUSANDS_SEPARATOR_RE comment.
    de_commaed = _THOUSANDS_SEPARATOR_RE.sub("", text)
    if de_commaed != text:
        changes.append((text, de_commaed))
        text = de_commaed

    # 0aa) Drop "(gloss)" parentheticals so the avatar never speaks the
    # Urdu/English form AND the parenthetical repeat together (e.g.
    # "... سینٹر (SOC)" → "... سینٹر", "ہواوی (Huawei)" → "ہواوی").
    #
    # Runs FIRST, on the raw text the LLM produced, because it is the only rule
    # here that keys off Latin script INSIDE the parentheses. Any rule that
    # rewrites Latin into Urdu must come after it: when the vendor-pronunciation
    # pass below ran first, it turned "ہواوی (Huawei)" into "ہواوے (ہواوے)",
    # which this regex no longer matches -- so the avatar said the name twice,
    # the exact repetition this rule exists to prevent.
    def _strip_paren_abbr(m: re.Match[str]) -> str:
        changes.append((m.group(0).strip(), ""))
        return ""

    text = _PAREN_ABBR_RE.sub(_strip_paren_abbr, text)

    # 0) Fix known loanword mispronunciations (voice-specific respellings).
    # Must run BEFORE _ENGLISH_ABBR_RE (step 2), which would otherwise treat an
    # all-caps vendor name like "NVIDIA" as an acronym and spell it out.
    if _PRONUNCIATION_FIX_RE is not None:

        def _replace_pronunciation(m: re.Match[str]) -> str:
            replacement = _PRONUNCIATION_FIX_LOOKUP[m.group(1).casefold()]
            if replacement != m.group(0):  # skip the canonical self-mappings
                changes.append((m.group(0), replacement))
            return replacement

        text = _PRONUNCIATION_FIX_RE.sub(_replace_pronunciation, text)

    # 0a2) Force specific terms back to English when the LLM transliterated
    # them into Urdu script despite the system prompt telling it not to.
    for urdu_spelling, english in _FORCE_ENGLISH_TERMS.items():
        if urdu_spelling in text:
            text = text.replace(urdu_spelling, english)
            changes.append((urdu_spelling, english))

    # 0a2b) Tagline words "Secure"/"Scalable" back to English (see
    # _TAGLINE_WORD_FIXES). Regex-based, not substring, to avoid corrupting
    # "سیکیورٹی" (Security).
    for pattern, english in _TAGLINE_WORD_FIXES:
        def _replace_tagline(m: re.Match[str], eng: str = english) -> str:
            changes.append((m.group(0), eng))
            return eng

        text = pattern.sub(_replace_tagline, text)

    # 0a3) Collapse hyphenated/spaced "as a Service" spellings so the acronym
    # map below sees the single-token form it is keyed on.
    def _join_aas(m: re.Match[str]) -> str:
        joined = f"{m.group(1)}aaS"
        changes.append((m.group(0), joined))
        return joined

    text = _AAS_JOIN_RE.sub(_join_aas, text)

    # Whatever "as a Service" tail survives -- whether it was hyphenated
    # ("GPU-as-a-Service") or already spaced ("Infrastructure as a Service",
    # copied verbatim out of the knowledge base) -- becomes the Urdu spoken
    # form, so it matches the _ABBR_MAP expansions above instead of leaving
    # half the term in Latin script mid-Urdu-sentence.
    de_hyphenated = _AS_A_SERVICE_HYPHEN_RE.sub(" ایز اے سروس", text)
    if de_hyphenated != text:
        changes.append((text, de_hyphenated))
        text = de_hyphenated

    # 0a1) Undo any Urdu translation of the Mari group's names, so the company
    # name is never lost to the homograph "میری" ("my"). See _MARI_URDU_RE.
    def _restore_mari(m: re.Match[str]) -> str:
        suffix = m.group(1)
        english = _MARI_SUFFIX_EN.get(suffix, suffix.title())
        replacement = f"Mari {english}"
        changes.append((m.group(0), replacement))
        return replacement

    text = _MARI_URDU_RE.sub(_restore_mari, text)

    # 0a1c) Correct a hallucinated wrong name back to the real CEO's name,
    # in Urdu script (see _HASSAN_ABBAS_WRONG_RE comment).
    def _replace_hassan_abbas_wrong(m: re.Match[str]) -> str:
        changes.append((m.group(0), "حسن عباس"))
        return "حسن عباس"

    text = _HASSAN_ABBAS_WRONG_RE.sub(_replace_hassan_abbas_wrong, text)

    # 0a1d) Force the Latin spelling back to Urdu (see _HASSAN_ABBAS_LATIN_RE
    # comment) -- Latin script is never wanted for this name.
    def _replace_hassan_abbas_latin(m: re.Match[str]) -> str:
        changes.append((m.group(0), "حسن عباس"))
        return "حسن عباس"

    text = _HASSAN_ABBAS_LATIN_RE.sub(_replace_hassan_abbas_latin, text)

    # 0a1e) Replace the former Chairman's name with the current one -- see
    # _WRONG_CHAIRMAN_RE.
    def _replace_wrong_chairman(m: re.Match[str]) -> str:
        changes.append((m.group(0), _CHAIRMAN_NAME))
        return _CHAIRMAN_NAME

    text = _WRONG_CHAIRMAN_RE.sub(_replace_wrong_chairman, text)

    # 0a) Force every spelling of the brand to the one canonical spoken form,
    # before the generic number converter turns a trailing "47" into the native
    # count word "سینتالیس". Latin first, then the Urdu-script forms the LLM
    # actually produces most of the time, then a bare "سکائی" with no number.
    def _replace_sky47(m: re.Match[str]) -> str:
        if m.group(0) != _SKY47_SPOKEN:  # skip text already in canonical form
            changes.append((m.group(0), _SKY47_SPOKEN))
        return _SKY47_SPOKEN

    text = _SKY47_RE.sub(_replace_sky47, text)
    text = _SKY47_URDU_RE.sub(_replace_sky47, text)
    text = _SKY_BARE_URDU_RE.sub(_replace_sky47, text)

    # 0) Replace "24/7" with a natural Urdu phrase
    def _replace_24_7(m: re.Match[str]) -> str:
        changes.append((m.group(0), "چوبیس گھنٹے سات دن"))
        return "چوبیس گھنٹے سات دن"

    text = _24_7_RE.sub(_replace_24_7, text)

    # 0b) Replace "Tier III" / "Tier 3" / "Tier III/IV" with the English
    # loanword form ("ٹیئر تھری"), never the native count word ("ٹیئر تین").
    # A slash pair is spoken as "یا" ("or"), matching how it reads aloud.
    def _replace_tier(m: re.Match[str]) -> str:
        first = _tier_number_word(m.group(1))
        second = _tier_number_word(m.group(2)) if m.group(2) else None
        replacement = (
            f"{_TIER_SPOKEN} {first} یا {second}" if second
            else f"{_TIER_SPOKEN} {first}"
        )
        changes.append((m.group(0), replacement))
        return replacement

    text = _TIER_RE.sub(_replace_tier, text)

    # 0b2) Fix any tier label left without a number (see _TIER_BARE_LABEL_RE).
    def _replace_bare_tier_label(m: re.Match[str]) -> str:
        changes.append((m.group(0), _TIER_SPOKEN))
        return _TIER_SPOKEN

    text = _TIER_BARE_LABEL_RE.sub(_replace_bare_tier_label, text)

    # 0c) Convert any remaining bare Roman numerals (no "Tier"/"ٹیئر" prefix)
    # so they don't fall through to the generic abbreviation handler and get
    # spelled out letter-by-letter instead.
    #
    # Uses the ENGLISH loanword form, not the native count word. In this domain
    # a bare Roman numeral is essentially always a back-reference to a tier
    # established earlier in the conversation ("... اور IV بھی"), so the native
    # count word produced the exact "ٹیئر تین / ٹیئر چار" mismatch the tier rule
    # above exists to avoid -- correct when the label was attached, wrong the
    # moment the LLM dropped it.
    def _replace_bare_roman(m: re.Match[str]) -> str:
        replacement = _tier_number_word(m.group(1))
        changes.append((m.group(0), replacement))
        return replacement

    text = _BARE_ROMAN_RE.sub(_replace_bare_roman, text)

    # 1) Convert numbers (with optional unit/%) to Urdu
    def _replace_number(m: re.Match[str]) -> str:
        num_str = m.group(1)
        unit = m.group(2)
        try:
            urdu = _number_to_urdu(num_str)
        except (ValueError, KeyError):
            return m.group(0)
        if unit:
            urdu_unit = _UNIT_MAP.get(unit, unit)
            result = f"{urdu} {urdu_unit}"
        else:
            result = urdu
        changes.append((m.group(0), result))
        return result

    text = _NUMBER_UNIT_RE.sub(_replace_number, text)

    # 2) Convert English abbreviations / words to Urdu
    def _replace_abbr(m: re.Match[str]) -> str:
        word = m.group(1)
        # Check known abbreviations (case-sensitive first, then upper)
        replacement = _ABBR_MAP.get(word) or _ABBR_MAP.get(word.upper())
        if replacement:
            changes.append((word, replacement))
            return replacement
        # Units (MW, kW, GB, ...) are normally expanded by _NUMBER_UNIT_RE
        # when directly attached to a number ("50 MW"), but when the LLM
        # mentions the unit on its own ("... کتنی MW صلاحیت ...", not
        # immediately after a digit), this regex never sees it — without this
        # check it would fall through to the letter-spell-out branch below
        # and get read as "M W" instead of "Mega Watt".
        unit_replacement = _UNIT_MAP.get(word)
        if unit_replacement:
            changes.append((word, unit_replacement))
            return unit_replacement
        # Spell out unknown all-caps abbreviations (2-6 letters)
        if _is_all_caps_or_known_abbr(word):
            replacement = _spell_out(word)
            changes.append((word, replacement))
            return replacement
        return word

    text = _ENGLISH_ABBR_RE.sub(_replace_abbr, text)

    # 3) Any "/" still left over (not part of 24/7 or Tier III/IV, both
    # already handled above) is read out loud as "slash" -- replace it with
    # the natural spoken alternative-conjunction "یا" ("or") instead.
    def _replace_slash(m: re.Match[str]) -> str:
        replacement = f"{m.group(1)} یا {m.group(2)}"
        changes.append((m.group(0), replacement))
        return replacement

    text = _GENERIC_SLASH_RE.sub(_replace_slash, text)

    return text, changes


def urdu_text_tts_transform(text_stream: AsyncIterable[str]) -> AsyncIterable[str]:
    """Streaming TTS text transform that normalizes Urdu text.

    Mirrors the buffering strategy of ``roman_numeral_tts_transform``
    so partial tokens at chunk boundaries are handled correctly.
    """
    import logging

    logger = logging.getLogger("urdu_normalizer")

    async def _transform() -> AsyncIterable[str]:
        buffer = ""
        # Hold back at least this many chars, and only ever cut the buffer at a
        # whitespace boundary — so a number ("27001") near the boundary is never
        # split mid-way. Cutting at a fixed character offset used to break
        # numbers into separate digits (e.g. "ستائیس صفر ایک" instead of
        # "ستائیس ہزار ایک"). Whitespace alone is NOT sufficient for patterns
        # whose own tokens are space-separated ("Sky 47") — see find_safe_cut.
        min_tail = 24
        is_first_chunk = True
        # Latched once the utterance shows any Urdu script: subsequent
        # Latin-only chunks belong to the same Urdu utterance and must still be
        # normalized. See the normalize_urdu_text docstring.
        stream_is_urdu = False

        async for chunk in text_stream:
            buffer += chunk
            if _ARABIC_RE.search(chunk):
                stream_is_urdu = True
            if len(buffer) <= min_tail:
                continue

            cut = find_safe_cut(buffer, min_tail)
            if cut == -1:
                continue

            safe_text = buffer[:cut]
            buffer = buffer[cut:]
            normalized, applied = normalize_urdu_text(
                safe_text, assume_urdu=stream_is_urdu
            )
            if is_first_chunk:
                stripped = strip_leading_interjection(normalized)
                if stripped != normalized:
                    logger.info("Urdu TTS: stripped leading interjection")
                normalized = stripped
                is_first_chunk = False
            if applied:
                preview = "; ".join(
                    f"{before} -> {after}" for before, after in applied[:5]
                )
                if len(applied) > 5:
                    preview += f"; ... ({len(applied)} total)"
                logger.info("Urdu TTS normalization: %s", preview)
            if normalized:
                yield normalized

        if buffer:
            normalized_tail, applied = normalize_urdu_text(
                buffer, assume_urdu=stream_is_urdu
            )
            if is_first_chunk:
                stripped = strip_leading_interjection(normalized_tail)
                if stripped != normalized_tail:
                    logger.info("Urdu TTS: stripped leading interjection")
                normalized_tail = stripped
                is_first_chunk = False
            if applied:
                preview = "; ".join(
                    f"{before} -> {after}" for before, after in applied[:5]
                )
                if len(applied) > 5:
                    preview += f"; ... ({len(applied)} total)"
                logger.info("Urdu TTS normalization: %s", preview)
            if normalized_tail:
                yield normalized_tail

    return _transform()