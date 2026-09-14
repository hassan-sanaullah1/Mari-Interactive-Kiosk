"""Unit tests for the retrieval layer that need no models, no Qdrant and no network.

Everything expensive (embedding, reranking, the vector store) is either injected or
stubbed. The retrieval stages worth testing here are the ones that encode a *decision* —
what gets corrected, what gets expanded, what gets gated away, what reaches the prompt —
and none of those need a real model to verify.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from server.services.expansion import (
    expand_for_lexical, has_urdu, strip_corpus_subject,
)
from server.services.generation import GenerationService
from server.services.metadata import MetadataService
from server.services.retriever import RetrievalResult, RetrievedChunk, Retriever
from server.services.rewriter import needs_rewrite
from server.services.settings import RagSettings
from server.services.store import Hit
from server.services.transcript import correct_transcript


# ── settings ────────────────────────────────────────────────────────

def test_e5_prefixes_are_resolved_from_the_model_name() -> None:
    """Asymmetric models need prefixes, and omitting them costs recall silently."""
    s = RagSettings(dense_model="intfloat/multilingual-e5-large")
    assert s.query_prefix == "query: "
    assert s.passage_prefix == "passage: "


def test_bge_v15_english_gets_a_query_prefix_only() -> None:
    s = RagSettings(dense_model="BAAI/bge-small-en-v1.5")
    assert s.query_prefix.startswith("Represent this sentence")
    assert s.passage_prefix == ""


def test_symmetric_models_get_no_prefix() -> None:
    s = RagSettings(dense_model="sentence-transformers/paraphrase-multilingual-mpnet-base-v2")
    assert s.query_prefix == "" and s.passage_prefix == ""


def test_explicit_prefix_is_not_overridden() -> None:
    s = RagSettings(dense_model="intfloat/multilingual-e5-large", query_prefix="custom: ")
    assert s.query_prefix == "custom: "


# ── transcript correction ───────────────────────────────────────────

@pytest.mark.parametrize("said,expected", [
    ("what happened at the har key field", "Daharki"),
    ("tell me about foji foundation", "Fauji"),
    ("who runs sky forty seven", "Sky47"),
    ("what is the p s x symbol", "PSX"),
    ("how many wells in waziri stan", "Waziristan"),
    ("the bitay six well", "Bhitai"),
])
def test_mishearings_are_repaired(said: str, expected: str) -> None:
    corrected, applied = correct_transcript(said)
    assert expected in corrected
    assert applied


def test_clean_text_is_left_alone() -> None:
    """A correction map that fires on correct input is worse than no map at all."""
    for clean in ("What is Mari Energies?", "Who is the CEO?", "Tell me about the company"):
        corrected, applied = correct_transcript(clean)
        assert corrected == clean, applied


def test_correction_is_idempotent() -> None:
    once, _ = correct_transcript("the har key gas field")
    twice, _ = correct_transcript(once)
    assert once == twice


# ── Urdu expansion ──────────────────────────────────────────────────

def test_english_queries_are_not_expanded() -> None:
    text, terms = expand_for_lexical("Who is the chief executive?")
    assert terms == [] and text == "Who is the chief executive?"


def test_urdu_expands_to_english_terms_for_the_lexical_channel() -> None:
    _, terms = expand_for_lexical("ریکروٹمنٹ کا کیا پروسیس ہے؟")
    assert "recruitment" in terms


def test_spelled_out_acronyms_are_rebuilt() -> None:
    """Urdu spells acronyms letter by letter; the corpus contains them joined."""
    _, terms = expand_for_lexical("پی ایس ایکس سمبل کیا ہے؟")
    assert "psx" in terms


def test_original_text_leads_the_expanded_query() -> None:
    """What the visitor said outranks what we inferred from it."""
    query = "سجاول بلاک کا کیا حال ہے؟"
    text, terms = expand_for_lexical(query)
    assert text.startswith(query)
    assert terms


def test_has_urdu() -> None:
    assert has_urdu("سی ای او کون ہے؟")
    assert not has_urdu("Who is the CEO?")


# ── query rewriting triggers ────────────────────────────────────────

def _settings() -> RagSettings:
    return RagSettings(rewrite_enabled=True, rewrite_min_content_words=4)


@pytest.mark.parametrize("text", [
    "what about their pricing?", "how much do they produce?", "and that one?",
    "اس کا کیا فائدہ؟", "tell me more",
])
def test_elliptical_followups_trigger_a_rewrite(text: str) -> None:
    assert needs_rewrite(text, has_history=True, settings=_settings())


@pytest.mark.parametrize("text", [
    "What is the recruitment process at Mari Energies?",
    "How many exploration blocks does the company hold?",
])
def test_self_contained_questions_do_not(text: str) -> None:
    """Rewriting is an LLM call inside the latency budget; it must stay rare."""
    assert not needs_rewrite(text, has_history=True, settings=_settings())


def test_first_turn_never_rewrites() -> None:
    """With no history there is nothing to resolve, so a rewrite can only invent context."""
    assert not needs_rewrite("what about them?", has_history=False, settings=_settings())


def test_disabling_rewrite_is_honoured() -> None:
    s = RagSettings(rewrite_enabled=False)
    assert not needs_rewrite("what about them?", has_history=True, settings=s)


# ── the relevance gate ──────────────────────────────────────────────

def _chunk(score: float) -> RetrievedChunk:
    return RetrievedChunk(text="t", source="s", heading_path="h",
                          score=score, fusion_score=score, reranked=True)


def _retriever(**kw) -> Retriever:
    # Constructing a Retriever does not touch Qdrant or any model — the store and the
    # embedding service are lazy — so the gate can be tested in isolation.
    return Retriever(settings=RagSettings(**kw))


def test_gate_passes_the_whole_top_k_when_the_best_chunk_clears_the_bar() -> None:
    r = _retriever(relative_score_floor=0.0)
    chunks = [_chunk(0.9), _chunk(0.4), _chunk(0.1)]
    assert len(r._gate(chunks, 0.02)) == 3


def test_gate_returns_nothing_when_nothing_is_relevant() -> None:
    """This is what lets the prompt's "say you don't know" branch fire."""
    r = _retriever()
    assert r._gate([_chunk(0.001), _chunk(0.0005)], 0.02) == []


