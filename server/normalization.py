"""Rewrites a reply the way the Uplift voice should *say* it, rather than how it reads.

The kiosk speaks both languages through one Urdu-first Uplift voice, which takes its
phonemes from the script it is given: Latin text gets English letter values, and bare
digits are read in Urdu. Every rule here fixes a word or shape that voice gets wrong.
This is a safety net for the persona prompts, not a replacement for them. Only the TTS
payload changes; the visitor still reads the model's own text on screen.

The evidence behind individual respellings is in docs/pronunciation_notes.md.
"""

from __future__ import annotations

import logging
import re
from typing import Callable

logger = logging.getLogger(__name__)

__all__ = ["normalize_tts_text", "normalize_for_tts", "spoken_units"]

# The engines this module writes for. Uplift is one Urdu-first voice for both languages and
# is fixed by respelling words in Urdu script; Kokoro is English-only, cannot read Urdu
# script, and is fixed with inline pronunciations instead (server/kokoro_lexicon.py).
ENGINES = ("uplift", "kokoro")

Changes = list[tuple[str, str]]


# ── Shared helpers ──────────────────────────────────────────────────


def _sub(
    pattern: re.Pattern[str],
    repl: str | Callable[[re.Match[str]], str],
    text: str,
    changes: Changes | None,
) -> str:
    """``pattern.sub(repl, text)``, also recording each (before, after) when asked."""
    if changes is None:
        return pattern.sub(repl, text)

    def record(match: re.Match[str]) -> str:
        new = repl(match) if callable(repl) else match.expand(repl)
        if new != match.group(0):
            changes.append((match.group(0), new))
        return new

    return pattern.sub(record, text)


def _words_re(keys, *, bounded: bool = True, flags: int = 0) -> re.Pattern[str]:
    """One alternation over a table's keys, longest first so no key eats a longer one."""
    ordered = sorted(keys, key=len, reverse=True)
    if bounded:
        return re.compile("|".join(rf"\b{re.escape(k)}\b" for k in ordered), flags)
    return re.compile("|".join(re.escape(k) for k in ordered), flags)


def _lang_key(lang: str) -> str:
    return "ur" if lang == "ur" else "en"


# ── Numbers ─────────────────────────────────────────────────────────
# English replies only: the voice reads bare digits in Urdu ("65" → "پینسٹھ"), so
# they are written out as English words. Urdu replies keep their digits.

_ONES = ("zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine",
         "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen",
         "seventeen", "eighteen", "nineteen")
