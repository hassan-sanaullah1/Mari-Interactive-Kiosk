"""ABBR → full-form glossary built from the Mari Energies knowledge base.

Retrieval here is BM25 over heading-delimited chunks (``server/knowledge.py``), and it
ranks whole sections. An abbreviation like "MSPC" or "CDRS" can be *used* in a dozen
sections but *spelled out* in only one, so the sections a question actually surfaces may
never contain the definition — leaving the model to guess. This module scans the whole
corpus once at import time for "ABBR (Full Form)" / "Full Form (ABBR)" pairs, so the
definition can be force-injected whenever a visitor asks about the abbreviation,
independent of what retrieval returned.

Adapted from a reference implementation written for a cybersecurity corpus. The
extraction mechanism is unchanged; the filtering is not. This knowledge base is an
annual-report export, where parentheses are used far more often for asides than for
definitions:

    "EPS 54.25 (restated)"                 → EPS = "restated"
    "OGDCL (20%)"                          → OGDCL = "20%"
    "energy use 4,344,223 GJ (2024: ...)"  → GJ  = "2024: 4,344,223 GJ"

Injected as authoritative definitions, those would actively produce wrong answers — the
opposite of what this module is for. ``_is_plausible_definition`` rejects them.
"""

from __future__ import annotations

import re

_ABBR_TOKEN_RE = re.compile(r"^[A-Z][A-Z0-9]{1,9}$")

# Lowercase connectives allowed inside a full form during the backward scan
# ("Oil & Gas Development Company Limited", "Institute of Chartered Accountants").
_CONNECTIVE_WORDS = {"of", "the", "and", "for", "&", "a", "an", "to", "in"}

# Short all-caps tokens that are ordinary words or markup, not abbreviations.
_NOT_ABBREVIATIONS = {
    "NEW", "OLD", "ALL", "ANY", "ARE", "NOT", "YES", "NOW", "WHO",
    "WHY", "CAN", "MAY", "OUR", "YOUR", "ITS", "OUT", "TOP", "TBD",
    # Seen in this corpus specifically: table headers and emphasis markers.
    "FY", "YOY", "QOQ", "NOTE", "TOTAL", "NIL",
}

# A definition never starts with these — they signal a continuation fragment the
# backward scan ran into ("and Debt Service Reserve Account", "Ltd").
_LEADING_NOISE = {"and", "the", "an", "a", "of", "for", "to", "in", "ltd", "limited"}

_PAREN_RE = re.compile(r"\(([^()]{2,80})\)")
_PRECEDING_WORD_RE = re.compile(r"([A-Za-z][A-Za-z0-9]{1,9})$")

# Rejects "20%", "2024: 4,344,223 GJ", "1,608,492 MT" — an expansion of an
# abbreviation is words, not a measurement.
_MOSTLY_NUMERIC_RE = re.compile(r"^[\d\s,.:%–—-]*$")
_HAS_DIGIT_RE = re.compile(r"\d")


def _looks_like_abbr(token: str) -> bool:
    return bool(_ABBR_TOKEN_RE.match(token)) and token not in _NOT_ABBREVIATIONS


def _clean_full_form(full_form: str) -> str:
    """Strip leading articles/connectives the backward scan may have swept up."""
    words = full_form.split()
    while words and words[0].lower() in _LEADING_NOISE:
        words.pop(0)
    return " ".join(words).strip(" ,.;:—-")


def _is_plausible_definition(abbr: str, full_form: str) -> bool:
    """Reject parenthetical asides that are not definitions at all.

    The corpus is an annual report, so "(20%)", "(restated)" and "(2024: 728 ML)" sit in
    exactly the same syntactic position a real definition does. Three cheap signals
    separate them: definitions contain no digits, run to more than one word, and their
    initials line up with the abbreviation they define.
    """
    if not full_form or len(full_form) < 3:
        return False
    if _MOSTLY_NUMERIC_RE.match(full_form) or _HAS_DIGIT_RE.search(full_form):
        return False

    words = full_form.split()
    # A one-word "expansion" ("restated", "Gas", "MBA") is an aside, not a definition.
    if not 2 <= len(words) <= 10:
        return False

    # The initials should broadly match the abbreviation. Requiring an exact match is
    # too strict — real forms drop connectives ("Health Safety & Environment" = HSE) and
    # keep plural/compound heads — so this only asks that the first letters agree, which
    # is enough to throw out "EPS = restated" while keeping the genuine entries.
    initials = [w[0].upper() for w in words if w[0].isalpha() and w.lower() not in _CONNECTIVE_WORDS]
    return bool(initials) and initials[0] == abbr[0].upper()


def extract_glossary(text: str) -> dict[str, str]:
    """Extract ABBR → full-form pairs from free text.

    Handles both orderings that occur in the knowledge base:
      - "MSPC (Mari Seismic Processing Center)"   [abbr inside the parentheses]
      - "Health Safety & Environment (HSE)"       [full form first]
    """
    pairs: dict[str, str] = {}

    for m in _PAREN_RE.finditer(text):
        inner = m.group(1).strip()

        if _looks_like_abbr(inner):
            # Full form precedes the parenthesis — walk backward collecting a
            # title-case phrase, capped at 8 words.
            before = text[: m.start()]
            words = before.split()
            candidate: list[str] = []
            for w in reversed(words[-10:]):
                clean = w.strip(" ,.;:—-")
                if not clean:
                    break
                if clean[0].isupper() or clean.lower() in _CONNECTIVE_WORDS:
                    candidate.insert(0, clean)
                    # A comma ends the phrase. This corpus lists subsidiaries and
                    # employers comma-separated ("... Fauji Meat Limited, Pakistan
                    # Maroc Phosphate (FFBL)"), and without this the scan walks
                    # straight through the separators and glues several list items
                    # into one bogus "full form".
                    if w.rstrip().endswith(","):
                        break
                else:
                    break
            abbr = inner
            full_form = _clean_full_form(" ".join(candidate))
            if _is_plausible_definition(abbr, full_form):
                if abbr not in pairs or len(full_form) > len(pairs[abbr]):
                    pairs[abbr] = full_form
        else:
            # "Full Form (ABBR)" — the word right before "(" is the abbreviation.
            before = text[: m.start()].rstrip()
            prev = _PRECEDING_WORD_RE.search(before)
            if prev:
                abbr = prev.group(1)
                full_form = _clean_full_form(inner)
                if _looks_like_abbr(abbr) and _is_plausible_definition(abbr, full_form):
                    if abbr not in pairs or len(full_form) > len(pairs[abbr]):
                        pairs[abbr] = full_form

    return pairs


def find_glossary_matches(query: str, glossary: dict[str, str]) -> dict[str, str]:
    """Glossary entries whose abbreviation appears as a whole word in the query."""
    if not glossary or not query:
        return {}
    matches: dict[str, str] = {}
    for abbr, full_form in glossary.items():
        if re.search(rf"\b{re.escape(abbr)}\b", query, re.IGNORECASE):
            matches[abbr] = full_form
    return matches


def format_glossary_block(matches: dict[str, str]) -> str:
    """Format matched entries as a context block to prepend to the retrieved sections."""
    if not matches:
        return ""
    lines = [f"{abbr} = {full_form}" for abbr, full_form in matches.items()]
    return (
        "Glossary (authoritative — use these exact definitions if asked "
        "about these terms):\n" + "\n".join(lines)
    )