def test_gate_uses_the_best_chunk_not_the_first() -> None:
    """Regression: RRF ranks by fused rank, so chunk 1 is often a sparse-channel winner
    with a mediocre dense score. Gating on it discarded entire correct retrievals."""
    r = _retriever(relative_score_floor=0.0)
    chunks = [_chunk(0.01), _chunk(0.95), _chunk(0.9)]
    assert len(r._gate(chunks, 0.5)) == 3


def test_relative_floor_drops_the_long_tail() -> None:
    r = _retriever(relative_score_floor=0.10)
    chunks = [_chunk(1.0), _chunk(0.5), _chunk(0.01)]
    assert len(r._gate(chunks, 0.02)) == 2


def test_gate_on_empty_input() -> None:
    assert _retriever()._gate([], 0.02) == []


# ── section expansion ───────────────────────────────────────────────

class _FakeStore:
    """Stands in for Qdrant. `fetch_section` is the only method expansion touches."""

    def __init__(self, sections: dict[str, list[str]]) -> None:
        self.sections = sections
        self.asked: list[str] = []

    async def fetch_section(self, section: str, limit: int = 32):
        self.asked.append(section)
        return [
            Hit(text=text, source="kb.md", heading_path=f"{section} > sub",
                chunk_index=i, score=0.0, payload={})
            for i, text in enumerate(self.sections.get(section, []))
        ]


def _ranked(section: str, text: str, score: float = 0.9) -> RetrievedChunk:
    return RetrievedChunk(text=text, source="kb.md", heading_path=f"{section} > sub",
                          score=score, fusion_score=score, reranked=True)


def _expander(store, **kw) -> Retriever:
    r = Retriever(store=store, settings=RagSettings(**kw))
    return r


def test_expansion_completes_the_section_that_ranked() -> None:
    """The failure this exists for: the right section is retrieved and the answer is
    still partial, because only one of its chunks reached the model."""
    store = _FakeStore({"6. Discoveries": ["first", "second", "third"]})
    r = _expander(store)
    chunks, added = asyncio.run(r._expand_section([_ranked("6. Discoveries", "first")]))
    assert added == 2
    assert [c.text for c in chunks] == ["first", "second", "third"]
    assert all(c.expanded for c in chunks[1:])
    assert not chunks[0].expanded