_TENS = ("", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety")
_SCALES = ((1_000_000_000, "billion"), (1_000_000, "million"), (1_000, "thousand"))
_DIGITS = {str(i): w for i, w in enumerate(_ONES[:10])}
_UR_DIGIT_WORDS = ("صفر", "ایک", "دو", "تین", "چار", "پانچ", "چھ", "سات", "آٹھ", "نو")

# Identifiers, not quantities: a dialling code is read digit by digit.
_PHONE_RE = re.compile(r"(?:\+?\d[\d\s-]{6,}\d)")
# Years read as pairs ("nineteen fifty four"); round centuries stay counts.
_YEAR_RE = re.compile(r"(?<![\d.])(1[89]|20)(\d{2})\b(?!\.\d)")
# A number not glued to a hyphen or decimal point on either side is a real quantity.
_NUMBER_RE = re.compile(r"(?<![\d.])(\d[\d,]*)(?:\.(\d+))?\b(?!\.\d)")


def _say_int(n: int) -> str:
    if n < 20:
        return _ONES[n]
    if n < 100:
        return _TENS[n // 10] + (f" {_ONES[n % 10]}" if n % 10 else "")
    if n < 1000:
        return f"{_ONES[n // 100]} hundred" + (f" and {_say_int(n % 100)}" if n % 100 else "")
    for value, name in _SCALES:
        if n >= value:
            head = f"{_say_int(n // value)} {name}"
            return head + (f" {_say_int(n % value)}" if n % value else "")
    return str(n)


def _say_number(match: re.Match[str]) -> str:
    whole, frac = match.group(1).replace(",", ""), match.group(2)
    try:
        said = _say_int(int(whole))
    except (ValueError, IndexError):
        return match.group(0)
    if frac:
        said += " point " + " ".join(_ONES[int(d)] for d in frac)
    return said


def _say_digits(match: re.Match[str]) -> str:
    return " ".join(_DIGITS.get(ch, ch) for ch in match.group(0) if ch.isdigit() or ch == "+")


def _say_year(match: re.Match[str]) -> str:
    century, rest = int(match.group(1)), int(match.group(2))
    if rest == 0:
        return _say_int(century * 100)
    return f"{_say_int(century)} {'oh ' + _ONES[rest] if rest < 10 else _say_int(rest)}"


def _spell_numbers(text: str, changes: Changes | None = None) -> str:
    text = _sub(_PHONE_RE, _say_digits, text, changes)
    text = _sub(_YEAR_RE, _say_year, text, changes)
    return _sub(_NUMBER_RE, _say_number, text, changes)


# Urdu replies: a bare "1954" is read as a count ("ایک ہزار نو سو چون"), but a year is
# said as a century pair ("انیس سو چون"). 20xx years are left as digits, whose count
# reading is already the correct one.
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
# Not part of a longer digit run, a decimal, or a hyphen/slash shape (fiscal pair,
# date, well number), all of which the formats section has already rewritten.
_URDU_YEAR_RE = re.compile(r"(?<![\d./-])(1[89])(\d{2})(?![\d./-])")


def _say_urdu_year(match: re.Match[str]) -> str:
    century, rest = int(match.group(1)), int(match.group(2))
    said = f"{_URDU_TENS_TAIL[century - 10]} سو"
    if rest == 0:
        return said
    tail = _UR_DIGIT_WORDS[rest] if rest < 10 else _URDU_TENS_TAIL[rest - 10]
    return f"{said} {tail}"


def spoken_years(text: str, changes: Changes | None = None) -> str:
    """Write 18xx/19xx years as Urdu words, in the year reading."""
    return _sub(_URDU_YEAR_RE, _say_urdu_year, text, changes)


# ── Brand and persona names ─────────────────────────────────────────

# "Sky47": Latin gets mangled into one word, and in Urdu the digits are read as the
# Urdu number. "Sky Forty Seven" is said correctly in both languages.
_SKY = r"(?:Sky|اسکائی|سکائی|اسکای|سکای)"
_47 = r"(?:47|۴۷|٤٧)"  # ASCII, Urdu (۴۷) and Arabic-Indic (٤٧) digits

# "Mari" is said with a retroflex flap (ماڑی), not the tapped ر both spellings imply.
_MARI = r"(?:Mari|ماری)"
# The all-caps PSX ticker, which the case-sensitive rule above does not match.
_MARI_TICKER = r"MARI"

# Latin persona names get English phonetics ("Mary-am"); Urdu script gets them right.
_MARYAM = r"(?:Maryam|Mariam|Marium)"
_HAMZA = r"(?:Hamza|Hamzah)"
# Every spelling of the salam the model writes: "Assalamualaikum", "Assalam-o-Alaikum",
# "As-salamu alaykum", "Salam alaikum".
_SALAM = r"(?:as?[-\s]*)?salaa?m[ou]?[-\s]*(?:o[-\s]*)?a?l[ae][iy]kum"
# The returned salam. Matched before _SALAM, since the two overlap on "salam".
_WALAIKUM = r"w[ae]?[-\s]*a?l[ae][iy]kum[-\s,]*(?:as?[-\s]*)?salaa?m[ou]?"


# ── Loanword respellings ────────────────────────────────────────────
# English loanwords written in Urdu script are read wrong by this voice, so each is
# forced to the spelling it does say correctly: usually Latin, sometimes a Latin
# phonetic respelling ("kaeosk"), sometimes Urdu script ("ہواوے"). Each respelling
# must stay ONE unbroken token; a hyphen or space reads as a break.

_LEAD = r"(?:Lead|لیڈ)"
_LISTED = r"(?:Listed|لیسٹڈ|لسٹڈ)"
_INTERACTIVE = r"(?:Interactive|انٹرایکٹو)"
_CAPITALIZATION = r"(?:Capitalization|Capitalisation|کیپیٹلائزیشن)"
# Plural before singular, so the plural is not left with a stray ز. The model also
# writes the ٹ as ت (ورتیکل).
_VERTICALS_PL = r"(?:Verticals|ورٹیکلز|ورتیکلز)"
_VERTICAL_SG = r"(?:Vertical|ورٹیکل|ورتیکل)"
_SEISMIC = r"(?:Seismic|سیزمک|سیسمک)"
_EARTH = r"(?:Earth|ایتھ)"
_GRADE = r"(?:Grade|گریڈ)"
_CLOUD = r"(?:Cloud|کلڈ|کلاؤڈ)"
# The hyphen is an English compound modifier and carries no sound.
_LIQUID_COOLED = r"(?:liquid[-\s]*cooled|لیکوئڈ[-\s]*کولڈ)"

# The Latin spelling gives the voice no way to reach "WAH-way", in either language.
_HUAWEI_RE = re.compile(r"\bHuawei\b")
_HUAWEI_SAID = {"en": "ہواوے", "ur": "ہواوے"}

# All-caps "NVIDIA" is letter-spelled as an initialism. The hyphen of
# "NVIDIA-compatible" is consumed so no hyphen is left between two scripts.
_NVIDIA_RE = re.compile(r"\bNVIDIA\b(\s*-\s*(?=\w))?", re.I)
_NVIDIA_SAID = {"en": "Envidia", "ur": "اینویڈیا"}

# ── Units ───────────────────────────────────────────────────────────
# A unit symbol is read as its letters ("kW" → "K W", "MW" → "M-W" once the initialism
# pass sees it), so each is said as its name. Round-tripped, the spelled-out words came
# back as the symbol in both voices ("fifty kilowatts" → "50 kW", «گیارہ کلو وولٹ» →
# "11 kV"). Bytes stay Latin in Urdu: after "500" the voice runs «سو» into «ٹیرا بائٹ»
# ("513 بائٹ"), in either Urdu spelling; "500 terabyte" was heard right every time.
#
# (symbols, English singular, English plural, Urdu, matched without a number too?)
# Symbols are case-sensitive. Single letters (m, g, t, W, V) are absent: "5m" is as often
# money as metres, and "4G" is a network. Longer symbols come first ("kWh" before "kW").
_UNITS: tuple[tuple[str, str, str, str, bool], ...] = (
    (r"kWh|KWh|KWH|kwh", "kilowatt hour", "kilowatt hours", "کلو واٹ آور", True),
    (r"MWh|MWH", "megawatt hour", "megawatt hours", "میگا واٹ آور", True),
    (r"GWh|GWH", "gigawatt hour", "gigawatt hours", "گیگا واٹ آور", True),
    (r"kWp|KWp", "kilowatt peak", "kilowatts peak", "کلو واٹ پیک", True),
    (r"MWp", "megawatt peak", "megawatts peak", "میگا واٹ پیک", True),
    (r"kW|KW|kw", "kilowatt", "kilowatts", "کلو واٹ", True),
    (r"MW", "megawatt", "megawatts", "میگا واٹ", True),
    (r"GW", "gigawatt", "gigawatts", "گیگا واٹ", True),
    (r"kVA|KVA", "kilovolt ampere", "kilovolt amperes", "کلو وولٹ ایمپیئر", True),
    (r"MVA", "megavolt ampere", "megavolt amperes", "میگا وولٹ ایمپیئر", True),
    (r"kV|KV", "kilovolt", "kilovolts", "کلو وولٹ", True),
    (r"Hz", "hertz", "hertz", "ہرٹز", True),
    (r"MMBtu|MMBTU|mmBtu", "million B-T-U", "million B-T-U", "ملین بی ٹی یو", True),
    (r"tCO2e|tCO₂e", "tonne of carbon dioxide equivalent",
     "tonnes of carbon dioxide equivalent", "ٹن کاربن ڈائی آکسائیڈ کے مساوی", True),
    (r"°\s?C", "degree Celsius", "degrees Celsius", "ڈگری سینٹی گریڈ", True),
    (r"°\s?F", "degree Fahrenheit", "degrees Fahrenheit", "ڈگری فارن ہائیٹ", True),
    (r"km²|km2|sq\.?\s?km", "square kilometre", "square kilometres", "مربع کلومیٹر", True),
    (r"sq\.?\s?ft", "square foot", "square feet", "مربع فٹ", True),
    (r"m²|sq\.?\s?m", "square metre", "square metres", "مربع میٹر", False),
    (r"m³|m3", "cubic metre", "cubic metres", "کیوبک میٹر", False),
    (r"km", "kilometre", "kilometres", "کلومیٹر", True),
    (r"cm", "centimetre", "centimetres", "سینٹی میٹر", False),
    (r"mm", "millimetre", "millimetres", "ملی میٹر", False),
    (r"kg|KG|Kg", "kilogram", "kilograms", "کلوگرام", True),
    (r"mg", "milligram", "milligrams", "ملی گرام", False),
    (r"GJ", "gigajoule", "gigajoules", "گیگا جول", True),
    (r"TJ", "terajoule", "terajoules", "ٹیرا جول", False),
    (r"MJ", "megajoule", "megajoules", "میگا جول", False),
    (r"PB", "petabyte", "petabytes", "petabyte", False),
    (r"TB", "terabyte", "terabytes", "terabyte", False),
    (r"GB", "gigabyte", "gigabytes", "gigabyte", False),
    (r"MB", "megabyte", "megabytes", "megabyte", False),
    (r"Gbps", "gigabit per second", "gigabits per second", "گیگا بٹ فی سیکنڈ", True),
    (r"Mbps", "megabit per second", "megabits per second", "میگا بٹ فی سیکنڈ", True),
    (r"psi", "P-S-I", "P-S-I", "پی ایس آئی", False),
    (r"ha", "hectare", "hectares", "ہیکٹر", False),
    # The model's own Urdu letter spellings of a symbol, and a Latin "Kilo Watts".
    (r"کے\s+ڈبلیو\s+ایچ", "kilowatt hour", "kilowatt hours", "کلو واٹ آور", False),
    (r"کے\s+ڈبلیو", "kilowatt", "kilowatts", "کلو واٹ", False),
    (r"ایم\s+ڈبلیو", "megawatt", "megawatts", "میگا واٹ", False),
    (r"کے\s+وی", "kilovolt", "kilovolts", "کلو وولٹ", False),
    (r"[Kk]ilo\s+[Ww]atts?", "kilowatt", "kilowatts", "کلو واٹ", True),
)
_SCALE_BEFORE_UNIT = r"thousand|million|billion|ہزار|لاکھ|کروڑ|ملین|بلین"
# "50kW", "50 kW", "50-kW rack", "5 million kWh", and "kW/rack" (the slash is "per").
_UNIT_RE = tuple(
    (re.compile(
        rf"(?:(?P<num>\d[\d,]*(?:\.\d+)?)(?:\s+(?P<scale>{_SCALE_BEFORE_UNIT}))?"
        rf"(?P<sep>\s*-\s*|\s*)"
        rf"|(?<![\w/.-]))"
        rf"(?:{symbols})(?![\w²³])(?P<per>\s*/\s*(?=[A-Za-z]))?"
    ), singular, plural, urdu, bare)
    for symbols, singular, plural, urdu, bare in _UNITS
)
_PER = {"en": " per ", "ur": " فی "}
_ARTICLE_BEFORE_RE = re.compile(r"\b(?:a|an|A|An)\s+$")


def _say_unit(match: re.Match[str], lang: str, singular: str, plural: str, urdu: str,
              bare: bool) -> str:
    num, scale = match.group("num"), match.group("scale")
    if num is None and not bare:
        return match.group(0)
    if lang == "ur":
        said = urdu
    else:
        # "1 kW" is one; "a 50-kW rack" and "a 100 MW plant" use the unit as an adjective.
        one = num is not None and not scale and num.replace(",", "") in ("1", "1.0")
        adjective = "-" in (match.group("sep") or "") or (
            num is not None and _ARTICLE_BEFORE_RE.search(match.string, 0, match.start())
        )
        said = singular if (one or adjective) else plural
    head = "" if num is None else f"{num} {scale + ' ' if scale else ''}"
    per = _PER[lang] if match.group("per") else ""
    return f"{head}{said}{per}"


def spoken_units(text: str, lang: str = "en", changes: Changes | None = None) -> str:
    if not text:
        return text
    key = _lang_key(lang)
    for pattern, singular, plural, urdu, bare in _UNIT_RE:
        text = _sub(pattern, lambda m, a=(singular, plural, urdu, bare): _say_unit(m, key, *a),
                    text, changes)
    return text

# The model splits "انفراسٹرکچر" into two mispronounced words.
_INFRASTRUCTURE_SPLIT_RE = re.compile(r"انفرا\s+اسٹرکچر")

# "mitigation": the joined Urdu spelling reads wrong; the split one reads correctly.
_MITIGATION_RE = re.compile(r"مٹیگیشن")

# "food-grade": the hyphen reads as a stop. "rare earth" and "methane mitigation" are
# deliberately left as written: any inserted pause made them worse.
_FOOD_GRADE_HYPHEN_RE = re.compile(r"\bfood-grade\b", re.I)

# Urdu only; the English voice says the Latin "methane" correctly.
_METHANE_RE = re.compile(r"(?:Methane|میتھین|میٹھین)", re.I)

# The pair is rewritten in one step, both halves Latin, so the phrase does not switch
# script mid-way (that mis-vowels "mitigation"). Must run before either single-word rule.
_METHANE_MITIGATION_RE = re.compile(
    rf"{_METHANE_RE.pattern}[\s-]*(?:Mitigation|مٹیگیشن|مٹی\s+گیشن)", re.I
)

# Urdu only. Also catches the hybrid "کiosk" with an Urdu first letter.
_KIOSK_RE = re.compile(r"[kک]iosk", re.I)

# Urdu only. "سبسڈیری" drops its middle syllable. The pattern is deliberately loose, and
# swallows malformed repeated tails ("سبسیڈیریاری") so they collapse to one correct form.
_SUBSIDIARY_RE = re.compile(r"سب\s*سی?ڈی+(?:ا?ری)+")

# Urdu only. "کولڈ" is how Urdu writes "cold", so the term goes to a Latin respelling.
_LIQUID_COOLED_UR_RE = re.compile(
    r"(?:liquid[\s-]*cooled|لیکویڈ[\s-]*کولڈ|لیکوئڈ[\s-]*کولڈ)", re.I
)

# Urdu only. Neither Urdu spelling can produce the English short "u". Plural first.
_CLUSTERS_UR_RE = re.compile(r"(?:کلاسٹرز|کلسٹرز|\bclusters\b)", re.I)
_CLUSTER_UR_RE = re.compile(r"(?:کلاسٹر|کلسٹر|\bcluster\b)", re.I)

# Urdu only. Follows the Urdu-script "NVIDIA", so it must not stay Latin beside it.
_COMPATIBLE_RE = re.compile(r"\bcompatible\b", re.I)

# Applied in this order. Maryam is matched before Mari; walaikum before salam.
_SAY_AS = (
    (re.compile(rf"(?<!\w){_SKY}\s*-?\s*{_47}(?!\w)", re.I), "Sky Forty Seven"),
    (re.compile(rf"(?<!\w){_WALAIKUM}(?!\w)", re.I), "وعلیکم السلام"),
    (re.compile(rf"(?<!\w){_SALAM}(?!\w)", re.I), "السلام علیکم"),
    (re.compile(rf"(?<!\w){_MARYAM}(?!\w)"), "مریم"),
    (re.compile(rf"(?<!\w){_HAMZA}(?!\w)"), "حمزہ"),
    (re.compile(rf"(?<!\w){_LEAD}(?!\w)", re.I), "Lead"),
    (re.compile(rf"(?<!\w){_LISTED}(?!\w)", re.I), "Listed"),
    (re.compile(rf"(?<!\w){_INTERACTIVE}(?!\w)", re.I), "Interactive"),
    (re.compile(rf"(?<!\w){_CAPITALIZATION}(?!\w)", re.I), "Capitalization"),
    (re.compile(rf"(?<!\w){_VERTICALS_PL}(?!\w)", re.I), "verticals"),
    (re.compile(rf"(?<!\w){_VERTICAL_SG}(?!\w)", re.I), "vertical"),
    (re.compile(rf"(?<!\w){_SEISMIC}(?!\w)", re.I), "Seismic"),
    (re.compile(rf"(?<!\w){_EARTH}(?!\w)", re.I), "earth"),
    (re.compile(rf"(?<!\w){_GRADE}(?!\w)", re.I), "grade"),
    (re.compile(rf"(?<!\w){_CLOUD}(?!\w)", re.I), "Cloud"),
    (re.compile(rf"(?<!\w){_LIQUID_COOLED}(?!\w)", re.I), "liquid cooled"),
    # "MariEnergies" has no word boundary inside it; split on the capital so the
    # ڑ rule below reaches it too.
    (re.compile(r"(?<!\w)Mari(?=[A-Z])"), "ماڑی "),
    (re.compile(rf"(?<!\w){_MARI}(?!\w)"), "ماڑی"),
    (re.compile(rf"(?<!\w){_MARI_TICKER}(?!\w)"), "ماڑی"),
)

# "ورٹیکلز (verticals)": the model glosses a loanword with its own Latin spelling, which
# the respelling above would turn into "verticals (verticals)". Collapse it to one.
_DEDUPE_GLOSS = tuple(
    (re.compile(rf"{pattern.pattern}\s*\(\s*{re.escape(replacement)}\s*\)", pattern.flags),
     replacement)
    for pattern, replacement in _SAY_AS
)


def _drop_repeated_gloss(text: str, changes: Changes | None = None) -> str:
    for pattern, replacement in _DEDUPE_GLOSS:
        text = _sub(pattern, replacement, text, changes)
    return text


# ── Transliterated English → Latin ──────────────────────────────────
# The Urdu prompt forbids English words in Urdu letters, but the model still writes
# them. Words with an ordinary Urdu equivalent (سونا for gold) are deliberately absent.

_TRANSLITERATED = {
    "کاپر": "copper",
    "گولڈ": "gold",
    "مائننگ": "mining",
    "منرلز": "Minerals",
    "انفراسٹرکچر": "infrastructure",
    "انفرا اسٹرکچر": "infrastructure",
    "ڈیٹا سینٹر": "data centre",
    "ڈیٹا سینٹرز": "data centres",
    "فرینڈلی": "friendly",
    "اسسٹنٹ": "assistant",
    "ریسیپشن": "reception",
    "ریسپشن": "reception",
    "پروڈکشن": "production",
    "ایکسپلوریشن": "exploration",
    "ٹیکنالوجیز": "Technologies",
    "سروسز": "Services",
    "انرجی": "Energy",
    "انرجیز": "Energies",
}
_TRANSLITERATED_RE = _words_re(_TRANSLITERATED, bounded=False)


# ── Acronyms, units and currency ────────────────────────────────────
# Initialisms and industry units are either letter-spaced, expanded, or (Urdu column)
# written as Urdu letter names: Latin letters in an Urdu sentence are read with English
# phonemes. An English column that repeats the key is left to spoken_initialisms, which
# hyphenates the letters (spacing them out made the English reading worse).
# Rules apply in insertion order and are \b-anchored, so longer forms and plurals come
# before the entry they contain ("GPUs" before "GPU"). Unit symbols are in _UNITS.

_ACRONYMS: dict[str, dict[str, str]] = {
    "MPCL": {"en": "M P C L", "ur": "ایم پی سی ایل"},
    "PSX": {"en": "P S X", "ur": "پی ایس ایکس"},
    "OGDCL": {"en": "O G D C L", "ur": "او جی ڈی سی ایل"},
    "MMBOE": {"en": "million barrels of oil equivalent",
              "ur": "ملین بیرل آئل ایکوی ویلنٹ"},
    "KBOEPD": {"en": "thousand barrels of oil equivalent per day",
               "ur": "ہزار بیرل آئل ایکوی ویلنٹ یومیہ"},
    "MMSCFD": {"en": "million standard cubic feet per day",
               "ur": "ملین اسٹینڈرڈ کیوبک فٹ یومیہ"},
    "MMSCF": {"en": "million standard cubic feet", "ur": "ملین اسٹینڈرڈ کیوبک فٹ"},
    "BSCF": {"en": "billion standard cubic feet", "ur": "بلین اسٹینڈرڈ کیوبک فٹ"},
    "BOEPD": {"en": "barrels of oil equivalent per day",
              "ur": "بیرل آئل ایکوی ویلنٹ یومیہ"},
    "BOPD": {"en": "barrels of oil per day", "ur": "بیرل تیل یومیہ"},
    "BBLs": {"en": "barrels", "ur": "بیرل"},
    "BBL": {"en": "barrel", "ur": "بیرل"},
    "D&PL": {"en": "development and production lease",
             "ur": "ڈیولپمنٹ اینڈ پروڈکشن لیز"},
    "MT": {"en": "metric tons", "ur": "میٹرک ٹن"},
    "REE": {"en": "rare earth elements", "ur": "نایاب معدنی عناصر"},
    "TCF": {"en": "trillion cubic feet", "ur": "ٹریلین کیوبک فٹ"},
    "E&P": {"en": "exploration and production", "ur": "تلاش اور پیداوار"},
    "ESG": {"en": "E S G", "ur": "ای ایس جی"},
    "EPS": {"en": "earnings per share", "ur": "فی حصص آمدنی"},
    "HR&R": {"en": "H R and R", "ur": "ایچ آر اینڈ آر"},
    "SNGPL": {"en": "SNGPL", "ur": "ایس این جی پی ایل"},
    "SSGCL": {"en": "SSGCL", "ur": "ایس ایس جی سی ایل"},
    "SECP": {"en": "SECP", "ur": "ایس ای سی پی"},
    "ICAP": {"en": "ICAP", "ur": "آئی سی اے پی"},
    "HSE": {"en": "HSE", "ur": "ایچ ایس ای"},
    "CEO": {"en": "CEO", "ur": "سی ای او"},
    "CFO": {"en": "CFO", "ur": "سی ایف او"},
    "COO": {"en": "COO", "ur": "سی او او"},
    "MD": {"en": "MD", "ur": "ایم ڈی"},
    "AGM": {"en": "AGM", "ur": "اے جی ایم"},
    "EGM": {"en": "EGM", "ur": "ای جی ایم"},
    "GHG": {"en": "GHG", "ur": "گرین ہاؤس گیسیں"},
    "LNG": {"en": "LNG", "ur": "ایل این جی"},
    "LPG": {"en": "LPG", "ur": "ایل پی جی"},
    "CSR": {"en": "CSR", "ur": "سی ایس آر"},
    "IFRS": {"en": "IFRS", "ur": "آئی ایف آر ایس"},
    "ISO": {"en": "ISO", "ur": "آئی ایس او"},
    "PKR": {"en": "PKR", "ur": "پاکستانی روپے"},
    "USD": {"en": "USD", "ur": "امریکی ڈالر"},
    "AI": {"en": "AI", "ur": "اے آئی"},
    "ML": {"en": "ML", "ur": "ایم ایل"},
    "IT": {"en": "IT", "ur": "آئی ٹی"},
    "HR": {"en": "HR", "ur": "ایچ آر"},
    # Avoids the word "Pakistan", which the places pass would respell mid-phrase.
    "PKT": {"en": "local time", "ur": "پاکستانی وقت"},
    "SGPC": {"en": "S G P C", "ur": "ایس جی پی سی"},
    "MSPC": {"en": "M S P C", "ur": "ایم ایس پی سی"},
    "MKDP": {"en": "M K D P", "ur": "ایم کے ڈی پی"},
    # Letters, not an expansion: the model writes the full title with this in brackets.
    "SCM": {"en": "S C M", "ur": "ایس سی ایم"},
    "PQ": {"en": "P Q", "ur": "پی کیو"},
    "JV": {"en": "joint venture", "ur": "جوائنٹ وینچر"},
    "ERP": {"en": "E R P", "ur": "ای آر پی"},
    "SAP": {"en": "SAP", "ur": "ایس اے پی"},
    "CPU": {"en": "C P U", "ur": "سی پی یو"},
    "GPUs": {"en": "G P Us", "ur": "جی پی یوز"},
    "GPU": {"en": "G P U", "ur": "جی پی یو"},
    # Urdu letter names in English too: spaced Latin capitals are not read as letter
    # names by this voice. English joins them into one token so it does not pause.
    "NPUs": {"en": "اینپیوز", "ur": "این پی یوز"},
    "NPU": {"en": "اینپیو", "ur": "این پی یو"},
    "UNGC": {"en": "U N G C", "ur": "یو این جی سی"},
    "SDGs": {"en": "S D Gs", "ur": "ایس ڈی جیز"},
    "UN": {"en": "U N", "ur": "اقوام متحدہ"},
}
_ACRONYM_RULES = tuple(
    (re.compile(rf"\b{re.escape(k)}\b"), v) for k, v in _ACRONYMS.items()
)

# A credit rating, not a quantity: the number spell-out would say "Aone".
_RATING_RE = re.compile(r"\bA1\b")

_SCALE_WORDS = {
    "bn": {"en": "billion", "ur": "بلین"},
    "mn": {"en": "million", "ur": "ملین"},
    "tn": {"en": "trillion", "ur": "ٹریلین"},
    "billion": {"en": "billion", "ur": "بلین"},
    "million": {"en": "million", "ur": "ملین"},
    "trillion": {"en": "trillion", "ur": "ٹریلین"},
}

# Currency is said after the amount: "PKR 65bn" → "65 billion rupees".
_CURRENCY = (
    (re.compile(r"\b(?:PKR|Rs\.?)\s*([\d,.]+)\s*(billion|million|trillion|bn|mn|tn)?\b", re.I),
     {"en": "rupees", "ur": "روپے"}),
    (re.compile(r"\bUSD\s*([\d,.]+)\s*(billion|million|trillion|bn|mn|tn)?\b", re.I),
     {"en": "US dollars", "ur": "امریکی ڈالر"}),
)


def _scale(word: str | None, lang: str = "en") -> str:
    if not word:
        return ""
    said = _SCALE_WORDS.get(word.lower(), {}).get(lang, word.lower())
    return f"{said} "


def _respell_by_language(text: str, lang: str, changes: Changes | None = None,
                         kokoro: bool = False) -> str:
    """The rules whose spoken form depends on the language."""
    key = _lang_key(lang)
    # Currency first: its pattern consumes "PKR"/"USD", which the acronym table would
    # otherwise claim.
    for pattern, unit in _CURRENCY:
        text = _sub(
            pattern,
            lambda m, u=unit[key]: f"{m.group(1)} {_scale(m.group(2), key)}{u}",
            text, changes,
        )
    if not kokoro:  # Kokoro's English lexicon already says "Huawei" correctly.
        text = _sub(_HUAWEI_RE, _HUAWEI_SAID[key], text, changes)
    text = _sub(_NVIDIA_RE, lambda m, s=_NVIDIA_SAID[key]: f"{s} " if m.group(1) else s,
                text, changes)
    # Before the acronym table, which would claim "MT"-style symbols as initialisms.
    text = spoken_units(text, key, changes)
    for pattern, spoken in _ACRONYM_RULES:
        # An Urdu-script English column ("NPU") is an Uplift trick; Kokoro reads the letters.
        if kokoro and _ARABIC_RE.search(spoken[key]):
            continue
        text = _sub(pattern, spoken[key], text, changes)
    if key == "ur":
        text = _sub(_KIOSK_RE, "kaeosk", text, changes)
        text = _sub(_SUBSIDIARY_RE, "سب سِڈی ری", text, changes)
        text = _sub(_COMPATIBLE_RE, "کمپیٹیبل", text, changes)
        text = _sub(_LIQUID_COOLED_UR_RE, "likwid koold", text, changes)
        text = _sub(_CLUSTERS_UR_RE, "klusturz", text, changes)
        text = _sub(_CLUSTER_UR_RE, "klustur", text, changes)
        text = _sub(_METHANE_RE, "methayn", text, changes)
    return text


# ── People: names, ranks and honours ────────────────────────────────
# Latin-script Pakistani names come out as different words ("Anwar Ali Hyder" → "and
# were early hired"); in Urdu script the same voice says them correctly. Applies in
# both languages, since Urdu replies keep names in Latin script too.

_PERSON_NAMES: dict[str, str] = {
    "Ghulam Muhammad Malik": "غلام محمد ملک",
    "Muhammad Afzal Janjua": "محمد افضل جنجوعہ",
    "Syed Bakhtiyar Kazmi": "سید بختیار کاظمی",
    "Muhammad Aamir Salim": "محمد عامر سلیم",
    "Sumair Ashraf Sheikh": "سمیر اشرف شیخ",
    "Hamed Yaqoob Sheikh": "حامد یعقوب شیخ",
    "Ishfaq Nadeem Ahmad": "اشفاق ندیم احمد",
    "Mehmood Aslam Hayat": "محمود اسلم حیات",
    "Khalid Nawaz Malik": "خالد نواز ملک",
    "Raza Muhammad Khan": "رضا محمد خان",
    "Syed Shahzad Nabi": "سید شہزاد نبی",
    "Anwar Ali Hyder": "انور علی حیدر",
    "Ahmed Hayat Lak": "احمد حیات لک",
    "Abid Niaz Hasan": "عابد نیاز حسن",
    "Mushtaq Hussain": "مشتاق حسین",
    "Muhammad Sajjad": "محمد سجاد",
    "Nabeel Rasheed": "نبیل رشید",
    "Imtiaz Shaheen": "امتیاز شاہین",
    "Faheem Haider": "فہیم حیدر",
    "Abdullah Asif": "عبداللہ آصف",
    "Hazoor Bakhsh": "حضور بخش",
    "Nadeem Ahmed": "ندیم احمد",
    "Zafar Abbas": "ظفر عباس",
    "Seema Adil": "سیما عادل",
    "Ayla Majid": "عائلہ مجید",
    "Hamid Niaz": "حامد نیاز",
}

# A reply often names someone by one word ("Ask Kazmi"), which the full-name table
# cannot match. Applied after it.
_WORD_FORMS: dict[str, str] = {
    "Abbas": "عباس", "Abdullah": "عبداللہ", "Abid": "عابد", "Adil": "عادل",
    "Ahmad": "احمد", "Ahmed": "احمد", "Ali": "علی", "Anwar": "انور",
    "Aamir": "عامر", "Ashraf": "اشرف", "Asif": "آصف", "Aslam": "اسلم",
    "Ayla": "عائلہ", "Afzal": "افضل", "Bakhsh": "بخش", "Bakhtiyar": "بختیار",
    "Faheem": "فہیم", "Ghulam": "غلام", "Haider": "حیدر", "Hamed": "حامد",
    "Hamid": "حامد", "Hasan": "حسن", "Hayat": "حیات", "Hazoor": "حضور",
    "Hussain": "حسین", "Hyder": "حیدر", "Imtiaz": "امتیاز", "Ishfaq": "اشفاق",
    "Janjua": "جنجوعہ", "Kazmi": "کاظمی", "Khalid": "خالد", "Khan": "خان",
    "Lak": "لک", "Majid": "مجید", "Malik": "ملک", "Mehmood": "محمود",
    "Muhammad": "محمد", "Mushtaq": "مشتاق", "Nabeel": "نبیل", "Nabi": "نبی",
    "Nadeem": "ندیم", "Nawaz": "نواز", "Niaz": "نیاز", "Rasheed": "رشید",
    "Raza": "رضا", "Sajjad": "سجاد", "Salim": "سلیم", "Seema": "سیما",
    "Shaheen": "شاہین", "Shahzad": "شہزاد", "Sheikh": "شیخ", "Sumair": "سمیر",
    "Syed": "سید", "Yaqoob": "یعقوب", "Zafar": "ظفر",
}

# Also ordinary words or places, so respelling them alone would misfire.
_WORD_BLOCKLIST = frozenset({"Ali", "Khan", "Malik"})

# Only words that occur in a known name, so the two tables cannot drift apart.
_KNOWN_WORDS: dict[str, str] = {
    word: _WORD_FORMS[word]
    for full in _PERSON_NAMES
    for word in full.split()
    if word in _WORD_FORMS and word not in _WORD_BLOCKLIST
}

_PERSON_NAME_RE = _words_re(_PERSON_NAMES)
_NAME_WORD_RE = _words_re(_KNOWN_WORDS)

# Abbreviated ranks are read as words ("Leftenant"); spelled out they are said
# correctly. Two-word ranks first, so "Lt Gen" is not split by the bare "Lt" rule.
_RANKS_EN: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bLt\.?\s*Gen\.?(?=\s|$)"), "Lieutenant General"),
    (re.compile(r"\bMaj\.?\s*Gen\.?(?=\s|$)"), "Major General"),
    (re.compile(r"\bBrig\.?\s*Gen\.?(?=\s|$)"), "Brigadier General"),
    (re.compile(r"\bBrig\.?(?=\s|$)"), "Brigadier"),
    (re.compile(r"\bCol\.?(?=\s|$)"), "Colonel"),
    (re.compile(r"\bLt\.?\s*Col\.?(?=\s|$)"), "Lieutenant Colonel"),
    (re.compile(r"\bCapt\.?(?=\s|$)"), "Captain"),
    (re.compile(r"\bMaj\.?(?=\s|$)"), "Major"),
    (re.compile(r"\bLt\.?(?=\s|$)"), "Lieutenant"),
)

# Urdu also maps the spelled-out English ranks, which the model writes in full.
_RANKS_UR: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bLt\.?\s*Gen\.?(?=\s|$)"), "لیفٹیننٹ جنرل"),
    (re.compile(r"\bMaj\.?\s*Gen\.?(?=\s|$)"), "میجر جنرل"),
    (re.compile(r"\bBrig\.?\s*Gen\.?(?=\s|$)"), "بریگیڈیئر جنرل"),
    (re.compile(r"\bLt\.?\s*Col\.?(?=\s|$)"), "لیفٹیننٹ کرنل"),
    (re.compile(r"\bBrig\.?(?=\s|$)"), "بریگیڈیئر"),
    (re.compile(r"\bCol\.?(?=\s|$)"), "کرنل"),
    (re.compile(r"\bCapt\.?(?=\s|$)"), "کیپٹن"),
    (re.compile(r"\bMaj\.?(?=\s|$)"), "میجر"),
    (re.compile(r"\bLt\.?(?=\s|$)"), "لیفٹیننٹ"),
    (re.compile(r"\bLieutenant General\b"), "لیفٹیننٹ جنرل"),
    (re.compile(r"\bMajor General\b"), "میجر جنرل"),
    (re.compile(r"\bBrigadier General\b"), "بریگیڈیئر جنرل"),
    (re.compile(r"\bLieutenant Colonel\b"), "لیفٹیننٹ کرنل"),
    (re.compile(r"\bBrigadier\b"), "بریگیڈیئر"),
    (re.compile(r"\bColonel\b"), "کرنل"),
    (re.compile(r"\bCaptain\b"), "کیپٹن"),
    (re.compile(r"\bMajor\b"), "میجر"),
    (re.compile(r"\bLieutenant\b"), "لیفٹیننٹ"),
)

