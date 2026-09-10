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

This began as a measured subset: only names a round trip (Uplift TTS → Soniox STT)
showed to be broken were listed, and ten people were pinned as deliberately absent
because Latin had come out closer for them. **Listening to the deployed kiosk showed
that was the wrong call** — those ten were precisely the names still being
mispronounced in English mode. Every person in the corpus is now respelled, in both
languages, and "which names" is no longer a judgement call that can be got wrong.

Two things still hold:

*   **A full name is not enough.** The tables only match the whole name, but a spoken
    answer rarely repeats one — "Ask Kazmi about it", "Faheem chairs the board". Those
    went through untouched, so the same person was said correctly in one sentence and
    mangled in the next. ``_WORD_FORMS`` covers each name word on its own, applied
    after the full-name pass, and is filtered by the names actually in the tables so
    the two cannot drift apart.
*   **Transliteration is a judgement call.** Getting "عائلہ" vs "آئلہ" wrong swaps one
    mispronunciation for another. The spellings here are conventional ones; a round
    trip is still the right way to settle a doubtful vowel.

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
    # These ten were previously absent on a round-trip finding that Latin came out
    # closer than Urdu script for them. Listening to the deployed kiosk says otherwise:
    # they were the names still being mispronounced in English mode. Every person in
    # the corpus is now respelled, so the rule is "all of them", not a measured subset
    # — which also means a name added to the corpus is covered by adding it here once.
    "Sumair Ashraf Sheikh": "سمیر اشرف شیخ",
    "Ishfaq Nadeem Ahmad": "اشفاق ندیم احمد",
    "Khalid Nawaz Malik": "خالد نواز ملک",
    "Raza Muhammad Khan": "رضا محمد خان",
    "Syed Shahzad Nabi": "سید شہزاد نبی",
    "Anwar Ali Hyder": "انور علی حیدر",
    "Abid Niaz Hasan": "عابد نیاز حسن",
    "Abdullah Asif": "عبداللہ آصف",
    "Nadeem Ahmed": "ندیم احمد",
    "Zafar Abbas": "ظفر عباس",
}

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


# ── individual name words ───────────────────────────────────────────
# The tables above only match a full name, but a spoken answer rarely repeats one.
# "Ask Kazmi about it", "Faheem chairs the board", "Mr. Rasheed" — every one of those
# went through untouched, so the same person was said correctly in one sentence and
# mangled in the next.
#
# Each distinct word of every name therefore gets its own spoken form, applied after
# the full-name pass has had first refusal. The words come from the full names above,
# so there is one source of truth: a name added there is covered here automatically,
# and the per-word spellings only have to be given for words the split cannot infer.
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

# Words that are also ordinary English, or a place the places table owns. Respelling
# these would fire on sentences that have nothing to do with a person.
_WORD_BLOCKLIST = frozenset({"Ali", "Khan", "Malik"})


def _name_pattern(names: dict[str, str]) -> re.Pattern[str] | None:
    if not names:
        return None
    keys = sorted(names, key=len, reverse=True)
    return re.compile("|".join(rf"\b{re.escape(k)}\b" for k in keys))


_EN_NAME_RE = _name_pattern(_NAMES_FOR_ENGLISH)
_UR_NAME_RE = _name_pattern(_NAMES_FOR_URDU)

# Only words that actually occur in a name the kiosk knows, minus the blocklist. Built
# from the tables rather than hand-listed, so the two cannot drift apart.
_KNOWN_WORDS: dict[str, str] = {
    word: _WORD_FORMS[word]
    for full in {**_NAMES_FOR_ENGLISH, **_NAMES_FOR_URDU}
    for word in full.split()
    if word in _WORD_FORMS and word not in _WORD_BLOCKLIST
}

_WORD_RE = _name_pattern(_KNOWN_WORDS)


# ── ranks ───────────────────────────────────────────────────────────
# Abbreviated ranks are read as words ("Leftenant", "Brick", "Eldeej", "Mert Can").
# Spelled out, the same voice says them correctly in both languages.
# Two-word ranks come first in both tables: "Lt Gen" must be matched whole, or the
# bare "Lt" rule would claim its first half and leave "Lieutenant Gen".
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

# Every rank the English table knows needs an Urdu form too. "Col", "Capt", "Maj" and a
# bare "Lt" had none, so in Urdu mode they stayed Latin — three letters in an Urdu
# sentence, which is the failure the acronym table in providers/tts.py exists to fix.
# The spelled-out English forms are listed as well, because the model writes those when
# the prompt tells it to keep a title in full.
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

# "(Retd)" is read as "Grade" and "(Late)" swallows the surrounding words, but the bare
# words are said correctly. A plain substitution would leave the ungrammatical
# "Brigadier Sumair Ashraf Sheikh Retired ...", so the suffix is lifted out and
# re-attached in front of the rank it belongs to: "Retired Brigadier Sumair ...".
# Longest first: "Lieutenant General" must win over "Lieutenant", or the suffix would
# be re-attached in front of half a rank ("Retired Lieutenant General ..." vs
# "Retired Lieutenant" followed by a stranded "General").
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

    # Last: any name word the full-name pass did not already consume. A reply that
    # says "Kazmi" or "Faheem" on its own has to be said the same way as the sentence
    # that gave the name in full. Runs in both languages, for the same reason the
    # tables above do.
    if _WORD_RE is not None:
        text = _WORD_RE.sub(lambda m: _KNOWN_WORDS[m.group(0)], text)

    return text
