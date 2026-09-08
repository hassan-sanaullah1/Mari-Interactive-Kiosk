"""Deterministic opener, and feminine agreement, for Maryam's replies.

The greeting prompts ask every first reply to open with the salam and her name —
"السلام علیکم" in Urdu, "Assalamualaikum" in English. DeepSeek obeyed;
Qwen 3.5 does not — sampling twelve greetings it opened with "وعلیکم السلام", with
"آپ کا خیر مقدم ہے", or with no salam at all about a third of the time, and once invented
the non-word "نمٹے".

The opener is a fixed string on a turn the server has already identified as a greeting
(``knowledge.is_greeting``), so it does not need to be left to the model. This trims
whatever opener the model produced and puts the required one back. Everything after the
opener — the introduction, her name, the wording, the tone — is still the model's.
"""

from __future__ import annotations

import re

SALAM_UR = "السلام علیکم"
SALAM_EN = "Assalamualaikum"

# Openers seen from Qwen in place of the required salam: a returned salam, a welcome
# phrase, an invented non-word, or a thanks. Matched only at the very start of a reply.
_WRONG_OPENER_UR = re.compile(
    r"^\s*(?:"
    r"و\s*علیکم\s*السلام|وعلیکم\s*السلام|"
    r"نمٹے|نمستے|آداب(?:\s*عرض)?|جی\s*آیاں\s*نوں|"
    r"آپ\s*کا\s*(?:خیر\s*مقدم|شکریہ)\s*(?:ہے)?|خیر\s*مقدم|"
    r"السلام\s*علیکم"
    r")\s*[!،,۔.]*\s*",
)

# A reply may also bury the welcome phrase right after a correct salam.
_STRAY_WELCOME_UR = re.compile(r"(?<=^السلام علیکم[،!] )(?:آپ\s*کا\s*خیر\s*مقدم\s*ہے\s*[،!]\s*)")

# The English greeting prompt asks for the same opener, and the same models drift the
# same way — "Hello!", "Hi there", "Welcome to Mari Energies", or a returned
# "Walaikum assalam". Matched only at the very start of a reply.
# "as-salamu", "assalam", "salaam" — the salam word itself, however it is spelt.
_SALAM_WORD_EN = r"(?:as?[\-\s]*)?salaa?m[ou]?"
_ALAIKUM_EN = r"a?l[ae][iy]kum"

_WRONG_OPENER_EN = re.compile(
    r"^\s*(?:"
    # a returned salam: "Walaikum assalam", "Wa alaikum as-salam"
    rf"w[ae]?['’]?[\-\s]*{_ALAIKUM_EN}[\-\s,]*{_SALAM_WORD_EN}|"
    # a correct-but-duplicated salam: "Assalamualaikum", "Assalam o alaikum"
    rf"{_SALAM_WORD_EN}[\-\s]*(?:o[\-\s]*)?{_ALAIKUM_EN}"
    r"(?:[\-\s]*wa[\-\s]*rahmatullah\w*(?:[\-\s]*wa[\-\s]*barakatuh?u?)?)?|"
    # a plain English opener in place of the salam
    rf"{_SALAM_WORD_EN}|hello|hi(?:\s+there)?|hey|greetings|"
    r"good\s+(?:morning|afternoon|evening)|"
    r"welcome(?:\s+to\s+Mari\s+Energies)?"
    # \b matters: without it "hi" eats the start of "Highly" and "hey" of "Heyward".
    r")\b\s*[!,.—\-]*\s*",
    re.IGNORECASE,
)


def force_salam(reply: str, lang: str = "ur") -> str:
    """Ensure a greeting reply opens with the salam — "السلام علیکم" in Urdu,
    "Assalamualaikum" in English.

    Call ONLY on turns where the visitor actually greeted — on any other turn the base
    prompt forbids a salam, and adding one would be wrong.

    The visitor's name for the persona ("Maryam" / "مریم") is left to the greeting
    prompt: the model reliably places it in a natural sentence, and splicing it in
    deterministically would collide with whatever introduction the model already wrote.
    """
    if not reply:
        return reply
    if lang == "ur":
        body = _WRONG_OPENER_UR.sub("", reply, count=1).lstrip(" ،,!۔.")
        if not body:
            return reply
        return _STRAY_WELCOME_UR.sub("", f"{SALAM_UR}، {body}")
    if lang == "en":
        body = _WRONG_OPENER_EN.sub("", reply, count=1).lstrip(" ,!.")
        if not body:
            return reply
        # Keep the visitor's capitalisation of the first real word; only the opener moved.
        return f"{SALAM_EN}! {body}"
    return reply


# ── feminine agreement ──────────────────────────────────────────────
# Maryam is a female persona and Urdu marks gender on the possessive too, not just on
# verbs. The prompt covers the verbs ("کر سکتی ہوں") and Qwen gets those right, but it
# intermittently writes "میں Mari Energies کا AI Representative ہوں" — masculine "کا"
# where a female speaker needs "کی". It is roughly one reply in twelve, which is exactly
# the kind of intermittent slip a prompt rule cannot be relied on to catch.
#
# Scoped to the SELF-DESCRIPTION only. "Mari Energies کے kiosk پر" is correct as it
# stands: there the possessive agrees with "kiosk", not with Maryam, so a blanket
# کا/کے → کی rewrite would introduce errors rather than remove them.
_ROLE = r"AI Representative|نمائندہ|نمائندگی|میزبان|اسسٹنٹ|assistant"
_SELF_IZAFAT_RE = re.compile(rf"\b(کا|کے)(\s+(?:ایک\s+)?(?:{_ROLE}))")

# "میں ... کا AI Representative ہوں" — only when the sentence is about the speaker.
_SPEAKER_CLAUSE_RE = re.compile(r"میں\b[^۔!؟\n]{0,120}")


def feminine_agreement(reply: str, lang: str = "ur") -> str:
    """Fix masculine possessives in Maryam's own self-description.

    Only rewrites "کا/کے" when it directly precedes a role noun inside a clause that
    starts with "میں" (I), so possessives belonging to anything else are left alone.
    """
    if lang != "ur" or not reply:
        return reply

    def fix_clause(m: re.Match[str]) -> str:
        return _SELF_IZAFAT_RE.sub(lambda g: "کی" + g.group(2), m.group(0))

    return _SPEAKER_CLAUSE_RE.sub(fix_clause, reply)