# "(Retd)" is read as "Grade", so it is moved in front of its rank as a word:
# "Brigadier X (Retd)" → "Retired Brigadier X". Longest rank first.
_RANK_NAMES_EN = (
    "Lieutenant General|Major General|Brigadier General|Lieutenant Colonel"
    "|Brigadier|Colonel|Captain|Major|Lieutenant"
)
_RANK_NAMES_UR = (
    "لیفٹیننٹ جنرل|میجر جنرل|بریگیڈیئر جنرل|لیفٹیننٹ کرنل"
    "|بریگیڈیئر|کرنل|کیپٹن|میجر|لیفٹیننٹ"
)

_SUFFIX_EN = {"retd": "Retired", "retired": "Retired", "r": "Retired", "late": "the late"}
_SUFFIX_UR = {"retd": "ریٹائرڈ", "retired": "ریٹائرڈ", "r": "ریٹائرڈ", "late": "مرحوم",
              "ر": "ریٹائرڈ", "ریٹائرڈ": "ریٹائرڈ", "مرحوم": "مرحوم"}

_RANK_SUFFIX_EN_RE = re.compile(
    rf"\b({_RANK_NAMES_EN})\b(?P<name>(?:\s+[^\s(,.]+){{0,4}})\s*\((Retd\.?|Retired|R|Late)\)",
    re.IGNORECASE,
)
_SUFFIX_TOKEN_UR = r"Retd\.?|Retired|R|Late|ر|ریٹائرڈ|مرحوم"
_RANK_SUFFIX_UR_RE = re.compile(
    rf"({_RANK_NAMES_UR})(?P<name>(?:\s+[^\s(،۔]+){{0,4}})\s*\((?P<suffix>{_SUFFIX_TOKEN_UR})\)",
    re.IGNORECASE,
)
# A suffix with no rank in front of it.
_BARE_SUFFIX_RE = re.compile(r"\s*\((Retd\.?|Retired|R|Late)\)", re.IGNORECASE)
_BARE_SUFFIX_UR_RE = re.compile(rf"\s*\((?:{_SUFFIX_TOKEN_UR})\)", re.IGNORECASE)

