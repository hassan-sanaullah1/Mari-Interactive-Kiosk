"""Query rewriting for the lexical (sparse/BM25) channel and the dense channel.

Urdu → English expansion: the corpus is English, so an Urdu query contributes almost
nothing to the sparse channel on its own. Each Urdu word is mapped to English search
terms through the tables in expansion_tables.py, spelled-out acronyms are joined back
together, and proper nouns are matched by sound against the corpus vocabulary. The dense
channel keeps the original text, where the embedding model's cross-lingual alignment
does better than a bag of keywords.
"""

from __future__ import annotations

import logging
import re

from .. import config as C
from .expansion_tables import (
    GLOSSARY,
    KB_STOPWORDS,
    PHRASES,
    UR_STOPWORDS,
    URDU_LETTER_NAMES,
    URDU_TO_LATIN,
)

log = logging.getLogger(__name__)

# Any character in the Urdu/Arabic block: a cheap "is expansion relevant" test.
_URDU_RE = re.compile(r"[؀-ۿ]")

_WORD_RE = re.compile(r"[a-z0-9]+")

# Urdu letters only. The wider block also holds "۔", "؟" and the Urdu digits, which would
# otherwise stick to a word and stop it matching a glossary key.
_UR_WORD_RE = re.compile(r"[\u0620-\u064a\u0670-\u06d3\u06fa-\u06ff]+")

# Expansion terms below this weight are broad topic guesses: useful beside real signal,
# harmful as the only content of a lexical query.
_MIN_WEIGHT = 0.5

# What the visitor said outweighs what was inferred from it.
_W_LITERAL = 1.0    # words the visitor typed, and acronyms they spelled out
_W_SOUND = 0.7      # a name matched by sound; can catch a common word inside a compound
_W_GLOSS = 0.5      # our own topic expansion: a hint, not evidence

# Sound matching. Exact on a consonant skeleton, never fuzzy: edit distance matched
# "آڈیٹر" to "dsra". A two-consonant key is trusted only if one corpus word has it.
_MIN_KEY = 2
_SHORT_KEY = 2
_MAX_CANDIDATES = 4


def _tokens(text: str) -> list[str]:
    return [w for w in _WORD_RE.findall(text.lower()) if len(w) > 2 and w not in KB_STOPWORDS]


def _read_corpus() -> str:
    path = C.KNOWLEDGE_FILE
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _acronyms(words: list[str]) -> list[str]:
    """Runs of two or more spelled-out letters, joined ("پی ایس ایکس" -> "psx")."""
    out, run = [], []
    for w in words + [""]:
        if letter := URDU_LETTER_NAMES.get(w):
            run.append(letter)
            continue
        if len(run) >= 2:
            out.append("".join(run))
        run = []
    return out


def _sound_key(word: str) -> str:
    """Spelling-independent skeleton: c/k/q folded, doubles collapsed, vowels dropped."""
    word = word.lower()
    for a, b in (("ck", "k"), ("ph", "f"), ("c", "k"), ("q", "k"), ("x", "ks")):
        word = word.replace(a, b)
    # Urdu writes v and w as و, plural -s as ز, and hears a soft g as ج.
    word = re.sub(r"g(?=[eiy])", "j", word)
    word = word.replace("v", "w").replace("z", "s")
    word = re.sub(r"(.)\1+", r"\1", word)
    word = re.sub(r"[aeiouwy]", "", word)
    word = re.sub(r"h$", "", word)          # silent final ہ: "آیلہ" is "ayla"
    return re.sub(r"(.)\1+", r"\1", word)


def _romanise(word: str) -> str:
    return "".join(URDU_TO_LATIN.get(ch, "") for ch in word)


def _sound_index(vocabulary: frozenset[str]) -> dict[str, list[str]]:
    idx: dict[str, list[str]] = {}
    # Sorted, so which names resolve does not vary between processes.
    for term in sorted(vocabulary):
        if term in KB_STOPWORDS:
            continue
        key = _sound_key(term)
        if len(key) >= _MIN_KEY:
            idx.setdefault(key, []).append(term)
    limit = {k: (1 if len(k) == _SHORT_KEY else _MAX_CANDIDATES) for k in idx}
    return {k: v for k, v in idx.items() if len(v) <= limit[k]}


_SOUNDS = _sound_index(frozenset(_tokens(_read_corpus())))


def _sounds_like(word: str) -> list[str]:
    """Corpus words that sound like this Urdu one, or [] if none clearly does."""
    key = _sound_key(_romanise(word))
    return _SOUNDS.get(key, []) if len(key) >= _MIN_KEY else []


def _expand_weighted(query: str) -> dict[str, float]:
    """Search terms mapped to how much trust each one has earned."""
    weights: dict[str, float] = {}

    def add(items, weight: float) -> None:
        for t in items:
            weights[t] = max(weights.get(t, 0.0), weight)

    add(_tokens(query), _W_LITERAL)
    rest = query
    for phrase, mapped in PHRASES.items():
        if phrase in rest:
            add(_tokens(mapped), _W_GLOSS)
            rest = rest.replace(phrase, " ")

    words = [w for w in _UR_WORD_RE.findall(rest) if w not in UR_STOPWORDS]
    add(_acronyms(words), _W_LITERAL)
    for word in words:
        if mapped := GLOSSARY.get(word):
            add(_tokens(mapped), _W_GLOSS)
        elif word not in URDU_LETTER_NAMES:
            add(_sounds_like(word), _W_SOUND)
    return weights


def _expand(query: str) -> list[str]:
    return list(_expand_weighted(query))


def has_urdu(text: str) -> bool:
    return bool(_URDU_RE.search(text or ""))


def expand_for_lexical(query: str) -> tuple[str, list[str]]:
    """Return (query text for the sparse channel, terms that were added).

    An all-English query passes through untouched, with an empty term list.
    """
    if not query or not has_urdu(query):
        return query, []
    try:
        weighted = _expand_weighted(query)
    except Exception:  # noqa: BLE001
        log.exception("Urdu query expansion failed; using the raw query for BM25")
        return query, []

    terms = sorted(
        (t for t, w in weighted.items() if w >= _MIN_WEIGHT and t.isascii()),
        key=lambda t: (-weighted[t], t),
    )
    if not terms:
        return query, []
    # The original text stays in front: a Latin token the visitor said ("Sky47", "PSX")
    # is the strongest lexical signal and must not be diluted.
    return f"{query} {' '.join(terms)}", terms


# ── corpus subject ──────────────────────────────────────────────────

# Words that cannot carry a topic on their own.
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
    """Remove the company's own name from a query, for the DENSE channel only.

    Every chunk is about Mari Energies, so its name says nothing about which chunk
    answers, but it drags the query vector toward the overview section. Measured on the
    342-question tester set: +6.1 points of hit@1. The sparse channel already discounts
    it through IDF. Urdu forms are not listed (measured: no effect), and a query that is
    only the subject is left alone, since the overview really is the answer then.
    """
    stripped = _SUBJECT_RE.sub(" ", query)
    # An orphaned possessive (" ' ") embeds as a token of its own and hurts.
    stripped = re.sub(r"\s+(['\u2019])", "", stripped)
    stripped = re.sub(r"\s{2,}", " ", stripped).strip(" ,'\u2019")
    content = [w for w in re.findall(r"[^\W\d_]+", stripped.lower()) if w not in _FUNCTION_WORDS]
    return stripped if content else query