def test_expansion_does_not_reorder_the_ranked_chunks() -> None:
    """Appending only. This is why expansion cannot cost hit@k, and the guarantee the
    measured "ranking metrics unchanged" result rests on."""
    store = _FakeStore({"A": ["a1", "a2"], "B": ["b1"]})
    r = _expander(store)
    ranked = [_ranked("A", "a1", 0.9), _ranked("B", "b1", 0.5)]
    chunks, _ = asyncio.run(r._expand_section(ranked))
    assert chunks[:2] == ranked


def test_only_the_rank_one_section_is_completed() -> None:
    """Regression, and the expensive kind — this asserted the OPPOSITE first.

    Completing every retrieved section raises section recall and lowers context
    precision, because the company-overview section is weakly relevant to everything and
    so gets completed constantly. Measured, it appends ~1,400 off-topic chunks against
    ~160 useful ones across the tester set. See `Retriever._sections_to_complete`.
    """
    store = _FakeStore({"2. History": ["h1", "h2"], "17. Recent": ["r1", "r2"]})
    r = _expander(store)
    chunks, _ = asyncio.run(
        r._expand_section([_ranked("2. History", "h1"), _ranked("17. Recent", "r1")])
    )
    assert store.asked == ["2. History"]
    assert {c.text for c in chunks} == {"h1", "h2", "r1"}


def test_expansion_respects_its_char_budget() -> None:
    store = _FakeStore({"A": ["x" * 400, "y" * 400, "z" * 400]})
    r = _expander(store, section_expansion_chars=500)
    _, added = asyncio.run(r._expand_section([_ranked("A", "seed")]))
    assert added == 1


def test_expansion_skips_an_oversized_chunk_rather_than_stopping() -> None:
    """Sections are in document order, not size order, so one long chunk in the middle
    must not hide the short ones behind it."""
    store = _FakeStore({"A": ["x" * 5000, "short"]})
    r = _expander(store, section_expansion_chars=1000)
    chunks, added = asyncio.run(r._expand_section([_ranked("A", "seed")]))
    assert added == 1
    assert chunks[-1].text == "short"


def test_expansion_does_not_duplicate_an_already_retrieved_chunk() -> None:
    store = _FakeStore({"A": ["seed", "other"]})
    r = _expander(store)
    chunks, added = asyncio.run(r._expand_section([_ranked("A", "seed")]))
    assert added == 1
    assert [c.text for c in chunks] == ["seed", "other"]


def test_expansion_can_be_turned_off() -> None:
    store = _FakeStore({"A": ["a1", "a2"]})
    r = _expander(store, section_expansion=False)
    chunks, added = asyncio.run(r._expand_section([_ranked("A", "a1")]))
    assert added == 0 and len(chunks) == 1


def test_a_store_failure_leaves_the_ranked_chunks_untouched() -> None:
    """Completeness is an improvement, not a promise — it must never fail a turn."""
    class _Broken(_FakeStore):
        async def fetch_section(self, section: str, limit: int = 32):
            raise RuntimeError("qdrant is down")

    r = _expander(_Broken({}))
    ranked = [_ranked("A", "a1")]
    chunks, added = asyncio.run(r._expand_section(ranked))
    assert added == 0 and chunks == ranked


# ── context assembly ────────────────────────────────────────────────

def test_assembly_dedupes_and_caps_length() -> None:
    r = _retriever(max_context_chars=100)
    chunks = [
        RetrievedChunk("A" * 60, "a.md", "h1", 1.0, 1.0, True),
        RetrievedChunk("A" * 60, "a.md", "h1", 0.9, 0.9, True),   # duplicate
        RetrievedChunk("B" * 60, "b.md", "h2", 0.8, 0.8, True),
        RetrievedChunk("C" * 60, "c.md", "h3", 0.7, 0.7, True),   # over the cap
    ]
    context, sources = r._assemble(chunks)
    assert context.count("A" * 60) == 1
    assert len(context) <= 100 + 2
    assert sources == ["a.md"]


# ── prompt assembly ─────────────────────────────────────────────────

def test_system_prompt_is_injected_even_with_no_context() -> None:
    """Persona must not collapse on an empty or failed index."""
    g = GenerationService()
    prompt = g.build_prompt(RetrievalResult(), lang="en", core_brief="CORE FACTS HERE")
    assert prompt.grounded is False
    assert "MARI" in prompt.system
    assert "CORE FACTS HERE" in prompt.system
    # and it must be told not to answer from its own memory
    assert "do not answer" in prompt.system.lower() or "not have that information" in prompt.system.lower()