# Military honours, said in full as Pakistanis say them. Latin "HI(M)" is read "HIV" and
# Latin "Hilal-e-Imtiaz" is garbled, but the Urdu spelling with the izafat written as ے
# round-trips as "Hilal-e-Imtiaz Military" in both languages.
_HONOUR_SAID = {
    "HI": "ہلالے امتیاز ملٹری", "SI": "ستارۂ امتیاز ملٹری",
    "TI": "تمغۂ امتیاز ملٹری", "NI": "نشانے امتیاز ملٹری",
}
# Kokoro cannot read Urdu script; its lexicon says these Latin forms.
_HONOUR_SAID_KOKORO = {
    "HI": "Hilal-e-Imtiaz Military", "SI": "Sitara-e-Imtiaz Military",
    "TI": "Tamgha-e-Imtiaz Military", "NI": "Nishan-e-Imtiaz Military",
}
_HONOUR_UR_LETTERS = {"ایچ آئی": "HI", "ایس آئی": "SI", "ٹی آئی": "TI", "این آئی": "NI"}
_HONOUR_WORDS = {"hilal": "HI", "ہلال": "HI", "sitara": "SI", "ستارہ": "SI", "ستارۂ": "SI",
                 "tamgha": "TI", "تمغہ": "TI", "تمغۂ": "TI", "nishan": "NI", "نشان": "NI"}
