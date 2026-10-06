"""ABBR → full-form glossary mined from the knowledge base.

Retrieval ranks whole chunks, so an abbreviation used in many chunks but defined in one
may never reach the model with its definition. The retriever scans the corpus for
"ABBR (Full Form)" / "Full Form (ABBR)" pairs and injects the matching definitions.
The corpus is an annual report, where most parentheses are asides ("EPS 54.25
(restated)", "OGDCL (20%)"); ``_is_plausible_definition`` rejects those.
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
    """Definitions contain no digits, run to 2-10 words, and start with the abbreviation's letter."""
    if not full_form or len(full_form) < 3:
        return False
    if _MOSTLY_NUMERIC_RE.match(full_form) or _HAS_DIGIT_RE.search(full_form):
        return False

    words = full_form.split()
    # A one-word "expansion" ("restated", "Gas", "MBA") is an aside, not a definition.
    if not 2 <= len(words) <= 10:
        return False

    # Only the first initial is compared: real forms drop connectives and keep plural heads.
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
                    # A comma ends the phrase, or a comma-separated list is glued into one.
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
