"""STT domain-term correction for the retrieval query.

General-purpose STT mishears the corpus's content words ("Daharki" → "the har key",
"Fauji" → "Foji"), and that one word decides which section is retrieved.

Two rules for adding entries:

  * Only map terms whose *correct* form is domain vocabulary. Mapping a common English
    word to a domain term will fire on unrelated questions and is strictly worse than
    leaving the mishearing alone.
  * Match on word boundaries and case-insensitively, but write the replacement in the
    corpus's own casing, because the sparse/BM25 channel is sensitive to it.
"""

from __future__ import annotations

import re

# (pattern, replacement). Ordered: longer, more specific phrases first, so a multi-word
# mishearing is repaired before a single-word rule fires inside it.
CORRECTIONS: list[tuple[str, str]] = [
    # Company and brand
    (r"\bmari\s+petroleum\b", "Mari Petroleum"),
    (r"\bmar(?:y|ie|rie)\s+energ(?:y|ies)\b", "Mari Energies"),
    (r"\bmar(?:y|ie|rie)\b(?=\s+(?:energ|gas|petroleum|minerals|services|meal))", "Mari"),
    (r"\bm\.?\s*p\.?\s*c\.?\s*l\.?\b", "MPCL"),
    (r"\bsky\s*(?:forty[\s-]?seven|47)\b", "Sky47"),
    (r"\bgem\s+energy\b", "GEM Energy"),
    # Fields, wells and blocks — the highest-value corrections, because these are the
    # words a question is *about* and they appear nowhere else in the language.
    (r"\bthe\s+har\s*key\b|\bda?\s*har\s*key\b|\bdahar\s*key\b", "Daharki"),
    (r"\bbi?t*ai\b|\bbh?it\s*ai\b|\bbitay\b", "Bhitai"),
    (r"\bsu[jg]a?wa?l\b|\bsu\s+jawal\b", "Sujawal"),
    (r"\bwazir[iy]?stan\b|\bwaziri\s+stan\b", "Waziristan"),
    (r"\bshe+wa\b|\bshiva\b(?=\s+(?:field|block|well|development))", "Shewa"),
    (r"\bspin\s*wam\b|\bspinam\b", "Spinwam"),
    (r"\bso+ho\b(?=\s+(?:well|field|discovery|gas))", "Soho"),
    (r"\bh\.?\s*r\.?\s*l\.?\b(?=\s+(?:pressure|field|facilit))", "HRL"),
    # Owners, institutions, tickers
    (r"\bfo+[uw]?ji\b|\bfow?gee\b", "Fauji"),
    (r"\bo\.?\s*g\.?\s*d\.?\s*c\.?\s*l\.?\b|\bog\s+dcl\b", "OGDCL"),
    (r"\bp\.?\s*s\.?\s*[xs]\.?\b(?=\s|$)|\bpakistan\s+stock\s+exchange\b", "PSX"),
    (r"\bcorp\s*link\b", "Corplink"),
    (r"\bmeezan\b|\bmizan\b(?=\s+bank)", "Meezan"),
    # Business vocabulary the models routinely mangle
    (r"\bup\s+stream\b", "upstream"),
    (r"\bseis?mic\b|\bsize\s*mic\b", "seismic"),
    (r"\bem\s*bo+e\b|\bm\.?\s*m\.?\s*b\.?\s*o\.?\s*e\.?\b", "MMBOE"),
    (r"\bk\.?\s*b\.?\s*o\.?\s*e\.?\s*p\.?\s*d\.?\b|\bkay\s+bo+pd\b", "KBOEPD"),
    (r"\be\.?\s*p\.?\s*s\.?\b(?=\s|$)|\bearning\s+per\s+share\b", "EPS"),
    (r"\bn\.?\s*t\.?\s*n\.?\b(?=\s|$)", "NTN"),
    (r"\bc\.?\s*s\.?\s*r\.?\b(?=\s|$)", "CSR"),
    (r"\be\.?\s*s\.?\s*g\.?\b(?=\s|$)", "ESG"),
    (r"\bfree\s*float\b", "free float"),
    (r"\bco\s*location\b|\bcollocation\b", "colocation"),
]

_COMPILED: list[tuple[re.Pattern[str], str]] = [
    (re.compile(p, re.IGNORECASE), r) for p, r in CORRECTIONS
]


def correct_transcript(text: str) -> tuple[str, list[tuple[str, str]]]:
    """Apply the correction map. Returns (corrected text, [(before, after), ...]).

    The applied list is returned rather than logged here so the caller can put it in the
    turn's trace. Which corrections fire, and how often, is the only evidence available
    for whether an entry earns its place — and for spotting one that fires too eagerly.
    """
    if not text:
        return text, []
    applied: list[tuple[str, str]] = []
    out = text
    for pattern, replacement in _COMPILED:
        def _sub(m: re.Match[str]) -> str:
            if m.group(0) != replacement:
                applied.append((m.group(0), replacement))
            return replacement

        out = pattern.sub(_sub, out)
    return out, applied