_HONOUR_TOKEN = (
    r"(?P<abbr>\b(?:HI|SI|TI|NI)|ایچ\s+آئی|ایس\s+آئی|ٹی\s+آئی|این\s+آئی)\s*\(\s*(?:M|ایم)\s*\)|"
    r"(?P<word>\b(?:Hilal|Sitara|Tamgha|Nishan)|ہلال|ستارۂ?|تمغۂ?|نشان)[ِ\s-]*(?:e|ے|ِ)?[\s-]*"
    r"(?:Imtiaz|امتیاز)\s*(?:\(\s*(?:Military|M|ملٹری|ایم)\s*\)|(?:Military|ملٹری))?"
)
_RETD_TOKEN = r"Retd\.?|Retired|R|Late|ر|ریٹائرڈ|مرحوم"
# The honour sits between the name and "(Retd)" in the corpus; the suffix is lifted in
# front of it so the rank rules below still see "name (Retd)".
_HONOURS_RE = re.compile(
    rf"[,،]?\s*(?:{_HONOUR_TOKEN})(?P<suffix>\s*[,،]?\s*\((?:{_RETD_TOKEN})\))?",
    re.IGNORECASE,
)
# ", (Retd)" → " (Retd)", so the rank/suffix pair stays one matchable phrase.
_COMMA_BEFORE_SUFFIX_RE = re.compile(r"[,،]\s*(?=\((?:Retd\.?|Retired|R|Late)\))", re.IGNORECASE)
# Commas left stranded by the dropped honour.
_ORPHAN_COMMA_RE = re.compile(r"[,،]\s*(?=[,،])|[,،](?=\s*(?:۔|\.|$))|،(?=\s+ہیں)")


def _say_honour(match: re.Match[str], lang: str, kokoro: bool = False) -> str:
    if match.group("abbr"):
        abbr = re.sub(r"\s+", " ", match.group("abbr"))
        key = _HONOUR_UR_LETTERS.get(abbr, abbr.upper())
    else:
        key = _HONOUR_WORDS[match.group("word").lower()]
    suffix = (match.group("suffix") or "").strip(" ,،")
    # Keep the separator only if the honour followed something ("Hyder, HI(M)").
    lead = match.group(0)[:1]
    comma = ("،" if lang == "ur" else ",") if lead in ",،" else (" " if lead.isspace() else "")
    said = (_HONOUR_SAID_KOKORO if kokoro else _HONOUR_SAID)[key]
    return f"{' ' + suffix if suffix else ''}{comma}{' ' if comma.strip() else ''}{said}"


# Honorifics before a name. English reads "Mr." and "Dr." correctly; Urdu needs them in
# Urdu script. "Dr" must be followed by a Latin name (the names pass has not run yet), or
# "Jinnah Dr. پر" (Drive) would match.
_HONORIFIC_BEFORE_NAME = r"(?=\s+[A-Z])"
_HONORIFICS = {
    "en": ((re.compile(rf"\bEngr\.?{_HONORIFIC_BEFORE_NAME}"), "Engineer"),
           (re.compile(rf"\bProf\.?{_HONORIFIC_BEFORE_NAME}"), "Professor")),
    "ur": ((re.compile(rf"\bEngr\.?{_HONORIFIC_BEFORE_NAME}"), "انجینئر"),
           (re.compile(rf"\bProf\.?{_HONORIFIC_BEFORE_NAME}"), "پروفیسر"),
           (re.compile(rf"\bDr\.?{_HONORIFIC_BEFORE_NAME}"), "ڈاکٹر"),
           (re.compile(rf"\bMrs\.?{_HONORIFIC_BEFORE_NAME}"), "مسز"),
           (re.compile(rf"\bMr\.?{_HONORIFIC_BEFORE_NAME}"), "مسٹر"),
           (re.compile(rf"\bMs\.?{_HONORIFIC_BEFORE_NAME}"), "مس")),
}


def _move_suffix(match: re.Match[str], table: dict[str, str]) -> str:
    rank, name = match.group(1), match.group("name")
    suffix = (match.groupdict().get("suffix") or match.group(3)).rstrip(".").lower()
    word = table.get(suffix, table["retd"])
    return f"{word} {rank}{name}"


def spoken_names_and_ranks(text: str, lang: str = "en", changes: Changes | None = None,
                           kokoro: bool = False) -> str:
    if not text:
        return text

    text = _sub(_HONOURS_RE, lambda m: _say_honour(m, lang, kokoro), text, changes)
    # Before the rank-suffix rules, whose pattern a leftover comma would break.
    text = _sub(_COMMA_BEFORE_SUFFIX_RE, " ", text, changes)
    text = _sub(_ORPHAN_COMMA_RE, "", text, changes)

    if lang == "ur":
        for pattern, replacement in _RANKS_UR:
            text = _sub(pattern, replacement, text, changes)
        text = _sub(_RANK_SUFFIX_UR_RE, lambda m: _move_suffix(m, _SUFFIX_UR), text, changes)
        text = _sub(_BARE_SUFFIX_UR_RE, "", text, changes)
    else:
        for pattern, replacement in _RANKS_EN:
            text = _sub(pattern, replacement, text, changes)
        text = _sub(_RANK_SUFFIX_EN_RE, lambda m: _move_suffix(m, _SUFFIX_EN), text, changes)
        text = _sub(_BARE_SUFFIX_RE,
                    lambda m: f" {_SUFFIX_EN[m.group(1).rstrip('.').lower()]}", text, changes)
    for pattern, replacement in _HONORIFICS[_lang_key(lang)]:
        text = _sub(pattern, replacement, text, changes)
    if kokoro:  # Names are said by spoken_for_kokoro, not respelled in Urdu script.
        return text
    text = _sub(_PERSON_NAME_RE, lambda m: _PERSON_NAMES[m.group(0)], text, changes)
    return _sub(_NAME_WORD_RE, lambda m: _KNOWN_WORDS[m.group(0)], text, changes)


# ── Addresses, contact details and formulae ─────────────────────────
# These must run before the English number spell-out: a postcode, a sector and the "2"
# in CO2 are identifiers, not quantities.

_FORMULA_SUB = str.maketrans("₀₁₂₃₄₅₆₇₈₉", "0123456789")
# The trailing ([A-Z])? lets "H2S" match.
_FORMULA_RE = re.compile(r"\b(CO|NO|SO|CH|H|N)([₀-₉]|(?<=[A-Z])\d)([A-Z])?(?![\d\w])")

# A formula is said by its name, never letter by letter.
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

# "CO2" spelled as Urdu letter names ("سی او 2").
_SPELLED_CO_RE = re.compile(r"\bسی\s+او\s*([۰-۹2])?\b")

_AMP_ABBR = {
    "E&P": {"en": "E and P", "ur": "ای اینڈ پی"},
    "HR&R": {"en": "H R and R", "ur": "ایچ آر اینڈ آر"},
    "HSE&Q": {"en": "H S E and Q", "ur": "ایچ ایس ای اینڈ کیو"},
    "R&D": {"en": "R and D", "ur": "آر اینڈ ڈی"},
    "M&A": {"en": "M and A", "ur": "ایم اینڈ اے"},
    "P&L": {"en": "P and L", "ur": "پی اینڈ ایل"},
}
_AMP_RE = _words_re(_AMP_ABBR, bounded=False)

# A slashed title pair ("MD/CEO") is run together; hyphenated letters joined by "and"
# read back correctly. A lone initialism is fine and left alone.
_TITLE_LETTERS = {
    "MD": "M-D", "CEO": "C-E-O", "CFO": "C-F-O", "COO": "C-O-O",
    "CTO": "C-T-O", "CIO": "C-I-O", "CISO": "C-I-S-O",
    # One role written as a compound; "and" twice in a row would be wrong.
    "MD-CEO": "M-D C-E-O",
}
_SPELLED_TITLE = r"Managing Director|Chief Executive Officer|Chairman"
_TITLE_PAIR_RE = re.compile(
    rf"\b({'|'.join(sorted(_TITLE_LETTERS, key=len, reverse=True))}|{_SPELLED_TITLE})"
    rf"\s*[/&]\s*"
    rf"({'|'.join(sorted(_TITLE_LETTERS, key=len, reverse=True))}|{_SPELLED_TITLE})\b"
)
_AND = {"en": "and", "ur": "اور"}

# "G-10/4" is an Islamabad sector, said "G ten four" with the slash silent. Scoped to
# the sector shape so "24/7" and "2024/25" keep their own handling.
_SECTOR_RE = re.compile(r"\b([A-Z])[-\s]?(\d{1,2})\s*/\s*(\d{1,2})\b")

# Anchored to a city: a bare 5-digit run is often an ISO standard, not a postcode.
_CITY = (
    r"Islamabad|Karachi|Lahore|Rawalpindi|Peshawar|Quetta|Multan|Hyderabad|Sukkur|"
    r"Ghotki|Daharki|اسلام\s*آباد|کراچی|لاہور|راولپنڈی|پشاور|کوئٹہ|ملتان|حیدرآباد|"
    r"سکھر|گھوٹکی|ڈہرکی"
)
_POSTCODE_RE = re.compile(
    rf"({_CITY})[\s,–—-]+(\d{{5}})\b(?!\s*(?:million|billion|thousand))"
)
_POSTAL_LABEL = {"en": "postal code", "ur": "پوسٹل کوڈ"}

# "ISO 45001:2018": a comma between standard and edition, so the numbers don't run together.
_STANDARD_EDITION_RE = re.compile(
    r"\b((?:ISO|IEC|OHSAS|ASTM|EN)(?:/[A-Z]{2,6})?\s*\d{4,5})\s*:\s*(\d{4})\b"
)
_DIGIT_WORDS = {"en": _ONES[:10], "ur": _UR_DIGIT_WORDS}

_ORDINALS = {
    "1st": {"en": "First", "ur": "فرسٹ"}, "2nd": {"en": "Second", "ur": "سیکنڈ"},
    "3rd": {"en": "Third", "ur": "تھرڈ"}, "4th": {"en": "Fourth", "ur": "فورتھ"},
    "5th": {"en": "Fifth", "ur": "فففتھ"}, "6th": {"en": "Sixth", "ur": "سکستھ"},
    "7th": {"en": "Seventh", "ur": "سیونتھ"}, "8th": {"en": "Eighth", "ur": "ایتھ"},
    "9th": {"en": "Ninth", "ur": "نائنتھ"}, "10th": {"en": "Tenth", "ur": "ٹینتھ"},
}
_ORDINAL_RE = re.compile(rf"\b({'|'.join(_ORDINALS)})\b", re.IGNORECASE)

