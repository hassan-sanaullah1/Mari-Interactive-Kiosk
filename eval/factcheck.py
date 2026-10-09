"""Scores one English reply against the facts it was required to contain.

The tester's grades in ``eval/data/tester_eval.csv`` are "Matched",
"Partial" and "Not Matched", and a Partial always means the same thing: the reply was
true but left out facts the Expected Answer carried. So the scoring unit here is a
*required fact*, and the grade is just how many of them survived into the reply.

Matching is substring matching, not similarity. The questions are about auditors, NTN
numbers and board committees — the fact either appears or it does not, and a fuzzy score
would turn a missing "A.F." into a 0.94 that nobody can act on.

Two things make plain substring matching work on spoken replies:

  canon()      folds away the differences that are never meaningful — case, en/em
               dashes against hyphens, the thousands separators in "322,973", and
               punctuation the model puts where the knowledge base did not.
  tts_canon()  runs the kiosk's own TTS normaliser over BOTH sides. The system prompt
               tells the model to write "127,000 boepd", the tested replies say "one
               hundred and twenty-seven thousand barrels of oil equivalent per day",
               and server/normalization.py already knows that those are the same
               number. Reusing it beats writing a words-to-digits inverse that would
               be wrong in new ways.

canon() is tried first and tts_canon() only as a fallback, so a change to the TTS
normaliser can add matches but never take one away.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from server.normalization import normalize_for_tts

__all__ = ["GRADES", "Entry", "FactScore", "canon", "hit", "score", "tts_canon"]

GRADES = ("Matched", "Partial", "Not Matched")

_DASHES = dict.fromkeys(map(ord, "‐‑‒–—―−"), "-")
_DIGIT_SEP = re.compile(r"(?<=\d)[, ](?=\d\d\d\b)")
# Hyphens become spaces rather than surviving: the TTS normaliser spells 127,000 as
# "twenty seven" where the model writes "twenty-seven", and a kept hyphen makes those
# two renderings of the same number miss each other. Hyphenated spans ("1975-2006",
# "FY2024-25") fold the same way on both sides, so they still match.
_KEEP = re.compile(r"[^0-9a-z%&./+ ]+")
_SPACE = re.compile(r"\s+")


def canon(text: str) -> str:
    """Lowercase, dash- and separator-normalised, punctuation-stripped text.

    ``%``, ``&``, ``.``, ``/`` and ``+`` are kept: they carry meaning in the facts
    being checked ("40%", "A.F.", "AAA/A1", "35+"). Hyphens do not survive — see above.
    """
    out = unicodedata.normalize("NFKC", text).casefold().translate(_DASHES)
    out = _DIGIT_SEP.sub("", out)
    return _SPACE.sub(" ", _KEEP.sub(" ", out)).strip()


def tts_canon(text: str) -> str:
    """``canon`` of the text as the kiosk would speak it, so numerals meet number words."""
    try:
        return canon(normalize_for_tts(text, "en"))
    except Exception:  # noqa: BLE001 - a normaliser crash must not fail the eval
        return canon(text)


def hit(variants: list[str] | str, haystack: str, spoken: str | None = None) -> bool:
    """True when any accepted surface form of one required fact is present.

    ``haystack`` is the raw reply; ``spoken`` is its ``tts_canon`` form, passed in by
    ``score`` so it is computed once per reply rather than once per variant.
    """
    if isinstance(variants, str):
        variants = [variants]
    flat = canon(haystack)
    spoken = spoken if spoken is not None else tts_canon(haystack)
    for v in variants:
        if not v.strip():
            continue
        if canon(v) and canon(v) in flat:
            return True
        if tts_canon(v) and tts_canon(v) in spoken:
            return True
    return False


@dataclass
class Entry:
    """One required fact and what became of it."""

    variants: list[str]
    hit: bool
    in_context: bool | None = None  # None when no retrieved context was supplied

    @property
    def cause(self) -> str | None:
        """Why this fact is missing: the retrieval stage, or the generation stage."""
        if self.hit:
            return None
        if self.in_context is None:
            return "unknown"
        return "generation" if self.in_context else "retrieval"

    def as_dict(self) -> dict:
        return {
            "variants": self.variants,
            "hit": self.hit,
            "in_context": self.in_context,
            "cause": self.cause,
        }


@dataclass
class FactScore:
    grade: str
    entries: list[Entry] = field(default_factory=list)
    optional_hits: int = 0
    optional_total: int = 0

    @property
    def hits(self) -> int:
        return sum(1 for e in self.entries if e.hit)

    @property
    def total(self) -> int:
        return len(self.entries)

    @property
    def missing(self) -> list[list[str]]:
        return [e.variants for e in self.entries if not e.hit]

    def causes(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for e in self.entries:
            if e.cause:
                out[e.cause] = out.get(e.cause, 0) + 1
        return out

    def as_dict(self) -> dict:
        return {
            "grade": self.grade,
            "hit": self.hits,
            "total": self.total,
            "entries": [e.as_dict() for e in self.entries],
            "optional_hits": self.optional_hits,
            "optional_total": self.optional_total,
            "causes": self.causes(),
        }


def score(
    require, optional, reply: str, context: str | None = None, cap_hit: bool = False
) -> FactScore:
    """Grade ``reply`` against the required facts.

    All required facts present is "Matched", some is "Partial", none is "Not Matched" —
    the tester's own three values, so a run compares against their column directly. With
    no required facts the case cannot be graded and comes back "Matched" by vacuity,
    which ``run_answers`` reports separately rather than counting as a pass.

    ``context`` is the assembled retrieved knowledge. Supplying it splits a miss into
    "the fact never reached the model" and "the model had it and dropped it", which is
    the difference between a retrieval fix and a prompt fix. ``cap_hit`` relabels a
    generation miss as ``cap`` when the reply was cut off at the token limit.
    """
    require = require or []
    optional = optional or []
    spoken_reply = tts_canon(reply)
    spoken_ctx = tts_canon(context) if context else None

    entries = []
    for variants in require:
        got = hit(variants, reply, spoken_reply)
        in_ctx = None if context is None else hit(variants, context, spoken_ctx)
        entries.append(Entry(variants if isinstance(variants, list) else [variants], got, in_ctx))

    if cap_hit:
        for e in entries:
            if e.cause == "generation":
                e.in_context = True  # keep the flag, relabel below via run_answers
    hits = sum(1 for e in entries if e.hit)
    grade = "Matched" if hits == len(entries) else ("Not Matched" if hits == 0 else "Partial")

    opt_hits = sum(1 for v in optional if hit(v, reply, spoken_reply))
    return FactScore(
        grade=grade, entries=entries, optional_hits=opt_hits, optional_total=len(optional)
    )
