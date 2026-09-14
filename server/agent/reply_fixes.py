"""Fixes applied to the LLM's reply text before it is shown and spoken.

The model follows the prompt on these only most of the time, so they are enforced in
code: the salam that must open a greeting reply, and Urdu gender agreement for the
presenter on screen.
"""

from __future__ import annotations

import re

SALAM_UR = "السلام علیکم"
SALAM_EN = "Assalamualaikum"
# The returned salam, for a visitor who greeted with one.
REPLY_SALAM_UR = "وعلیکم السلام"
REPLY_SALAM_EN = "Walaikum Assalam"

# ── Salam opener ────────────────────────────────────────────────────

# Openers the model writes instead of the salam: a returned salam, a welcome phrase, an
# invented word, a thanks. Matched only at the very start of a reply.
_WRONG_OPENER_UR = re.compile(
    r"^\s*(?:"
    r"و\s*علیکم\s*السلام|وعلیکم\s*السلام|"
    r"نمٹے|نمستے|آداب(?:\s*عرض)?|جی\s*آیاں\s*نوں|"
    r"آپ\s*کا\s*(?:خیر\s*مقدم|شکریہ)\s*(?:ہے)?|خیر\s*مقدم|"
    r"السلام\s*علیکم"
    r")\s*[!،,۔.]*\s*",
)

# A welcome phrase buried right after a correct salam. The opener is captured and put
# back, since a fixed-width lookbehind cannot span two salams of different lengths.
_STRAY_WELCOME_UR = re.compile(
    r"^(وعلیکم السلام|السلام علیکم)([،!] )(?:آپ\s*کا\s*خیر\s*مقدم\s*ہے\s*[،!]\s*)"
)

_SALAM_WORD_EN = r"(?:as?[\-\s]*)?salaa?m[ou]?"
_ALAIKUM_EN = r"a?l[ae][iy]kum"

_WRONG_OPENER_EN = re.compile(
    r"^\s*(?:"
    # a returned salam: "Walaikum assalam", "Wa alaikum as-salam"
    rf"w[ae]?['’]?[\-\s]*{_ALAIKUM_EN}[\-\s,]*{_SALAM_WORD_EN}|"
    # a duplicated salam: "Assalamualaikum", "Assalam o alaikum"
    rf"{_SALAM_WORD_EN}[\-\s]*(?:o[\-\s]*)?{_ALAIKUM_EN}"
    r"(?:[\-\s]*wa[\-\s]*rahmatullah\w*(?:[\-\s]*wa[\-\s]*barakatuh?u?)?)?|"
    # a plain English opener
    rf"{_SALAM_WORD_EN}|hello|hi(?:\s+there)?|hey|greetings|"
    r"good\s+(?:morning|afternoon|evening)|"
    r"welcome(?:\s+to\s+Mari\s+Energies)?"
    # \b stops "hi" eating the start of "Highly".
    r")\b\s*[!,.—\-]*\s*",
    re.IGNORECASE,
)


def force_salam(reply: str, lang: str = "ur", returning: bool = False) -> str:
    """Make a greeting reply open with exactly one salam.

    ``returning`` is True when the visitor greeted with a salam: it is answered with
    "وعلیکم السلام" / "Walaikum Assalam", as a Pakistani receptionist would. Otherwise
    the kiosk offers its own "السلام علیکم" / "Assalamualaikum".

    Call only on greeting turns; on any other turn the prompt forbids a salam. The
    presenter's name is left to the model, which already places it in a sentence.
    """
    if not reply:
        return reply
    if lang == "ur":
        body = _WRONG_OPENER_UR.sub("", reply, count=1).lstrip(" ،,!۔.")
        if not body:
            return reply
        salam = REPLY_SALAM_UR if returning else SALAM_UR
        return _STRAY_WELCOME_UR.sub(r"\1\2", f"{salam}، {body}")
    if lang == "en":
        body = _WRONG_OPENER_EN.sub("", reply, count=1).lstrip(" ,!.")
        if not body:
            return reply
        return f"{REPLY_SALAM_EN if returning else SALAM_EN}! {body}"
    return reply


# ── Feminine agreement (female presenter) ───────────────────────────
# Only the self-description is touched: in "Mari Energies کے kiosk پر" the possessive
# agrees with "kiosk", so a blanket کا/کے → کی rewrite would introduce errors.

_ROLE = r"AI Representative|نمائندہ|نمائندگی|میزبان|اسسٹنٹ|assistant"
_SELF_IZAFAT_RE = re.compile(rf"\b(کا|کے)(\s+(?:ایک\s+)?(?:{_ROLE}))")
# A clause about the speaker: from "میں" to the end of the sentence.
_SPEAKER_CLAUSE_RE = re.compile(r"میں\b[^۔!؟\n]{0,120}")


def feminine_agreement(reply: str, lang: str = "ur") -> str:
    """Rewrite "کا/کے" to "کی" before a role noun in a clause that starts with "میں"."""
    if lang != "ur" or not reply:
        return reply

    def fix_clause(m: re.Match[str]) -> str:
        return _SELF_IZAFAT_RE.sub(lambda g: "کی" + g.group(2), m.group(0))

    return _SPEAKER_CLAUSE_RE.sub(fix_clause, reply)


# ── Masculine agreement (male presenter) ────────────────────────────
# Not a mirror of the feminine pass: the male rig also needs verb endings fixed.
# A feminine ending before "ہوں" (first person singular) can only be the speaker, so
# those apply to the whole reply. The perfective forms have no such anchor and are
# limited to the speaker's own clause, which stops at anything that can start a new
# subject (a subordinator, a comma, sentence punctuation). The ergative "میں نے ..."
# agrees with the object, so past-tense verbs are never rewritten.

_BREAK_WORDS = ("کہ", "اور", "جو", "جب", "لیکن", "کیونکہ", "تاکہ")
_SPEAKER_SPAN = (
    r"(?:(?!" + "|".join(rf"{w}\b" for w in _BREAK_WORDS) + r")[^۔!؟\n،,]){0,60}?"
)

_FEM_VERB_RE = (
    (re.compile(r"تی(?=\s+ہوں)"), "تا"),      # کر سکتی ہوں → کر سکتا ہوں
    (re.compile(r"رہی(?=\s+ہوں)"), "رہا"),    # بتا رہی ہوں → بتا رہا ہوں
    # "سکی" alone is also correct for other subjects ("ٹیم مدد کر سکی").
    (re.compile(rf"(میں\b{_SPEAKER_SPAN})سکی\b"), r"\1سکا"),
    (re.compile(rf"(میں\b{_SPEAKER_SPAN})پائی\b"), r"\1پایا"),
)

_SELF_IZAFAT_M_RE = re.compile(rf"\b(کی)(\s+(?:ایک\s+)?(?:{_ROLE}))")


def masculine_agreement(reply: str, lang: str = "ur") -> str:
    """Fix feminine verb endings and possessives in the male presenter's self-description."""
    if lang != "ur" or not reply:
        return reply

    for pattern, replacement in _FEM_VERB_RE:
        reply = pattern.sub(replacement, reply)

    def fix_clause(m: re.Match[str]) -> str:
        return _SELF_IZAFAT_M_RE.sub(lambda g: "کا" + g.group(2), m.group(0))

    return _SPEAKER_CLAUSE_RE.sub(fix_clause, reply)


def gender_agreement(reply: str, lang: str = "ur", avatar: str = "female") -> str:
    """The agreement pass for the presenter on screen; unknown ids get the female one."""
    if avatar == "male":
        return masculine_agreement(reply, lang)
    return feminine_agreement(reply, lang)