# Extension and box numbers are identifiers, read digit by digit.
_CONTACT = {
    "en": [
        (re.compile(r"\bExt\.?\s*(?=\d)", re.IGNORECASE), "extension "),
        (re.compile(r"(?<=extension )(\d{2,5})\b"),
         lambda m: " ".join(_DIGIT_WORDS["en"][int(d)] for d in m.group(1))),
        (re.compile(r"\bP\.?\s?O\.?\s+Box\b", re.IGNORECASE), "Post Office Box"),
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

# "kiosk" written in Urdu script is said "kioosk"; the prompt's Latin rule is not
# always followed.
_KIOSK_TRANSLIT_RE = re.compile(r"کائیوسک|کائوسک|کیوسک|کیوسْک")

# English only: the hyphen swallows the prefix's vowel ("anti-" heard as "ant").
# In Urdu the spaced form reads worse.
_PREFIX_RE = re.compile(
    r"\b(anti|multi|semi|non|pre|post|co|re|sub|inter|intra|micro|macro|self|cross|ex)"
    r"-(?=[a-z])",
    re.IGNORECASE,
)


def _say_formula(match: re.Match[str], lang: str = "en") -> str:
    letters, digit = match.group(1), match.group(2).translate(_FORMULA_SUB)
    tail = match.group(3) or ""
    named = _FORMULA_NAMES.get(f"{letters}{digit}{tail}")
    if named:
        return named[_lang_key(lang)]
    # Unknown formula: spaced, so the number pass cannot glue the digit on.
    return " ".join(letters + tail) + " " + digit


def _say_spelled_co(match: re.Match[str]) -> str:
    digit = (match.group(1) or "").translate(_FORMULA_SUB)
    return _FORMULA_NAMES["CO2" if digit == "2" else "CO"]["ur"]


def _say_title(token: str) -> str:
    return _TITLE_LETTERS.get(token, token)


def _say_sector(match: re.Match[str]) -> str:
    letter, block, sub = match.group(1), int(match.group(2)), int(match.group(3))
    return f"{letter} {_say_int(block)} {_say_int(sub)}"


def spoken_addresses(text: str, lang: str = "en", changes: Changes | None = None) -> str:
    if not text:
        return text
    key = _lang_key(lang)

    text = _sub(_FORMULA_RE, lambda m: _say_formula(m, lang), text, changes)
    if key == "ur":
        text = _sub(_SPELLED_CO_RE, _say_spelled_co, text, changes)
    text = _sub(_AMP_RE, lambda m: _AMP_ABBR[m.group(0)][key], text, changes)
    text = _sub(
        _TITLE_PAIR_RE,
        lambda m: f"{_say_title(m.group(1))} {_AND[key]} {_say_title(m.group(2))}",
        text, changes,
    )
    text = _sub(_SECTOR_RE, _say_sector, text, changes)

    comma = "،" if key == "ur" else ","
    text = _sub(_STANDARD_EDITION_RE, rf"\1{comma} \2", text, changes)

    digits = _DIGIT_WORDS[key]
    text = _sub(
        _POSTCODE_RE,
        lambda m: f"{m.group(1)}{comma} {_POSTAL_LABEL[key]} "
        + " ".join(digits[int(d)] for d in m.group(2)),
        text, changes,
    )

    text = _sub(_ORDINAL_RE, lambda m: _ORDINALS[m.group(1).lower()][key], text, changes)
    for pattern, replacement in _CONTACT[key]:
        text = _sub(pattern, replacement, text, changes)
    if key == "ur":
        text = _sub(_KIOSK_TRANSLIT_RE, "kiosk", text, changes)
    else:
        text = _sub(_PREFIX_RE, r"\1 ", text, changes)
    return text


# ── Report formats, dates and symbols ───────────────────────────────
# Both languages. Structural shapes neither voice reads: fiscal years, DD/MM/YYYY,
# "2.81x", well identifiers, ~ − §. Digits are left in place for the number pass.
# Runs after addresses, which claims "G-10/4" before the well rule could.

_FY_LABEL = {"en": "financial year", "ur": "مالی سال"}
_TO_WORD = {"en": "to", "ur": "تا"}
_FY_RE = re.compile(r"\bFY\s*(\d{2,4})(?:\s*[-–]\s*(\d{2,4}))?\b", re.IGNORECASE)

# A bare "2024-25". Excludes "2017-2020" and "20-year"; allows a sentence-ending period
# but not a decimal.
_NOT_PART_OF_A_NUMBER = r"(?![\d/-])(?!\.\d)"
_FY_BARE_RE = re.compile(rf"(?<![\d./-])(\d{{4}})\s*[-–]\s*(\d{{2}}){_NOT_PART_OF_A_NUMBER}")

_MONTHS = {
    "en": ("January", "February", "March", "April", "May", "June",
           "July", "August", "September", "October", "November", "December"),
    "ur": ("جنوری", "فروری", "مارچ", "اپریل", "مئی", "جون",
           "جولائی", "اگست", "ستمبر", "اکتوبر", "نومبر", "دسمبر"),
}
_DATE_RE = re.compile(r"\b(\d{1,2})\s*/\s*(\d{1,2})\s*/\s*(\d{4})\b")

_TIMES_WORD = {"en": "times", "ur": "گنا"}
_TIMES_RATIO_RE = re.compile(r"(?<=\d)\s*x\b")

# "Karakoram-01": the digits are spaced so the leading zero is said. A digit before the
# hyphen ("20-year") is not an identifier. AM/PM are excluded ("9:00 AM-5:00 PM").
_WELL_RE = re.compile(r"\b(?!(?:AM|PM)\b)([A-Za-z][A-Za-z]*)-(\d{1,2})\b", re.IGNORECASE)

_SYMBOL_WORDS = {
    "~": {"en": "approximately ", "ur": "تقریباً "},
    "−": {"en": "minus ", "ur": "منفی "},   # U+2212, not the ASCII hyphen
    "§": {"en": "section ", "ur": "سیکشن "},
}
_SYMBOL_RE = re.compile(r"[~−§](?=\s*[\d\w])")

# An en-dash between two numbers is a range, not a minus.
_RANGE_RE = re.compile(r"(?<=\d)\s*–\s*(?=\d)")

# "2017-2020" would otherwise match the phone-number rule and be read digit by digit.
_YEAR_RANGE_RE = re.compile(
    rf"(?<![\d./-])((?:1[89]|20)\d{{2}})\s*[-–]\s*((?:1[89]|20)\d{{2}}){_NOT_PART_OF_A_NUMBER}"
)


def _say_fy(match: re.Match[str], lang: str) -> str:
    start, end = match.group(1), match.group(2)
    said = f"{_FY_LABEL[lang]} {start}"
    return f"{said} {_TO_WORD[lang]} {end}" if end else said


def _say_date(match: re.Match[str], lang: str) -> str:
    day, month, year = int(match.group(1)), int(match.group(2)), match.group(3)
    if not 1 <= month <= 12 or not 1 <= day <= 31:
        return match.group(0)
    return f"{day} {_MONTHS[lang][month - 1]} {year}"


def spoken_formats(text: str, lang: str = "en", changes: Changes | None = None) -> str:
    key = _lang_key(lang)
    text = _sub(_FY_RE, lambda m: _say_fy(m, key), text, changes)
    text = _sub(_DATE_RE, lambda m: _say_date(m, key), text, changes)
    # Before _FY_BARE_RE: a full year-to-year span is not a fiscal pair.
    text = _sub(_YEAR_RANGE_RE, rf"\1 {_TO_WORD[key]} \2", text, changes)
    text = _sub(_FY_BARE_RE, rf"\1 {_TO_WORD[key]} \2", text, changes)
    text = _sub(_RANGE_RE, f" {_TO_WORD[key]} ", text, changes)
    text = _sub(_TIMES_RATIO_RE, f" {_TIMES_WORD[key]}", text, changes)
    text = _sub(_WELL_RE, lambda m: f"{m.group(1)} {' '.join(m.group(2))}", text, changes)
    return _sub(_SYMBOL_RE, lambda m: _SYMBOL_WORDS[m.group(0)][key], text, changes)


# ── URLs and domains ────────────────────────────────────────────────
# A bare domain is mangled in both languages. The dots are said as words, and the label
# is split into its real words by lookup, since only the corpus knows the split.

_DOMAIN_LABELS = {
    "marienergies": {"en": "Mari Energies", "ur": "ماڑی انرجیز"},
    "mariservices": {"en": "Mari Services", "ur": "ماڑی سروسز"},
    "sky47": {"en": "Sky Forty Seven", "ur": "اسکائی فورٹی سیون"},
    "linkedin": {"en": "LinkedIn", "ur": "لنکڈان"},
}
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
    www, label, suffix = match.group(1), match.group(2).lower(), match.group(3)
    dot = _DOT[lang]
    parts: list[str] = []
    if www:
        parts += [_WWW[lang], dot]
    parts.append(_DOMAIN_LABELS[label][lang])
    for piece in suffix.strip(".").split("."):
        parts += [dot, _TLD_WORDS[piece.lower()][lang]]
    return " ".join(parts)


def spoken_urls(text: str, lang: str = "en", changes: Changes | None = None) -> str:
    key = _lang_key(lang)
    return _sub(_URL_RE, lambda m: _say_domain(m, key), text, changes)


# ── Places, fields and programmes ───────────────────────────────────
# Urdu- and Pashto-origin names written in Latin script, respelled in Urdu script in
# both languages. Genuinely foreign names (Lockhart, Miyawaki, Dundee, PwC) are left out.

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
    # Formations and reservoirs
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
    # Wells and blocks
    "Spinwam": "سپین وام",
    "Shewa": "شیوہ",
    "Shawal": "شوال",
    "Maiwand": "میوند",
    "Pateji": "پٹیجی",
    "Jhim": "جھم",
    "Karak": "کرک",
    # Provinces and major cities. "Pakistan" is the exception: Urdu script reads badly
    # for it, so it gets a Latin respelling. "Pakistani" needs its own entry, since there
    # is no word boundary after "Pakistan" inside it.
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
    # Ranges and deserts. "Indus" is absent: it is read correctly, and the Urdu would
    # be a translation, not a respelling.
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
    # Address localities. "Cantt" is absent: "چھاؤنی" would change what the address says.
    "Bijjar Chowk": "بجار چوک",
    "Chowk": "چوک",
    "Jinnah": "جناح",
    "Azadi": "آزادی",
    # Minerals ventures
    "Tuzgi": "توزگی",
    "Ammuri": "عموری",
}

# CSR programmes, banks and partners. "Maroc" is absent: "مراکش" is the country.
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
    "Fauji": "فوجی",
    "Askari": "عسکری",
    "Meezan": "میزان",
    "Faysal": "فیصل",
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
    "Corplink": "کارپلنک",
    "Fatima": "فاطمہ",
    "Portia": "پورشیا",
    "Orient": "اورینٹ",
    "Paramount": "پیراماؤنٹ",
    "Stanvac": "اسٹینویک",
    "Clifton": "کلفٹن",
    "Ramadan": "رمضان",
    "EZShifa": "ای زیڈ شفا",
    "Pak-Turk": "پاک ترک",
    "Pak Arab": "پاک عرب",
    "Noor-e-Sehar": "نور سحر",
    "Noor-Sehar": "نور سحر",
    "Dad Laghari": "داد لغاری",
}

