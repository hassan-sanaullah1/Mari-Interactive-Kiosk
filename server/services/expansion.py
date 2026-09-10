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

# ── corpus subject ──────────────────────────────────────────────────

# Words that cannot carry a topic on their own. Used only to decide whether anything
# retrievable survives the strip — not to filter the query that gets embedded, which
# keeps its natural phrasing because the embedding model was trained on running text.
_FUNCTION_WORDS = frozenset(
    "a an the is are was were be been being do does did what which who whom whose when "
    "where why how tell me us you your our their about of for from to in on at by with "
    "and or but if then than that this these those it its there here can could would "
    "should will shall may might must have has had get give show say said please".split()
)

_SUBJECT_RE = re.compile(
    r"\b(?:mari\s*energies\s*limited|mari\s*energies|marienergies"
    r"|mari\s*petroleum\s*company\s*limited|mari\s*petroleum|mpcl)\b['\u2019]?s?",
    re.IGNORECASE,
)


def strip_corpus_subject(query: str) -> str:
    """Remove the corpus's own subject from a query, for the DENSE channel only.

    Every chunk in this knowledge base is about Mari Energies, so the company's name
    carries no information about WHICH chunk answers a question — but a dense embedding
    has no notion of document frequency, and cannot discount it the way BM25's IDF does.
    Naming the company therefore drags the query vector toward the generic
    "corporate overview" region of the space, and section 1 (a twelve-chunk overview of
    everything) wins on that similarity for almost any question.

    Measured on the corpus, dense rank of the answering section:

        question                                   as asked   subject stripped
        "What discoveries has [X] made recently?"        18           2
        "What are [X]'s production ... figures?"         20           1
        "Who is [X]'s CEO?"                              11           1
        "What is [X]'s corporate group structure?"        2           1

    Across the 342-question tester set this is worth +6.1 points of hit@1 (78.4% ->
    84.5%) and +2.4 of context precision, with the internal English set unchanged at
    81.1% hit@1 and its hit@3/@5 both up.

    Three deliberate limits:

    * Dense only. The sparse channel already handles this correctly — Qdrant's IDF
      modifier gives a term present in every document a weight near zero — and stripping
      there would throw away a genuine lexical signal for the questions that really are
      about the company's identity.
    * The Urdu forms are not listed, so Urdu queries are untouched. That is measured, not
      an oversight: the Urdu half of the eval set is identical either way, because the
      cross-lingual embedding does not align "ماری انرجیز" onto the English name strongly
      enough for it to dominate.
    * A query that is ONLY the subject ("Mari Energies?", "tell me about MariEnergies")
      is left alone — there is nothing else in it to retrieve on, and the overview
      section really is the right answer. That check counts CONTENT words, not tokens:
      "tell me about MariEnergies" strips to "tell me about", which is four tokens of
      pure function word and embeds as nothing at all.
    """
    stripped = _SUBJECT_RE.sub(" ", query)
    # An orphaned possessive is left behind by "Mari Energies' head office"; leaving it
    # in measurably hurt, because " ' " embeds as a token of its own.
    stripped = re.sub(r"\s+(['\u2019])", "", stripped)
    stripped = re.sub(r"\s{2,}", " ", stripped).strip(" ,'\u2019")
    content = [w for w in re.findall(r"[^\W\d_]+", stripped.lower()) if w not in _FUNCTION_WORDS]
    return stripped if content else query

