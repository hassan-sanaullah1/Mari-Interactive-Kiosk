"""Spoken forms for people's names, military ranks and honours — both languages.

The kiosk runs one Urdu-first Uplift voice for English as well (``APP_EN_TTS=uplift``),
and that voice applies English/American phonetics to Latin-script text. On the Pakistani
names in the knowledge base the result is not an accent, it is the wrong name:

    "Anwar Ali Hyder"      → "and were early hired"
    "Abid Niaz Hasan"      → "David Nais Hassan"
    "Ahmed Hayat Lak"      → "Othman Hayat Lark"
    "Muhammad Aamir Salim" → "Mehmet Amir Selim"
    "Syed Bakhtiyar Kazmi" → "Sit back, Dr. Kazmi"

Writing the name in Urdu script instead makes the same voice reach for Urdu phonemes,
and it comes out right — the trick already used for ``ماڑی`` in ``server/providers/tts.py``.

Two things keep this a lookup table rather than a rule:

*   **It is not a blanket win.** "Faheem Haider" is already correct in English mode and
    Urdu script makes it *worse* ("Fahim headers"); in Urdu mode the reverse is true.
    So every entry is per-language, and only names that a round trip (Uplift TTS →
    Soniox STT) showed to be broken are listed. Names that already work are absent on
    purpose — see ``tests/test_names_and_ranks.py``, which pins that.
*   **Transliteration is a judgement call.** Getting "عائلہ" vs "آئلہ" wrong swaps one
    mispronunciation for another, so each spelling here was checked against the engine
    rather than derived.

Ranks and honours are separate from names and are handled by rule, because the failure
there is abbreviation, not phonetics: the voice reads "Lt. Gen." as "Leftenant"/"Eldeej"
and "(Retd)" as "Grade", but says "Lieutenant General" and "Retired" correctly.
"""

from __future__ import annotations

import re

# ── names ───────────────────────────────────────────────────────────
# Latin spelling → Urdu-script spelling, applied ONLY in English mode. Every entry was
# verified round trip: Latin wrong, Urdu right. Longest first at match time so
# "Syed Bakhtiyar Kazmi" wins over any shorter overlapping key.
_NAMES_FOR_ENGLISH: dict[str, str] = {
    "Ghulam Muhammad Malik": "غلام محمد ملک",
    "Muhammad Afzal Janjua": "محمد افضل جنجوعہ",
    "Syed Bakhtiyar Kazmi": "سید بختیار کاظمی",
    "Muhammad Aamir Salim": "محمد عامر سلیم",
    "Hamed Yaqoob Sheikh": "حامد یعقوب شیخ",
    "Mehmood Aslam Hayat": "محمود اسلم حیات",
    "Ahmed Hayat Lak": "احمد حیات لک",
    "Mushtaq Hussain": "مشتاق حسین",
    "Muhammad Sajjad": "محمد سجاد",
    "Nabeel Rasheed": "نبیل رشید",
    "Imtiaz Shaheen": "امتیاز شاہین",
    "Faheem Haider": "فہیم حیدر",
    "Hazoor Bakhsh": "حضور بخش",
    "Seema Adil": "سیما عادل",
    "Ayla Majid": "عائلہ مجید",
    "Hamid Niaz": "حامد نیاز",
}

# Everyone else in the knowledge base was tested the same way and is deliberately NOT
# here, because Latin came out closer than Urdu script for them:
#     "Abdullah Asif", "Abid Niaz Hasan", "Anwar Ali Hyder", "Ishfaq Nadeem Ahmad",
#     "Khalid Nawaz Malik", "Nadeem Ahmed", "Raza Muhammad Khan", "Sumair Ashraf Sheikh",
#     "Syed Shahzad Nabi", "Zafar Abbas"
# Re-run the round trip before adding one — respelling a name the voice already says
# correctly makes it worse, which is why this is a measured list and not a rule.