# The words the multi-word keys are made of, for replies that use one on its own.
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
    "Naya": "نیا",
    "Hilal": "ہلال",
    "Abu": "ابو",
    "Dhabi": "ظہبی",
    "Baraka": "برکہ",
    "Pak": "پاک",
    "Esso": "ایسو",
    "Petroserv": "پیٹروسرو",
    "Infraavest": "انفراویسٹ",
    "Planetive": "پلانیٹو",
}

# Urdu spellings the model writes itself, mapped to the one the voice says correctly.
# "این جی ایل" is LNG with its letters reordered.
_URDU_VARIANTS: dict[str, str] = {
    "ڈہرکی": "ڈھرکی",
    "ساچل": "سچل",
    "سجاؤل": "سجاول",
    "این جی ایل": "ایل این جی",
    "ایل این جی": "ایل این جی",
}

_ALL_PLACES: dict[str, str] = {**_PLACES, **_PROGRAMMES, **_PARTS, **_URDU_VARIANTS}
_PLACE_RE = _words_re(_ALL_PLACES)


def spoken_places(text: str, lang: str = "en", changes: Changes | None = None) -> str:
    if not text:
        return text
    return _sub(_PLACE_RE, lambda m: _ALL_PLACES[m.group(0)], text, changes)


# ── Every other initialism ──────────────────────────────────────────
# The acronym table covers the measured cases; the knowledge base has ~150 more (UET,
# NTN, UBL, ACCA, SNGPL ...) and the model writes others. Round-tripped, plain Latin
# capitals failed in both voices ("UBL" → "above", "IBA" → "Eber", "NTN" → "MTN").
# English: hyphenated letters, the same trick as "M-D and C-E-O", read back correctly.
# Urdu: Urdu letter names, as the acronym table's Urdu column already does.

_UR_LETTER_NAMES = {
    "A": "اے", "B": "بی", "C": "سی", "D": "ڈی", "E": "ای", "F": "ایف", "G": "جی",
    "H": "ایچ", "I": "آئی", "J": "جے", "K": "کے", "L": "ایل", "M": "ایم", "N": "این",
    "O": "او", "P": "پی", "Q": "کیو", "R": "آر", "S": "ایس", "T": "ٹی", "U": "یو",
    "V": "وی", "W": "ڈبلیو", "X": "ایکس", "Y": "وائی", "Z": "زیڈ",
}

# Said as a word, not letters. English keeps the Latin, which it reads correctly.
_WORD_ACRONYMS_UR = {
    "LUMS": "لمز", "PARCO": "پارکو", "GEM": "جیم", "SOAS": "سواس", "NUST": "نسٹ",
    "NADRA": "نادرا", "WAPDA": "واپڈا", "NEPRA": "نیپرا", "OGRA": "اوگرا", "NAB": "نیب",
    "FATA": "فاٹا", "SUPARCO": "سپارکو", "COMSATS": "کامسیٹس", "NATO": "نیٹو",
    "OPEC": "اوپیک", "COVID": "کووڈ", "UNICEF": "یونیسیف", "UNESCO": "یونیسکو",
    "NASA": "ناسا", "SMART": "سمارٹ", "SEED": "سیڈ", "RAG": "ریگ", "BTEX": "بی ٹیکس",
    "FONGROW": "فون گرو", "IPSEC": "آئی پی سیک", "EBITDA": "EBITDA", "OHSAS": "OHSAS",
    "ANSI": "اینسی", "PACRA": "پیکرا",
}
# Mixed-case forms the all-caps pattern cannot see, and ones said neither as letters
# nor as a word ("AAA" is "triple A").
_SPECIAL_ACRONYMS = {
    "MSc": {"en": "M-Sc", "ur": "ایم ایس سی"}, "BSc": {"en": "B-Sc", "ur": "بی ایس سی"},
    "PhD": {"en": "P-H-D", "ur": "پی ایچ ڈی"}, "PwC": {"en": "P-W-C", "ur": "پی ڈبلیو سی"},
    "AAA": {"en": "triple A", "ur": "ٹرپل اے"},
}
_SPECIAL_ACRONYM_RE = _words_re(_SPECIAL_ACRONYMS)

# Ordinary English words written in capitals, for emphasis or in a heading. Not
# initialisms, in either language.
_CAPS_WORDS = frozenset({
    "A", "ALL", "AN", "AND", "ARE", "AS", "AT", "BE", "BUT", "BY", "DO", "DONT", "EVER",
    "FIRST", "FOR", "FROM", "HAS", "HAVE", "IF", "IMPORTANT", "IN", "INTO", "IS", "IT",
    "LAST", "MUST", "NAME", "NAMES", "NEVER", "NEW", "NO", "NOT", "NOTE", "OF", "ON",
    "ONE", "ONLY", "OR", "OUR", "READ", "READER", "REPLY", "SEE", "SENIOR", "SHOULD",
    "THAT", "THE", "THIS", "TO", "USE", "VOICE", "WARNING", "WE", "WITH", "YES", "YOU",
    "YOUR", "MANAGEMENT", "ALWAYS", "WHAT", "WHO", "WHEN", "WHERE", "WHY", "HOW",
})

_ROMAN_NUMERALS = frozenset({"II", "III", "IV", "VI", "VII", "VIII", "IX", "XI", "XII"})
# English: already read correctly as written, or an ordinary word in capitals.
_KEEP_LATIN_EN = frozenset({
    "AI", "IT", "HR", "ML", "CEO", "CFO", "COO", "MD", "ISO", "AM", "PM", "TV", "OK",
    "US", "UK", "USA", "UAE",
    # Word-read acronyms stay Latin, except PACRA: Latin came back "Petra", letters "PECRA".
    *(_WORD_ACRONYMS_UR.keys() - {"PACRA"}),
})

# Standalone capitals; a hyphen on either side means the token is already spelled out
# ("M-D") or part of a compound the earlier passes own.
_INITIALISM_RE = re.compile(r"(?<![\w&-])([A-Z]{2,7})(s)?(?![\w&-])")


def _say_initialism(match: re.Match[str], lang: str) -> str:
    letters, plural = match.group(1), match.group(2) or ""
    if letters in _ROMAN_NUMERALS or letters in _CAPS_WORDS:
        return match.group(0)
    if lang == "ur":
        if letters in _WORD_ACRONYMS_UR:
            return _WORD_ACRONYMS_UR[letters] + ("ز" if plural else "")
        if len(letters) > 6:
            return match.group(0)
        said = " ".join(_UR_LETTER_NAMES[c] for c in letters)
        return f"{said}ز" if plural else said
    if letters in _KEEP_LATIN_EN or len(letters) > 6:
        return match.group(0)
    return "-".join(letters) + plural


def spoken_initialisms(text: str, lang: str = "en", changes: Changes | None = None) -> str:
    if not text:
        return text
    key = _lang_key(lang)
    text = _sub(_SPECIAL_ACRONYM_RE, lambda m: _SPECIAL_ACRONYMS[m.group(0)][key], text, changes)
    return _sub(_INITIALISM_RE, lambda m: _say_initialism(m, key), text, changes)


# ── English-only: percent, times, slashes and abbreviations ─────────
# Runs after addresses (which owns "MD/CEO" and the sectors) and before the number
# spell-out, so "33%" is already "33 percent" when its digits are read.

_PERCENT_RE = re.compile(r"\s*%")
# A slash between digits is a ratio or date and is left alone.
_EN_WORD_SLASH_RE = re.compile(r"(?<=[A-Za-z])\s*/\s*(?=[A-Za-z])")
# "24/7" is an idiom, not a ratio.
_24_7_RE = re.compile(r"\b24\s*/\s*7\b")
# Minutes bounded to [0-5]\d so the debt ratio "0.24:99.76" is not read as a time.
_TIME_RE = re.compile(r"\b(\d{1,2}):([0-5]\d)\s*(AM|PM|am|pm)?")
# "9:00 AM-5:00 PM": the hyphen between two times is spoken as "to".
_TIME_RANGE_RE = re.compile(r"(?<=[AP]M)\s*[-–]\s*(?=\d{1,2}:[0-5]\d)", re.IGNORECASE)
# A colon ratio with decimals on both sides; "ISO 9001:2015" is not matched.
_COLON_RATIO_RE = re.compile(r"(?<=\d)\s*:\s*(?=\d+\.\d)")

_SUFFIXES = {
    r"\bLtd\b\.?": "Limited",
    r"\bPvt\b\.?": "Private",
    r"\bCo\.": "Company",
}
_LATIN_ABBR = {
    r"\bw\.e\.f\.": "with effect from",
    r"\be\.g\.": "for example",
    r"\bi\.e\.": "that is",
    r"\bvs\.?(?=\s)": "versus",
    r"\betc\.": "et cetera",
    r"\bapprox\.": "approximately",
    r"\bincl\.": "including",
    r"\bNo[.:](?=\s*\d)": "number",
}
_SUFFIX_RULES = tuple((re.compile(p), r) for p, r in _SUFFIXES.items())
_ABBR_RULES = tuple((re.compile(p, re.IGNORECASE), r) for p, r in _LATIN_ABBR.items())


def _say_time(match: re.Match[str]) -> str:
    """"9:00 AM" → "9 AM"; "5:30 PM" → "5 30 PM"."""
    hour, minute, meridiem = match.group(1), match.group(2), match.group(3)
    said = hour if minute == "00" else f"{hour} {minute}"
    return f"{said} {meridiem}" if meridiem else said