def test_context_and_glossary_reach_the_prompt_in_order() -> None:
    """Glossary before sections, so truncation never cuts the authoritative definitions."""
    g = GenerationService()
    result = RetrievalResult(context="SECTION BODY", sources=["kb.md"],
                             glossary_block="GLOSSARY: MSPC = Mari Seismic Processing Center")
    prompt = g.build_prompt(result, lang="en")
    assert prompt.grounded is True
    assert prompt.sources == ["kb.md"]
    assert prompt.system.index("GLOSSARY:") < prompt.system.index("SECTION BODY")


def test_urdu_prompt_is_used_for_urdu() -> None:
    g = GenerationService()
    en = g.build_prompt(RetrievalResult(), lang="en").system
    ur = g.build_prompt(RetrievalResult(), lang="ur").system
    assert en != ur


def test_unknown_language_falls_back_to_english() -> None:
    g = GenerationService()
    assert g.build_prompt(RetrievalResult(), lang="fr").system == \
           g.build_prompt(RetrievalResult(), lang="en").system


# ── metadata DB ─────────────────────────────────────────────────────

def test_hash_check_skips_unchanged_and_retries_failed(tmp_path: Path) -> None:
    db = MetadataService(tmp_path / "m.sqlite")
    db.mark_ready("kb.md", "hash1", "md", 100, chunk_count=42)
    assert db.is_unchanged("kb.md", "hash1")
    assert not db.is_unchanged("kb.md", "hash2"), "edited file must re-ingest"

    # A file that failed has a stored hash; a hash-only check would skip it forever.
    db.mark_failed("bad.md", "hash3", "md", 10, "boom")
    assert not db.is_unchanged("bad.md", "hash3")
    assert db.summary()["failed"] == 1


def test_metadata_summary_counts(tmp_path: Path) -> None:
    db = MetadataService(tmp_path / "m.sqlite")
    db.mark_ready("a.md", "h", "md", 1, chunk_count=3)
    db.mark_ready("b.md", "h", "md", 1, chunk_count=4)
    summary = db.summary()
    assert summary["documents"] == 2 and summary["chunks"] == 7 and summary["ready"] == 2
    db.delete("a.md")
    assert db.summary()["documents"] == 1


# ── corpus-subject stripping (dense channel only) ───────────────────

@pytest.mark.parametrize("query,expected", [
    ("What discoveries has Mari Energies made recently?", "What discoveries has made recently?"),
    ("Who is Mari Energies' CEO?", "Who is CEO?"),
    ("What was MariEnergies' FY2024-25 net profit?", "What was FY2024-25 net profit?"),
    ("MPCL history", "history"),
    ("What is Mari Petroleum Company Limited's tagline?", "What is tagline?"),
])
def test_the_corpus_subject_is_removed(query: str, expected: str) -> None:
    """Every chunk is about this company, so its name cannot pick between them — and a
    dense embedding, unlike BM25, has no document frequency to discount it with."""
    assert strip_corpus_subject(query) == expected


def test_an_orphaned_possessive_does_not_survive() -> None:
    """" ' " left dangling embeds as a token of its own and measurably hurt."""
    assert "'" not in strip_corpus_subject("Where is Mari Energies' head office located?")


@pytest.mark.parametrize("query", [
    "Mari Energies?",
    "tell me about MariEnergies",
    "What is Mari Energies?",
])
def test_a_query_that_is_only_the_subject_is_left_alone(query: str) -> None:
    """Nothing retrievable survives the strip, and the overview section really is the
    right answer. The check counts content words, not tokens: "tell me about" is four
    tokens of pure function word."""
    assert strip_corpus_subject(query) == query


def test_urdu_queries_are_untouched() -> None:
    """Measured identical either way — the cross-lingual embedding does not align the
    Urdu form onto the English name strongly enough for it to dominate."""
    q = "ماری انرجیز کا سی ای او کون ہے؟"
    assert strip_corpus_subject(q) == q


def test_stripping_leaves_other_company_names_alone() -> None:
    """OGDCL and Fauji Foundation are genuinely discriminating here."""
    q = "What stake does OGDCL hold in Mari Energies?"
    assert "OGDCL" in strip_corpus_subject(q)
