"""Builds a persistent ABBR -> full-form glossary from the ingested knowledge
base, so short-form questions (e.g. "what is SOC") are always grounded in the
document's own definition — independent of whether semantic chunk retrieval
happens to surface the specific chunk that spells it out.

A large knowledge base can mention an abbreviation like "SOC" dozens of times
across many chunks, but only spell out its full form in one or two of them.
With top-k semantic retrieval, it's entirely possible for a query to surface
only chunks that USE the abbreviation without ever DEFINING it — leaving the
LLM to guess (hallucinate) despite the correct answer existing elsewhere in
the same document. This module extracts every "ABBR (Full Form)" /
"Full Form (ABBR)" pair found anywhere in the corpus once, up front, so the
definition can always be force-injected into context regardless of retrieval.
"""

from __future__ import annotations

import re

_ABBR_TOKEN_RE = re.compile(r"^[A-Z][A-Z0-9]{1,9}$")

# Lowercase connective words allowed inside a "full form" phrase during the
# backward scan (e.g. "Chief Information Security Officer" or "Oil & Gas
# Development Company Limited").
_CONNECTIVE_WORDS = {"of", "the", "and", "for", "&", "a", "an", "to", "in"}

# Common English words that happen to be short/all-caps in source markdown
# (e.g. a "[NEW]" annotation) but aren't actual abbreviations — excluded so
# they don't pollute the glossary with bogus entries.
_NOT_ABBREVIATIONS = {
    "NEW", "OLD", "ALL", "ANY", "ARE", "NOT", "YES", "NOW", "WHO",
    "WHY", "CAN", "MAY", "OUR", "YOUR", "ITS", "OUT", "TOP", "TBD",
}

_PAREN_RE = re.compile(r"\(([^()]{2,80})\)")
_PRECEDING_WORD_RE = re.compile(r"([A-Za-z][A-Za-z0-9]{1,9})$")


def _looks_like_abbr(token: str) -> bool:
    return bool(_ABBR_TOKEN_RE.match(token)) and token not in _NOT_ABBREVIATIONS


def extract_glossary(text: str) -> dict[str, str]:
    """Extract ABBR -> full-form pairs from free text.

    Handles both orderings seen in real documents:
      - "SOC (Security Operations Center)"            [abbr first]
      - "Chief Information Security Officer (CISO)"    [full form first]
    """
    pairs: dict[str, str] = {}

    for m in _PAREN_RE.finditer(text):
        inner = m.group(1).strip()

        if _looks_like_abbr(inner):
            # Full form precedes the parenthesis — walk backward collecting
            # a title-case phrase, capped at 8 words.
            before = text[: m.start()]
            words = before.split()
            candidate: list[str] = []
            for w in reversed(words[-10:]):
                clean = w.strip(" ,.;:—-")
                if not clean:
                    break
                if clean[0].isupper() or clean.lower() in _CONNECTIVE_WORDS:
                    candidate.insert(0, clean)
                else:
                    break
            full_form = " ".join(candidate).strip(" ,.")
            if full_form and 1 <= len(full_form.split()) <= 8:
                abbr = inner
                if abbr not in pairs or len(full_form) > len(pairs[abbr]):
                    pairs[abbr] = full_form
        else:
            # "Full Form (ABBR)" — the word immediately before "(" is the
            # abbreviation candidate; only handle the direct case here.
            before = text[: m.start()].rstrip()
            prev = _PRECEDING_WORD_RE.search(before)
            if prev:
                candidate_abbr = prev.group(1)
                if _looks_like_abbr(candidate_abbr) and 1 <= len(inner.split()) <= 10:
                    if candidate_abbr not in pairs or len(inner) > len(pairs[candidate_abbr]):
                        pairs[candidate_abbr] = inner

    return pairs


def find_glossary_matches(query: str, glossary: dict[str, str]) -> dict[str, str]:
    """Return glossary entries whose abbreviation appears as a whole word in query."""
    if not glossary or not query:
        return {}
    matches: dict[str, str] = {}
    for abbr, full_form in glossary.items():
        if re.search(rf"\b{re.escape(abbr)}\b", query, re.IGNORECASE):
            matches[abbr] = full_form
    return matches


def format_glossary_block(matches: dict[str, str]) -> str:
    """Format matched glossary entries as a context block to prepend to RAG context."""
    if not matches:
        return ""
    lines = [f"{abbr} = {full_form}" for abbr, full_form in matches.items()]
    return (
        "Glossary (authoritative — use these exact definitions if asked "
        "about these terms):\n" + "\n".join(lines)
    )