def normalise_for_english(text: str, lang: str = "en", changes: Changes | None = None) -> str:
    if not text or lang == "ur":
        return text

    text = _sub(_24_7_RE, "24 7", text, changes)
    text = _sub(_PERCENT_RE, " percent", text, changes)
    # Before _TIME_RE, which would leave this hyphen with no digits around it.
    text = _sub(_TIME_RANGE_RE, " to ", text, changes)
    text = _sub(_TIME_RE, _say_time, text, changes)
    text = _sub(_COLON_RATIO_RE, " to ", text, changes)
    for pattern, replacement in _SUFFIX_RULES:
        text = _sub(pattern, replacement, text, changes)
    for pattern, replacement in _ABBR_RULES:
        text = _sub(pattern, replacement, text, changes)
    # Last, once "w.e.f."/"No:" are settled.
    return _sub(_EN_WORD_SLASH_RE, " and ", text, changes)


# ── Urdu-only: Roman numerals and slashes ───────────────────────────

_ARABIC_RE = re.compile(r"[؀-ۿݐ-ݿﭐ-﷿ﹰ-﻿]")

# "Tier III" is read letter by letter. Anchored to a label so a stray "IV" in prose is
# untouched; a bare "I" is absent because it collides with the pronoun.
_ROMAN_VALUES = {
    "II": "2", "III": "3", "IV": "4", "V": "5",
    "VI": "6", "VII": "7", "VIII": "8", "IX": "9", "X": "10",
}
_ROMAN_LABEL = r"(?:Tier|Phase|Annex|Annexure|Category|Class|ٹیئر|مرحلہ|درجہ)"
_ROMAN_RE = re.compile(
    rf"\b({_ROMAN_LABEL})(\s+)((?:{'|'.join(sorted(_ROMAN_VALUES, key=len, reverse=True))})(?:\s*/\s*(?:{'|'.join(sorted(_ROMAN_VALUES, key=len, reverse=True))}))*)\b"
)

# A spaced "&" ("ایم ڈی & سی ای او") is read as a stray word; joined forms like "HR&R"
# are the acronym table's.
_UR_AMPERSAND_RE = re.compile(r"(?<=\S)\s+&\s+(?=\S)")

# "/" between words is said "flash". Numeric slashes are ratios and are left alone.
_UR_WORD_SLASH_RE = re.compile(r"(?<=[\w؀-ۿ])\s*/\s*(?=[\w؀-ۿ])")
_NUMERIC_SLASH_RE = re.compile(r"\d\s*/\s*\d")


def _roman_to_digits(match: re.Match[str]) -> str:
    label, gap, numerals = match.group(1), match.group(2), match.group(3)
    converted = "/".join(
        _ROMAN_VALUES.get(part.strip(), part.strip()) for part in numerals.split("/")
    )
    return f"{label}{gap}{converted}"


def _fix_slashes(text: str, changes: Changes | None = None) -> str:
    out, last = [], 0
    for m in _UR_WORD_SLASH_RE.finditer(text):
        window = text[max(0, m.start() - 1): m.end() + 1]
        if _NUMERIC_SLASH_RE.search(window):
            continue
        out.append(text[last:m.start()])
        out.append(" اور ")
        if changes is not None:
            changes.append((m.group(0), " اور "))
        last = m.end()
    out.append(text[last:])
    return "".join(out)


def normalise_for_uplift(text: str, lang: str = "ur", changes: Changes | None = None) -> str:
    if not text or lang != "ur" or not _ARABIC_RE.search(text):
        return text
    text = _sub(_ROMAN_RE, _roman_to_digits, text, changes)
    text = spoken_years(text, changes)
    text = spoken_urls(text, "ur", changes)
    text = _sub(_UR_AMPERSAND_RE, " اور ", text, changes)
    return _fix_slashes(text, changes)


# ── Kokoro: Pakistani words as inline pronunciations ────────────────
# Kokoro takes "[word](/IPA/)" in its input. Each known word becomes a placeholder here so
# no later pass (number spell-out, slashes, initialisms) can reach inside the IPA, and the
# placeholders become the inline pronunciations as the very last step.

from .kokoro_lexicon import KOKORO_ALIASES, KOKORO_IPA  # noqa: E402

# Every spelling → its lexicon key.
_KOKORO_WORDS: dict[str, str] = {**{w: w for w in KOKORO_IPA}, **KOKORO_ALIASES}
_KOKORO_WALAIKUM_RE = re.compile(rf"(?<!\w){_WALAIKUM}(?!\w)", re.I)
_KOKORO_SALAM_RE = re.compile(rf"(?<!\w){_SALAM}(?!\w)", re.I)
# "MariEnergies" has no boundary inside it.
_KOKORO_MARI_JOINED_RE = re.compile(r"(?<!\w)Mari(?=[A-Z])")
# Full names first, so "Ali", "Khan" and "Malik" are only said this way inside a name.
_KOKORO_FULL_NAME_RE = _words_re(_PERSON_NAMES)
_KOKORO_WORD_RE = _words_re(w for w in _KOKORO_WORDS if w not in _WORD_BLOCKLIST)
_SLOT_OPEN, _SLOT_CLOSE, _SLOT_DIGIT0 = "\ue000", "\ue001", 0xE010
_KOKORO_SLOT_RE = re.compile(f"{_SLOT_OPEN}([\ue010-\ue019]+){_SLOT_CLOSE}")
_AAA_RE = re.compile(r"\bAAA\b")


def spoken_for_kokoro(text: str, slots: list[str], changes: Changes | None = None) -> str:
    """Replace known Pakistani words with placeholders for their inline pronunciation."""

    def slot(written: str, keys: list[str]) -> str:
        said = f"[{written}](/{' '.join(KOKORO_IPA[k] for k in keys)}/)"
        if changes is not None:
            changes.append((written, said))
        slots.append(said)
        digits = "".join(chr(_SLOT_DIGIT0 + int(d)) for d in str(len(slots) - 1))
        return f"{_SLOT_OPEN}{digits}{_SLOT_CLOSE}"

    text = _KOKORO_WALAIKUM_RE.sub(lambda m: slot(m.group(0), ["Walaikum Assalam"]), text)
    text = _KOKORO_SALAM_RE.sub(lambda m: slot(m.group(0), ["Assalamualaikum"]), text)
    text = _KOKORO_MARI_JOINED_RE.sub(lambda m: slot("Mari", ["Mari"]) + " ", text)
    # A name can mix audited pronunciations with words Kokoro says best as written
    # ("Zafar Abbas"), so each word of a full name is decided on its own.
    text = _KOKORO_FULL_NAME_RE.sub(
        lambda m: " ".join(slot(w, [_KOKORO_WORDS[w]]) if w in _KOKORO_WORDS else w
                           for w in m.group(0).split()), text)
    return _KOKORO_WORD_RE.sub(lambda m: slot(m.group(0), [_KOKORO_WORDS[m.group(0)]]), text)


def _restore_kokoro_slots(text: str, slots: list[str]) -> str:
    return _KOKORO_SLOT_RE.sub(
        lambda m: slots[int("".join(str(ord(c) - _SLOT_DIGIT0) for c in m.group(1)))], text)


# ── Public API ──────────────────────────────────────────────────────


def normalize_tts_text(text: str, lang: str = "en", engine: str = "uplift") -> tuple[str, Changes]:
    """Rewrite one reply sentence for the TTS voice.

    ``lang`` is "ur" for the Urdu voice path; anything else is treated as English.
    ``engine`` is "uplift" or "kokoro" (English only; see :data:`ENGINES`).
    Returns the spoken text and the (before, after) pairs of every rule that fired.
    Sentences arrive whole from the reply stream, so no stream buffering is needed.
    """
    changes: Changes = []
    kokoro = engine == "kokoro" and lang != "ur"
    slots: list[str] = []
    # Domains first: "sky47.com.pk" must be seen whole, before the Sky47 rule.
    text = spoken_urls(text, lang, changes)
    if not kokoro:
        text = _drop_repeated_gloss(text, changes)
    text = _sub(_FOOD_GRADE_HYPHEN_RE, "food grade", text, changes)
    text = _sub(_INFRASTRUCTURE_SPLIT_RE, "انفراسٹرکچر", text, changes)
    # The pair before its single-word rules, which would split its script.
    if lang == "ur":
        text = _sub(_METHANE_MITIGATION_RE, "methayn mitigation", text, changes)
    text = _sub(_MITIGATION_RE, "مٹی گیشن", text, changes)
    text = _sub(_TRANSLITERATED_RE, lambda m: _TRANSLITERATED[m.group(0)], text, changes)
    for pattern, replacement in _SAY_AS:
        # The salam, persona names and Mari are Urdu script for Uplift; Kokoro says them
        # through its lexicon below.
        if kokoro and _ARABIC_RE.search(replacement):
            continue
        text = _sub(pattern, replacement, text, changes)
    text = _respell_by_language(text, lang, changes, kokoro)
    text = spoken_names_and_ranks(text, lang, changes, kokoro)
    text = spoken_addresses(text, lang, changes)
    # Again: the address pass expands "CH4" to "میتھین".
    if lang == "ur":
        text = _sub(_METHANE_MITIGATION_RE, "methayn mitigation", text, changes)
        text = _sub(_METHANE_RE, "methayn", text, changes)
    text = spoken_formats(text, lang, changes)
    text = normalise_for_english(text, lang, changes)
    if kokoro:
        # Late for the same reason as spoken_places: the address and well rules need the
        # Latin names. Kokoro reads plain capitals correctly; hyphenating them made it
        # worse ("U-E-T" → "UIT"), so only "AAA" is rewritten.
        text = spoken_for_kokoro(text, slots, changes)
        text = _sub(_AAA_RE, _SPECIAL_ACRONYMS["AAA"]["en"], text, changes)
    else:
        # After formats, whose well rule needs the Latin letter before "Spinwam-1"'s hyphen.
        text = spoken_places(text, lang, changes)
        # After every pass that owns a capitalised shape (table acronyms, titles, domains).
        text = spoken_initialisms(text, lang, changes)
    text = _sub(_RATING_RE, "A one", text, changes)
    if lang != "ur":
        text = _spell_numbers(text, changes)
    # Last, so it sees the fully rewritten text.
    text = normalise_for_uplift(text, lang, changes)
    if kokoro:
        text = _restore_kokoro_slots(text, slots)
    return text, changes


def normalize_for_tts(text: str, lang: str = "en", engine: str = "uplift") -> str:
    """:func:`normalize_tts_text`, logging a preview of what was rewritten."""
    spoken, changes = normalize_tts_text(text, lang, engine)
    if changes:
        preview = "; ".join(f"{before!r} -> {after!r}" for before, after in changes[:5])
        logger.info("tts normalized (%s/%s, %d changes): %s", engine, lang, len(changes), preview)
    return spoken