# The same idea in Urdu mode, where the LLM often leaves the name in Latin script
# because the system prompt tells it to keep names in their original spelling. There the
# voice says "فہیم ہیڈر" for "Faheem Haider" and "صبا قدیر کاظمی" for "Syed Bakhtiyar
# Kazmi", so the Latin form is swapped for Urdu script.
_NAMES_FOR_URDU: dict[str, str] = {
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


def _name_pattern(names: dict[str, str]) -> re.Pattern[str] | None:
    if not names:
        return None
    keys = sorted(names, key=len, reverse=True)
    return re.compile("|".join(rf"\b{re.escape(k)}\b" for k in keys))


_EN_NAME_RE = _name_pattern(_NAMES_FOR_ENGLISH)
_UR_NAME_RE = _name_pattern(_NAMES_FOR_URDU)


# ── ranks ───────────────────────────────────────────────────────────
# Abbreviated ranks are read as words ("Leftenant", "Brick", "Eldeej", "Mert Can").
# Spelled out, the same voice says them correctly in both languages.
_RANKS_EN: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bLt\.?\s*Gen\.?(?=\s|$)"), "Lieutenant General"),
    (re.compile(r"\bMaj\.?\s*Gen\.?(?=\s|$)"), "Major General"),
    (re.compile(r"\bBrig\.?(?=\s|$)"), "Brigadier"),
    (re.compile(r"\bCol\.?(?=\s|$)"), "Colonel"),
    (re.compile(r"\bCapt\.?(?=\s|$)"), "Captain"),
)

_RANKS_UR: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bLt\.?\s*Gen\.?(?=\s|$)"), "لیفٹیننٹ جنرل"),
    (re.compile(r"\bMaj\.?\s*Gen\.?(?=\s|$)"), "میجر جنرل"),
    (re.compile(r"\bBrig\.?(?=\s|$)"), "بریگیڈیئر"),
    (re.compile(r"\bLieutenant General\b"), "لیفٹیننٹ جنرل"),
    (re.compile(r"\bMajor General\b"), "میجر جنرل"),
    (re.compile(r"\bBrigadier\b"), "بریگیڈیئر"),
)

# "(Retd)" is read as "Grade" and "(Late)" swallows the surrounding words, but the bare
# words are said correctly. A plain substitution would leave the ungrammatical
# "Brigadier Sumair Ashraf Sheikh Retired ...", so the suffix is lifted out and
# re-attached in front of the rank it belongs to: "Retired Brigadier Sumair ...".
_RANK_NAMES_EN = "Lieutenant General|Major General|Brigadier|Colonel|Captain"
_RANK_NAMES_UR = "لیفٹیننٹ جنرل|میجر جنرل|بریگیڈیئر"

_SUFFIX_EN = {"retd": "Retired", "retired": "Retired", "r": "Retired", "late": "the late"}
_SUFFIX_UR = {"retd": "ریٹائرڈ", "retired": "ریٹائرڈ", "r": "ریٹائرڈ", "late": "مرحوم",
               "ر": "ریٹائرڈ", "ریٹائرڈ": "ریٹائرڈ", "مرحوم": "مرحوم"}

# "<rank> <name words...> (Retd)" — the name run stops at the parenthesis.
_RANK_SUFFIX_EN_RE = re.compile(
    rf"\b({_RANK_NAMES_EN})\b(?P<name>(?:\s+[^\s(,.]+){{0,4}})\s*\((Retd\.?|Retired|R|Late)\)",
    re.IGNORECASE,
)
# Urdu replies write the suffix in Urdu letters too — "(ر)" for retired, "(مرحوم)" for
# the late — so both alphabets are accepted here.
_SUFFIX_TOKEN_UR = r"Retd\.?|Retired|R|Late|ر|ریٹائرڈ|مرحوم"
_RANK_SUFFIX_UR_RE = re.compile(
    rf"({_RANK_NAMES_UR})(?P<name>(?:\s+[^\s(،۔]+){{0,4}})\s*\((?P<suffix>{_SUFFIX_TOKEN_UR})\)",
    re.IGNORECASE,
)

