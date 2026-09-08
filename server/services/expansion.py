"""Urdu → English query expansion for the lexical channel.

Discovered by the eval harness, and worth writing down because it is not obvious.

The dense model (multilingual-e5-large) aligns Urdu and English well enough to beat the
old BM25 retriever on English questions by six points of hit@5. On *Urdu* questions it
loses to it by fifteen. The reason is that server/knowledge.py carries a hand-built,
corpus-specific Urdu layer that no general-purpose embedding model reproduces:

  * a curated topic glossary ("ریکروٹمنٹ" -> recruitment process careers hiring),
  * multi-word phrase mappings, because Urdu spells acronyms out letter by letter
    ("پی ایس ایکس" is P-S-X, three tokens that individually mean nothing),
  * a phonetic index that matches proper nouns across scripts on a consonant skeleton,
    which is how "آیلہ مجید" finds "Ayla Majid" and "کارپلنک" finds "Corplink".

That layer took real effort to build and is tuned against this exact corpus. Deleting it
in favour of a multilingual embedding would have been a fifteen-point regression on half
the kiosk's traffic, and nothing except the eval set would have revealed it — the
English half would have looked like a clean win.

So it is kept, and pointed at the channel it helps most. The sparse/BM25 channel is
purely lexical: an Urdu query contributes essentially nothing to it against an English
corpus, so the expansion is what makes that channel work at all for Urdu. The dense
channel keeps the original text, where the model's own cross-lingual alignment is
better than a bag of expanded keywords.

The tables themselves are not duplicated here — they are imported from
server/knowledge.py, which remains their single source of truth and is covered by
tests/test_retrieval.py. If that module is ever retired, the tables move to voice_config
(where the rest of the language configuration lives) rather than being copied.
"""

from __future__ import annotations

import logging
import re

log = logging.getLogger(__name__)

# Any character in the Urdu/Arabic block. Cheap test for "is expansion even relevant".
_URDU_RE = re.compile(r"[؀-ۿ]")

try:
    from .. import knowledge as _knowledge
except Exception:  # noqa: BLE001 - pragma: no cover
    _knowledge = None  # type: ignore[assignment]

# Terms below this expansion weight are the glossary's broadest topic guesses. They are
# useful as a hint to a ranker that already has other signal, and actively harmful as
# the *only* content of a lexical query — a single Urdu word expands to four or five
# broad English ones, and BM25 will happily rank a section that contains all of them
# above the one that actually names the thing asked about.
_MIN_WEIGHT = 0.5


def has_urdu(text: str) -> bool:
    return bool(_URDU_RE.search(text or ""))


def expand_for_lexical(query: str) -> tuple[str, list[str]]:
    """Return (query text for the sparse channel, terms that were added).

    An all-English query passes through untouched — expansion has nothing to add, and
    the returned term list is empty so the trace shows it did not fire.
    """
    if not query or not has_urdu(query) or _knowledge is None:
        return query, []
    try:
        weighted = _knowledge._expand_weighted(query)
    except Exception:  # noqa: BLE001
        log.exception("Urdu query expansion failed; using the raw query for BM25")
        return query, []

    terms = sorted(
        (t for t, w in weighted.items() if w >= _MIN_WEIGHT and t.isascii()),
        key=lambda t: (-weighted[t], t),
    )
    if not terms:
        return query, []
    # The original text stays in front of the expansion. Any Latin-script token the
    # visitor actually said — "Sky47", "PSX", a name — is the strongest lexical signal
    # available, and must not be diluted by keywords we inferred.
    return f"{query} {' '.join(terms)}", terms
