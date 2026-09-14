"""The Urdu → English expansion layer that feeds the retriever's sparse channel.

This file used to assert end-to-end retrieval: it called the in-process BM25 index and
checked which section came back. That index is gone — retrieval is hybrid search in
Qdrant now — and ranking quality is measured where it can be measured properly, by
``eval/run_eval.py`` against ``eval/questions.yaml`` (150 questions, 87 of them Urdu).
A unit test cannot meaningfully assert "the right chunk ranked first" without standing
up a vector database, and pretending otherwise is how the old suite stayed green while
real questions retrieved nothing.

What is still worth testing here is the part that is pure, fast, and genuinely fragile:
the expansion tables themselves. An Urdu query contributes almost nothing to a lexical
search over an English corpus, so if expansion silently returns no terms, the sparse
half of the hybrid search goes dark and the failure shows up only as slightly worse
answers. These tests guard that specific silence.

Run: python -m pytest tests/ -q
"""

from __future__ import annotations

import pytest

from server.services import expansion
from server.services import expansion as K
from tests.retrieval_cases import CASES


@pytest.mark.parametrize("query", [q for q, _ in CASES], ids=lambda q: q[:40])
def test_every_urdu_question_produces_search_terms(query: str) -> None:
    """No visitor question expands to nothing.

    Which section it then retrieves is the eval harness's job; that it reaches the
    sparse channel carrying *some* English signal is this one's.
    """
    terms = [t for t in K._expand(query) if t.isascii()]
    assert terms, f"{query!r} expanded to no English terms; sparse search would see nothing"


def test_expansion_is_wired_into_the_sparse_channel() -> None:
    """The retriever must actually use the layer above, not just contain it."""
    text, terms = expansion.expand_for_lexical("سی ای او کون ہے؟")
    assert terms, "expansion produced no terms for a question it has a phrase entry for"
    assert "ceo" in terms
    # The visitor's own words stay in front; inferred keywords are appended, never
    # substituted. See server/services/expansion.py for why.
    assert text.startswith("سی ای او کون ہے؟")


def test_english_queries_pass_through_untouched() -> None:
    """Expansion has nothing to add to English, and must not dilute it."""
    text, terms = expansion.expand_for_lexical("who is the CEO")
    assert (text, terms) == ("who is the CEO", [])


def test_no_multiword_glossary_keys() -> None:
    """GLOSSARY is matched word by word, so a spaced key would never fire."""
    assert not [k for k in K.GLOSSARY if " " in k]


def test_bare_question_words_do_not_false_match() -> None:
    """A contentless question expands to nothing rather than dragging in section 1."""
    assert K._expand("یہ کیا ہے؟") == []


def test_urdu_sentence_punctuation_does_not_block_lookup() -> None:
    """۔ and ؟ must not be glued onto the word being looked up."""
    assert K._expand("ریکروٹمنٹ؟") == K._expand("ریکروٹمنٹ")


def test_spelled_out_acronyms_are_rebuilt() -> None:
    """Urdu spells acronyms letter by letter; the KB contains them joined."""
    assert "psx" in K._expand("پی ایس ایکس")
    assert "eps" in K._expand("ای پی ایس")


@pytest.mark.parametrize(
    "urdu,expected",
    [("مجید", "majid"), ("بھٹائی", "bhitai"), ("کارپلنک", "corplink"),
     ("نبیل", "nabeel"), ("رجسٹرار", "registrar"), ("ڈہرکی", "daharki"),
     ("فوجی", "fauji"), ("غنی", "ghani")],
)
def test_names_are_matched_by_sound(urdu: str, expected: str) -> None:
    """Proper nouns are unbounded, so they are matched phonetically, not from a list.

    The index behind this is built from the corpus vocabulary at import.
    """
    assert expected in K._sounds_like(urdu)


def test_sound_matching_stays_exact() -> None:
    """No fuzzy tolerance: an earlier edit-distance version matched درخت to 'direct'."""
    assert "direct" not in K._sounds_like("درخت")
    assert "dsra" not in K._sounds_like("آڈیٹر")


def test_typed_words_outrank_inferred_topics() -> None:
    """A glossary expansion must not outvote the specific term it came with."""
    weights = K._expand_weighted("ڈہرکی فیلڈ")
    assert weights["daharki"] > weights["development"]