# A "(Retd)" with no rank in front of it still has to go — bare, not parenthesised.
_BARE_SUFFIX_RE = re.compile(r"\s*\((Retd\.?|Retired|R|Late)\)", re.IGNORECASE)
_BARE_SUFFIX_UR_RE = re.compile(rf"\s*\((?:{_SUFFIX_TOKEN_UR})\)", re.IGNORECASE)


def _move_suffix(match: re.Match[str], table: dict[str, str]) -> str:
    rank, name = match.group(1), match.group("name")
    suffix = (match.groupdict().get("suffix") or match.group(3)).rstrip(".").lower()
    word = table.get(suffix, table["retd"])
    return f"{word} {rank}{name}"

# ── honours and slashed titles ──────────────────────────────────────
# "HI(M)" comes out as "HIV" or "a type M", and spelling out "Hilal-e-Imtiaz Military"
# fares no better ("Hello team, here's Mummy Tree"). It is a decoration, not a fact a
# visitor needs read aloud, so it is dropped from speech only — the text the model
# generated, and every fact in it, is untouched.
_HONOURS_RE = re.compile(r"[,،]?\s*\b(?:HI|SI|TI|NI)\s*\(\s*M\s*\)")

# Dropping an honour mid-sentence strands the comma that introduced it — "Hyder, ,
# (Retd)" in English, "حیدر، ہیں۔" in Urdu — which the voice reads as a stumble. This
# collapses a doubled comma and drops one left hanging before a clause end.
# ", (Retd)" → " (Retd)", so the rank/suffix pair below stays one matchable phrase.
_COMMA_BEFORE_SUFFIX_RE = re.compile(r"[,،]\s*(?=\((?:Retd\.?|Retired|R|Late)\))", re.IGNORECASE)

_ORPHAN_COMMA_RE = re.compile(r"[,،]\s*(?=[,،])|[,،](?=\s*(?:۔|\.|$))|،(?=\s+ہیں)")

# "MD/CEO" is read as "complete search seekie ko" in English mode. The Urdu-mode slash
# fix in urdu_normalise.py does not cover Latin-only runs like this one.
# Slashed/ampersanded title pairs ("MD/CEO", "MD & CEO") are handled in addresses.py,
# which spells each title out in full — "the MD and CEO" was still heard as "ESDM didn't
# see EO", so splitting on "and" alone is not enough.


def spoken_names_and_ranks(text: str, lang: str = "en") -> str:
    """Rewrite names, ranks and honours into forms the Uplift voice says correctly.

    Applies to both languages — the mangling is worst in English mode, but Urdu replies
    keep Latin-script names too (the system prompt asks for original spellings), and the
    voice mishandles those just as badly.
    """
    if not text:
        return text

    text = _HONOURS_RE.sub("", text)
    # The honour often sits between the name and "(Retd)" ("Hyder, HI(M), (Retd)").
    # Removing it leaves ", (Retd)", whose comma would stop the rank-suffix pattern
    # below from seeing the two as one phrase, so it goes before that runs.
    text = _COMMA_BEFORE_SUFFIX_RE.sub(" ", text)
    text = _ORPHAN_COMMA_RE.sub("", text)

    if lang == "ur":
        for pattern, replacement in _RANKS_UR:
            text = pattern.sub(replacement, text)
        text = _RANK_SUFFIX_UR_RE.sub(lambda m: _move_suffix(m, _SUFFIX_UR), text)
        text = _BARE_SUFFIX_UR_RE.sub("", text)
        if _UR_NAME_RE is not None:
            text = _UR_NAME_RE.sub(lambda m: _NAMES_FOR_URDU[m.group(0)], text)
    else:
        for pattern, replacement in _RANKS_EN:
            text = pattern.sub(replacement, text)
        text = _RANK_SUFFIX_EN_RE.sub(lambda m: _move_suffix(m, _SUFFIX_EN), text)
        text = _BARE_SUFFIX_RE.sub(lambda m: f" {_SUFFIX_EN[m.group(1).rstrip('.').lower()]}", text)
        if _EN_NAME_RE is not None:
            text = _EN_NAME_RE.sub(lambda m: _NAMES_FOR_ENGLISH[m.group(0)], text)

    return text
