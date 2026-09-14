"""Decides whether a visitor's message is a greeting or an ask for an introduction.

Each turn is a stateless LLM call, so the model cannot tell an opening line from a
follow-up; the greeting prompt and the forced salam are applied only when this says so.
"""

from __future__ import annotations

import re

# Every way a visitor's salam reaches us: typed, or as Soniox writes it in either script.
# "Assalamualaikum", "Assalam o Alaikum", "As-salamu alaykum", "Salam alaikum",
# "السلام علیکم", "اسلام علیکم", "السلام و علیکم", "سلام علیکم". Optional blessing tail.
_SALAM = (
    r"(?:"
    r"(?:a?s?[-\s]*)?salaa?m(?:[-\s]*[ouw])?[-\s]*(?:o[-\s]*)?a?l[ae][iy]?kum"
    r"(?:[-\s]*wa?[-\s]*rahmatull[ae]h\w*(?:[-\s]*wa?[-\s]*barakatuh?u?)?)?|"
    r"(?:ال|ا)?سلام\s*(?:و\s*)?علیکم(?:\s*و\s*رحمۃ\s*اللہ(?:\s*و\s*برکاتہ)?)?"
    r")"
)
_SALAM_ONLY = r"salam|salaam|سلام"

# The visitor offered the salam, so it is returned ("Walaikum Assalam"), not repeated.
# After a greeting word it still counts: "Hi, assalamualaikum" is a salam too, but
# "what does salam mean" is not.
_LEAD_IN = r"(?:(?:hi|hey|hello|hallo|ji|jee|sir|madam|ہیلو|جی)[\s\W]+){0,2}"
_VISITOR_SALAM_RE = re.compile(
    rf"^[\s\W]*{_LEAD_IN}(?:{_SALAM}|{_SALAM_ONLY})(?!\w)",
    re.IGNORECASE,
)
# A visitor who answers with "Walaikum assalam" has not offered a salam to return.
_RETURNED_SALAM_RE = re.compile(
    rf"^[\s\W]*{_LEAD_IN}(?:w[ae]?['’]?[-\s]*a?l[ae][iy]?kum|و\s*علیکم)",
    re.IGNORECASE,
)

# Matched against the whole stripped message: "hi" greets, "what is Mari's history" does not.
_GREETING_RE = re.compile(
    r"^(?:"
    rf"{_SALAM}|salam|salaam|hi(?:\s+there)?|hey(?:\s+there)?|"
    r"hello(?:\s+there)?|hallo|yo|"
    r"good\s+(?:morning|afternoon|evening)|greetings|"
    # "How are you?" expects the introduction, not an answer about the company.
    r"how\s+(?:are|r)\s+(?:you|u)(?:\s+doing)?|how(?:'s|\s+is)\s+it\s+going|"
    r"how\s+do\s+you\s+do|what(?:'s|\s+is)\s+up|"
    r"kya\s+haal\s+(?:hai|hain)|kaise\s+(?:ho|hain)|"
    r"who\s+are\s+you|what\s+are\s+you|introduce\s+yourself|please\s+introduce\s+yourself|"
    r"tell\s+me\s+about\s+yourself|"
    r"what(?:'s|\s+is)\s+your\s+name|"
    r"السلام\s*علیکم|سلام|ہیلو|آداب|آپ\s+کون\s+ہیں|"
    r"(?:آپ\s+)?کیسی\s+ہیں(?:\s+آپ)?|(?:آپ\s+)?کیسے\s+ہیں(?:\s+آپ)?|"
    r"کیا\s+حال\s+ہے|کیا\s+حال\s+ہیں|سب\s+خیریت\s+ہے|"
    r"اپنا\s+(?:تعارف|انٹروڈکشن)\s*(?:کرائیں|کروائیں|کرا\s*دیں|دیجیے|دیجئے|دیں|دو)?|"
    r"تمہارا\s+نام\s+کیا\s+ہے|آپ\s+کا\s+نام\s+کیا\s+ہے"
    # "؟" (U+061F) is the question mark Urdu text actually uses; "۔" is the full stop.
    r")[\s!,.…?؟ـ۔]*$",
    re.IGNORECASE,
)

# The same asks as a PREFIX, for a message that greets and then asks something else:
# "السلام علیکم۔ اپنا انٹروڈکشن دیجیے، اور مجھے … بتائیے".
_URDU_INTRO_ASK = r"اپنا\s+(?:تعارف|انٹروڈکشن)\s*(?:کرائیں|کروائیں|کرا\s*دیں|دیجیے|دیجئے|دیں|دو)?"
_GREETING_PREFIX_RE = re.compile(
    r"^(?:please\s+)?(?:can\s+you\s+)?introduce\s+yourself\b|"
    r"^tell\s+me\s+about\s+yourself\b|"
    rf"^{_SALAM}(?!\w)|"
    r"^(?:hi|hey|hello)\b(?=.*\b(?:introduce\s+yourself|your\s+name|who\s+are\s+you)\b)|"
    r"^(?:hi|hey|hello|hallo)\b\s*[,!.…-]*\s*(?=how\s+(?:are|r)\s+(?:you|u))|"
    r"^how\s+(?:are|r)\s+(?:you|u)\b|"
    r"^(?:آپ\s+)?کیسی\s+ہیں|^(?:آپ\s+)?کیسے\s+ہیں|^کیا\s+حال\s+ہے|"
    r"^السلام\s*علیکم|"
    r"^سلام\b|"
    rf"^{_URDU_INTRO_ASK}",
    re.IGNORECASE,
)


def is_greeting(text: str) -> bool:
    stripped = (text or "").strip()
    return bool(_GREETING_RE.match(stripped) or _GREETING_PREFIX_RE.match(stripped)
                or said_salam(stripped))


def said_salam(text: str) -> bool:
    """True when the visitor opened with a salam, which the reply must return."""
    stripped = (text or "").strip()
    return bool(_VISITOR_SALAM_RE.match(stripped)) and not _RETURNED_SALAM_RE.match(stripped)
