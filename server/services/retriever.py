"""The one retrieval path, shared by the HTTP API and the voice agent.

This module exists as much for what it prevents as for what it does. The system it
replaces had retrieval implemented twice — once in the web service and once in the voice
agent — and the two copies drifted: different top_k, one of them missing the glossary
injection, and a fix applied to one of them for months before anyone noticed the other
still had the bug. Anything that needs retrieval calls `Retriever.retrieve`. The voice
path may pass a smaller `top_k` and a tighter deadline; it does not get its own logic.

The pipeline, in order, with the reason each stage is where it is:

  1. transcript correction   Fix domain terms before anything reads the query. A wrong
                             content word poisons every later stage identically.
  2. query rewrite           Conditional and timeout-guarded (see rewriter.py). Only
                             elliptical follow-ups pay for it.
  3. embed (dense + sparse)  Usually already done — see `prestart`. The dense side
                             drops the corpus's own subject first; the sparse side does
                             not (IDF already handles it there).
  4. hybrid search + RRF     One Qdrant round trip, fused server-side.
  5. rerank                  Cross-encoder over the fused candidates.
  6. threshold               Drop everything below calibrated relevance. This is the
                             stage that lets the kiosk say "I don't know".
  7. section expansion       Complete the section the top chunk came from. Answers a
                             question top-k cannot: "what else is in here?"
  8. glossary injection      Deterministic override for abbreviations, regardless of
                             what retrieval returned.
  9. context assembly        Joined, deduped, length-capped.

Every stage is timed and every stage is optional in the sense that its failure degrades
the result rather than failing the turn. A visitor who gets an ungrounded-but-polite
answer has had a worse experience; a visitor who gets a 500 has had no experience.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import re
import time
from dataclasses import dataclass, field

import numpy as np

from .embedding import EmbeddingService, get_embedding_service
from .rewriter import QueryRewriter
from .settings import RagSettings, get_settings
from .expansion import expand_for_lexical, has_urdu, strip_corpus_subject
from .store import Hit, QdrantStore
from .transcript import correct_transcript

log = logging.getLogger(__name__)

try:
    from voice_config import extract_glossary, find_glossary_matches, format_glossary_block
except ImportError:  # pragma: no cover
    def extract_glossary(text: str) -> dict[str, str]:
        return {}

    def find_glossary_matches(query: str, glossary: dict[str, str]) -> dict[str, str]:
        return {}

    def format_glossary_block(matches: dict[str, str]) -> str:
        return ""


@dataclass
class RetrievedChunk:
    text: str
    source: str
    heading_path: str
    score: float           # rerank probability when reranked, else the RRF score
    fusion_score: float    # always the RRF score, kept for tuning
    reranked: bool
    # True when this chunk was not retrieved on its own merits but pulled in to complete
    # the section a ranked chunk came from (see `_expand_section`). Its score is 0 and
    # must not be compared against a ranked chunk's; this flag is what stops a reader —
    # or a future gate — from doing that by accident.
    expanded: bool = False


@dataclass
class RetrievalResult:
    chunks: list[RetrievedChunk] = field(default_factory=list)
    context: str = ""
    sources: list[str] = field(default_factory=list)
    glossary_block: str = ""
    query: str = ""              # what was actually searched
    original_query: str = ""     # what the visitor said
    rewritten: bool = False
    corrections: list[tuple[str, str]] = field(default_factory=list)
    timings_ms: dict[str, float] = field(default_factory=dict)
    degraded: str = ""           # non-empty when a fallback was used; names the reason
    cached: bool = False
    embedding_prestarted: bool = False
    expansion_terms: list[str] = field(default_factory=list)
    section_expanded: int = 0    # chunks appended to complete the winning section

    @property
    def total_ms(self) -> float:
        return sum(self.timings_ms.values())


class _Timer:
    """Records per-stage wall clock into a dict. The breakdown is the tuning signal —
    a single total tells you the budget was blown, not which stage to look at."""

    def __init__(self, into: dict[str, float]) -> None:
        self._into = into

    @contextlib.contextmanager
    def __call__(self, stage: str):
        t0 = time.perf_counter()
        try:
            yield
        finally:
            self._into[stage] = self._into.get(stage, 0.0) + (time.perf_counter() - t0) * 1000


class Retriever:
    def __init__(
        self,
        store: QdrantStore | None = None,
        embedding: EmbeddingService | None = None,
        settings: RagSettings | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.store = store or QdrantStore(self.settings)
        self.embedding = embedding or get_embedding_service(self.settings)
        self.rewriter = QueryRewriter(self.settings)

        self.glossary: dict[str, str] = {}
        self._ready = False
        # Pre-started embedding tasks, keyed by the text they were started for.
        self._prestarted: dict[str, asyncio.Task] = {}
        self._result_cache: dict[str, tuple[float, RetrievalResult]] = {}

    # ── lifecycle ───────────────────────────────────────────────────

    async def warmup(self) -> None:
        """Load models, ensure the collection, and mine the glossary. Idempotent."""
        t0 = time.perf_counter()
        # The models and Qdrant are independent; loading them concurrently roughly halves
        # cold start, and cold start is the window in which the kiosk is visibly dead.
        results = await asyncio.gather(
            self.embedding.warmup_async(),
            self._ensure_store(),
            return_exceptions=True,
        )
        for r in results:
            if isinstance(r, Exception):
                log.warning("warmup step failed: %s: %s", type(r).__name__, r)
        await self.refresh_glossary()
        self._ready = True
        log.info("retriever warmup finished in %.1fs", time.perf_counter() - t0)

    async def _ensure_store(self) -> None:
        await self.store.ensure_collection()

    async def refresh_glossary(self) -> None:
        """Scan the whole corpus once for "ABBR (Full Form)" pairs and cache the map.

        This is a one-off full scan, not a per-turn cost, and it buys a deterministic
        guarantee that top-k retrieval cannot give. A corpus can *use* an abbreviation
        fifty times and *define* it once. Semantic search returns the chunks that use it
        — they are all about the same topic and all score well — and the single chunk
        that defines it ranks nowhere. The model then confidently invents an expansion.
        Force-injecting the definition is a deterministic guardrail over a probabilistic
        retriever, and it is the reason this survives every refactor.
        """
        try:
            texts = [p.get("text", "") async for p in self.store.scroll_all()]
            self.glossary = extract_glossary("\n".join(texts))
            log.info("glossary: %d abbreviations from %d chunks", len(self.glossary), len(texts))
        except Exception:  # noqa: BLE001
            log.exception("glossary scan failed; abbreviation injection disabled this run")
            self.glossary = {}

    async def close(self) -> None:
        for task in self._prestarted.values():
            task.cancel()
        self._prestarted.clear()
        await self.store.close()

    # ── pre-started embedding ───────────────────────────────────────

    def prestart(self, text: str) -> None:
        """Begin embedding `text` now, before the turn handler asks for it.

        Called the moment STT produces a transcript. By the time end-of-speech is
        detected, endpointing has settled and the turn handler runs, the embedding is
        usually already finished — so its 15-40 ms disappears entirely rather than being
        added to the visitor's wait. This is the single cheapest latency win available
        on the voice path, because it removes a stage from the critical path instead of
        making it faster.

        Safe to call repeatedly with interim transcripts: each distinct string gets one
        task, and unclaimed tasks are reaped below.
        """
        corrected, _ = correct_transcript(text or "")
        key = self._cache_key(corrected)
        if not key or key in self._prestarted:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return  # not on a loop (sync caller) — nothing to pre-start against
        self._prestarted[key] = loop.create_task(self._embed_both(corrected))
        self._reap_prestarted()

    def _reap_prestarted(self, keep: int = 8) -> None:
        """Interim transcripts pile up — one per STT partial. Only the last few can still
        be claimed, and an un-awaited task holding a vector is a slow leak."""
        while len(self._prestarted) > keep:
            oldest = next(iter(self._prestarted))
            self._prestarted.pop(oldest).cancel()

    async def _embed_both(self, text: str) -> tuple[np.ndarray, object, list[str]]:
        # The two channels get DIFFERENT text, which is the whole point of running both.
        #
        # Dense gets the query as spoken: multilingual-e5 aligns Urdu to English better
        # than a bag of translated keywords does, and prepending keywords measurably
        # blunts it.
        #
        # Sparse gets the Urdu-expanded form. BM25 is purely lexical, so an Urdu query
        # against an English corpus contributes almost nothing to it — the expansion is
        # what makes the lexical channel exist at all for half the kiosk's traffic. See
        # expansion.py for how much this is worth (fifteen points of hit@5).
        lexical, _terms = (
            expand_for_lexical(text) if self.settings.expand_urdu_lexical else (text, [])
        )
        # Dense also gets the company's own name removed. The name is in every chunk, so
        # it cannot discriminate between them — but unlike BM25, a dense embedding has no
        # document frequency to discount it with, so naming the company pulls the query
        # toward the generic company-overview region and section 1 wins on almost any
        # question. Worth 6 points of hit@1; see strip_corpus_subject for the numbers and
        # for why the sparse channel is deliberately left alone.
        focused = (
            strip_corpus_subject(text) if self.settings.strip_subject_for_dense else text
        )
        # Separate models on separate threads: concurrently, the pair costs about as
        # much as the slower one alone.
        dense, sparse = await asyncio.gather(
            self.embedding.embed_query_async(focused),
            self.embedding.embed_sparse_query_async(lexical),
        )
        return dense, sparse, _terms

    async def _get_vectors(self, text: str) -> tuple[np.ndarray, object, list[str], bool]:
        """The query's vectors, claiming a pre-started task when one matches."""
        key = self._cache_key(text)
        if task := self._prestarted.pop(key, None):
            try:
                dense, sparse, terms = await task
                return dense, sparse, terms, True
            except Exception:  # noqa: BLE001 - a failed pre-start just means embed now
                log.debug("pre-started embedding failed; embedding inline")
        dense, sparse, terms = await self._embed_both(text)
        return dense, sparse, terms, False

    # ── retrieval ───────────────────────────────────────────────────

    @staticmethod
    def _cache_key(text: str) -> str:
        return re.sub(r"\s+", " ", (text or "").strip().lower())

    async def retrieve(
        self,
        text: str,
        *,
        lang: str = "en",
        top_k: int | None = None,
        history: list[dict] | None = None,
        llm_base: str = "",
        llm_key: str = "",
        llm_model: str = "",
        use_cache: bool = True,
    ) -> RetrievalResult:
        """Retrieve context for one turn. Never raises."""
        s = self.settings
        top_k = top_k or s.top_k
        timings: dict[str, float] = {}
        timer = _Timer(timings)
        result = RetrievalResult(original_query=text, timings_ms=timings)

        with timer("correct"):
            query, corrections = correct_transcript(text or "")
        result.corrections = corrections

        if s.rewrite_enabled and llm_base:
            with timer("rewrite"):
                query, rewritten, _ = await self.rewriter.rewrite(
                    query, history, api_base=llm_base, api_key=llm_key, model=llm_model
                )
            result.rewritten = rewritten
        result.query = query

        if use_cache and (cached := self._cache_get(query, top_k)):
            cached.timings_ms = timings
            cached.cached = True
            cached.original_query = text
            return cached

        try:
            with timer("embed"):
                dense, sparse, expanded, prestarted = await self._get_vectors(query)
            result.expansion_terms = expanded
            # Recorded as a flag, not a timing: when the embedding was pre-started its
            # measured cost here is near zero, and a reader comparing stage timings
            # across turns needs to know *why* rather than seeing it flicker.
            result.embedding_prestarted = prestarted

            with timer("search"):
                hits = await self.store.hybrid_search(
                    dense, sparse,
                    limit=s.rerank_candidates if s.rerank_enabled else top_k * 2,
                    prefetch_limit=s.prefetch_limit,
                )

            with timer("rerank"):
                chunks = await self._rerank_and_gate(query, hits, top_k)

            with timer("expand"):
                chunks, added = await self._expand_section(chunks)
            result.section_expanded = added
        except Exception as exc:  # noqa: BLE001
            # Retrieval failure is never fatal. The system prompt still goes in, the
            # persona still holds, the core brief is still there, and the visitor gets an
            # honest "I don't have that" instead of an error. exc_info because this is
            # the log line that explains a day of "why does the kiosk not know anything".
            #
            # There is deliberately no second retriever to fall back to. A shadow BM25
            # index used to sit here, and it was worse than nothing: it answered from a
            # separately-chunked copy of the corpus that no eval run ever scored, so a
            # broken Qdrant produced quietly degraded answers instead of a visible
            # failure. Empty context is the honest signal, and /healthz reports why.
            log.warning("retrieval failed (%s); serving with no context",
                        type(exc).__name__, exc_info=True)
            result.degraded = f"{type(exc).__name__}: {exc}"
            chunks = []

        result.chunks = chunks
        with timer("assemble"):
            result.glossary_block = self._glossary_block(query) if s.glossary_injection else ""
            result.context, result.sources = self._assemble(chunks)

        if use_cache and not result.degraded:
            self._cache_put(query, top_k, result)
        if s.log_stage_timings:
            log.debug(
                "retrieve %r -> %d chunks in %.0f ms %s",
                query, len(chunks), result.total_ms,
                {k: round(v, 1) for k, v in timings.items()},
            )
        return result

    @staticmethod
    def _order(hits: list[Hit]) -> list[Hit]:
        """Impose a total, deterministic order on the fused hits.

        RRF fuses *ranks*, so its scores are sums of 1/(k+rank) drawn from a small set,
        and ties are not an edge case — they are the common case. Measured on the
        150-question eval: 47 questions had at least one tied pair inside the top 5, and
        Qdrant returns tied results in whatever order it happened to scan them, which is
        not stable across processes. So the kiosk could answer the same question with a
        different chunk after a restart, and the eval swung 70.9% - 72.4% hit@1 on
        identical code — a band wider than most of the parameter changes this harness
        exists to detect, which made every small A/B comparison partly a coin flip.

        The tie-break is document order, and it is deliberately content-neutral: it is
        there to make the system reproducible, NOT to rank better. The obvious-looking
        alternative is to prefer the higher dense similarity, and it was measured rather
        than assumed — across the 33 tied groups that contain the answering chunk, the
        higher-dense chunk is the right one 17 times and the lower-dense chunk 16 times.
        That is a coin flip: dense cosine carries no information about which of two
        rank-equivalent chunks is better, and adopting it would only have fixed the
        assignment of ~33 near-random choices.

        This matters because those choices are worth several points of hit@1 on this
        question set, so a tie-break can be *selected* for a score it did not earn.
        Ordering by ascending dense similarity scores 74.6% here versus 70.9% for
        descending — 5 questions, entirely from the coin flips above. If you change this
        rule and hit@1 moves by a few points, that is what you are looking at, not a
        retrieval improvement.
        """
        return sorted(hits, key=lambda h: (-h.score, h.source, h.chunk_index))

    async def _rerank_and_gate(self, query: str, hits: list[Hit], top_k: int) -> list[RetrievedChunk]:
        s = self.settings
        if not hits:
            return []
        hits = self._order(hits)

        # An English-only cross-encoder scoring an Urdu query against English chunks
        # produces near-noise, and noise applied after a good ranking can only degrade
        # it. On the Urdu path the curated expansion (expansion.py) has already done the
        # work, so RRF's ordering is kept as-is.
        skip = s.rerank_skip_for_urdu and has_urdu(query)

        if not s.rerank_enabled or skip:
            # Gate on dense cosine similarity, NOT on the RRF score. Calibrating against
            # the eval set showed RRF scores give no separation whatsoever between
            # answerable and unanswerable questions — unsurprising in hindsight, since
            # RRF is purely rank-based and something is always rank 1 no matter how
            # irrelevant the whole candidate set is. Cosine similarity is an absolute
            # measure and does separate them. Ordering still comes from RRF, which is
            # the better ranker; only the gate uses similarity.
            chunks = [
                RetrievedChunk(h.text, h.source, h.heading_path, h.dense_similarity,
                               h.score, False)
                for h in hits[:top_k]
            ]
            return self._gate(chunks, s.dense_score_threshold)

        logits = await self.embedding.rerank_async(query, [h.text for h in hits])
        scored = sorted(
            zip(hits, (self.embedding.to_probability(x) for x in logits)),
            key=lambda pair: pair[1],
            reverse=True,
        )
        chunks = [
            RetrievedChunk(h.text, h.source, h.heading_path, prob, h.score, True)
            for h, prob in scored[:top_k]
        ]
        return self._gate(chunks, s.score_threshold)

    def _sections_to_complete(self, chunks: list[RetrievedChunk]) -> list[str]:
        """Which sections to complete: the one that owns rank 1, and only that one.

        This is deliberately the simplest possible rule, and it is the simplest rule
        because two more elaborate ones were built, measured and thrown away. Recording
        them, because the reasoning that produced them is seductive and wrong.

        The first was "walk the retrieved sections in rank order and complete as many as
        the budget allows". The second was "order them by how many chunks each
        contributed, since that is better evidence of the topic than owning one good
        chunk". Both are defensible, both raise section RECALL, and both make the kiosk
        worse — because recall was the only thing being measured.

        Scored per chunk over the 342-question tester set, completing every retrieved
        section appends 163 chunks from the answering section and 1,398 from somewhere
        else. Section 1, the company overview, supplies 545 of those and 393 KB of
        prompt on its own: a twelve-chunk overview of everything is weakly relevant to
        every question and decisively relevant to almost none, so it is retrieved
        constantly and completed constantly. The result is a context whose share of
        on-topic text falls from 31.4% to 23.2% while its recall rises — and a model
        that answers "what are your production figures?" from the quick-reference
        summary, because the summary is in front of it three times.

        Completing only the rank-1 section scores BEST on both halves at once:

            rule                       section recall   context precision
            rank-1 section only              91.0%            27.7%
            rank-1 + corroborated others     91.5%            25.8%
            by chunk count, top 2            90.3%            23.2%
            by rank order, top 2             92.0%            23.2%

        The near-miss case that motivated walking further down is real — "what
        discoveries has Mari Energies made recently?" ranks the history section first —
        but it is answered by the ranked chunks themselves, not by expanding into
        another section, so paying for it everywhere buys nothing.
        """
        top = chunks[0].heading_path.split(" > ")[0].strip()
        return [top] if top else []

    def _gate(self, chunks: list[RetrievedChunk], threshold: float) -> list[RetrievedChunk]:
        """Apply the relevance threshold to the RESULT, not to each chunk individually.

        This distinction cost 23 points of hit@5 when it was got wrong, so it is worth
        being precise about what the gate is for. Its job is to answer one question:
        does this corpus contain anything relevant to what was asked? That is a property
        of the best match, not of each match — so the threshold is applied to the top
        chunk, and if the top chunk clears it the whole top-k goes through.

        Filtering every chunk against the same bar looks equivalent and is not. Chunks
        ranked 2-5 legitimately score lower than the best one; they are supporting
        context, and a topic here routinely spans two or three chunks (which is why
        top_k was raised in the first place). Cutting them left the LLM with a single
        chunk on most turns and made hit@3 and hit@5 collapse to hit@1.

        The relative floor below still drops the long tail — a chunk scoring a tenth of
        the top one is not supporting the same answer — without gutting the context.
        """
        if not chunks:
            return []
        # The bar is cleared by the BEST chunk, not by the top-ranked one. Those differ,
        # and assuming they did not was a real bug: RRF ranks by fused rank, so the
        # rank-1 chunk is frequently a sparse/lexical winner whose dense similarity is
        # mediocre. Gating on that chunk's score discarded entire correct retrievals —
        # an Urdu question about "آیلہ مجید" whose top three hits were all the right
        # board-members section returned nothing at all, because the one that happened
        # to rank first scored 0.743 against a 0.75 floor.
        if max(c.score for c in chunks) < threshold:
            # Nothing is relevant. Return nothing and let the system prompt's
            # "say you don't know" branch fire: an honest "I don't have that
            # information" is a better kiosk experience than a fluent wrong answer.
            return []
        floor = max(c.score for c in chunks) * self.settings.relative_score_floor
        return [c for c in chunks if c.score >= floor]

    async def _expand_section(
        self, chunks: list[RetrievedChunk]
    ) -> tuple[list[RetrievedChunk], int]:
        """Complete the sections that ranked, by appending their unretrieved chunks.

        Retrieval answers "which chunks match?", and for a corpus of leaf facts that is
        the same question as "what answers this?". For a numbered outline it is not. Ten
        of this corpus's eighteen sections are enumerations — eleven discoveries, five
        field developments, seventeen sustainability milestones — and a visitor asking
        "what discoveries have you made?" is asking for the enumeration, not for its two
        best-matching entries. Top-k cannot express that: every chunk of section 6 is
        equally on-topic, so which two arrive is decided by wording noise, and the kiosk
        names two discoveries out of ten with complete confidence.

        So: once gating has decided a section is the right one, the rest of that section
        is not a fresh retrieval decision that has to compete on score. It is already
        known to be relevant, and it is appended without one — which is why these chunks
        carry `expanded=True` and score 0 rather than a fabricated score that would let
        them be ranked against chunks that earned theirs.

        Which section gets completed, and why it is only one of them, is in
        `_sections_to_complete` — that choice was the difference between this stage
        helping and hurting.

        Ordering is: ranked chunks first, in rank order, then the appended ones in
        document order. The rank-1 chunk stays first because it is the one the model
        weights most heavily and the one least likely to be truncated away; the appendix
        reads as that section's remaining bullets, which is what it is.
        """
        s = self.settings
        if not s.section_expansion or not chunks:
            return chunks, 0

        sections = self._sections_to_complete(chunks)
        if not sections:
            return chunks, 0

        # Match on the leading text, not on equality: overlap means a retrieved chunk
        # and its stored twin are the same chunk, while two DIFFERENT chunks of one
        # section share only their heading path prefix.
        seen = {c.text[:200] for c in chunks}
        budget = s.section_expansion_chars
        added: list[RetrievedChunk] = []

        for name in sections[: s.section_expansion_sections]:
            if len(added) >= s.section_expansion_max_chunks or budget <= 0:
                break
            try:
                siblings = await self.store.fetch_section(name)
            except Exception:  # noqa: BLE001 - completeness is an improvement, not a promise
                log.debug("section expansion failed for %r", name, exc_info=True)
                continue
            for hit in siblings:
                if len(added) >= s.section_expansion_max_chunks or budget <= 0:
                    break
                if not hit.text or hit.text[:200] in seen:
                    continue
                if len(hit.text) > budget:
                    # Skip rather than stop: sections are ordered by document position,
                    # not by size, so one long chunk in the middle must not hide the
                    # short ones after it.
                    continue
                seen.add(hit.text[:200])
                budget -= len(hit.text)
                added.append(
                    RetrievedChunk(hit.text, hit.source, hit.heading_path, 0.0, 0.0,
                                   False, expanded=True)
                )
        return chunks + added, len(added)

    # ── context assembly ────────────────────────────────────────────

    def _glossary_block(self, query: str) -> str:
        return format_glossary_block(find_glossary_matches(query, self.glossary))

    def _assemble(self, chunks: list[RetrievedChunk]) -> tuple[str, list[str]]:
        """Join chunk texts into one context block, deduped and length-capped."""
        parts: list[str] = []
        sources: list[str] = []
        seen: set[str] = set()
        used = 0
        for chunk in chunks:
            # Overlap means adjacent chunks legitimately share text; an exact duplicate
            # is a re-ingest artefact and wastes a context slot.
            key = chunk.text[:200]
            if key in seen:
                continue
            seen.add(key)
            if used + len(chunk.text) > self.settings.max_context_chars:
                # Skip this one and keep going rather than stopping here. Chunks arrive
                # in relevance order, not size order, so one long chunk near the cap
                # used to discard every shorter chunk behind it — including, on the
                # exploration-portfolio question, the one carrying the figures asked for.
                continue
            parts.append(chunk.text)
            used += len(chunk.text)
            if chunk.source and chunk.source not in sources:
                sources.append(chunk.source)
        return "\n\n".join(parts), sources

    # ── result cache ────────────────────────────────────────────────

    def _cache_get(self, query: str, top_k: int) -> RetrievalResult | None:
        key = f"{top_k}:{self._cache_key(query)}"
        entry = self._result_cache.get(key)
        if not entry:
            return None
        stamped, result = entry
        if time.time() - stamped > self.settings.result_cache_ttl_s:
            self._result_cache.pop(key, None)
            return None
        return result

    def _cache_put(self, query: str, top_k: int, result: RetrievalResult) -> None:
        key = f"{top_k}:{self._cache_key(query)}"
        self._result_cache[key] = (time.time(), result)
        while len(self._result_cache) > self.settings.result_cache_size:
            self._result_cache.pop(next(iter(self._result_cache)))

    def clear_caches(self) -> None:
        """Called after ingest — cached results point at chunks that may no longer exist."""
        self._result_cache.clear()
        self.embedding.clear_caches()

    async def health(self) -> dict:
        return {
            "ready": self._ready,
            "qdrant": await self.store.health(),
            "embedding": self.embedding.stats(),
            "glossary_terms": len(self.glossary),
            "result_cache": len(self._result_cache),
            "settings": {
                "top_k": self.settings.top_k,
                "prefetch_limit": self.settings.prefetch_limit,
                "rerank_candidates": self.settings.rerank_candidates,
                "rerank_enabled": self.settings.rerank_enabled,
                "score_threshold": self.settings.score_threshold,
                "dense_score_threshold": self.settings.dense_score_threshold,
                "chunk_tokens": self.settings.chunk_tokens,
                "section_expansion": self.settings.section_expansion,
            },
        }


_retriever: Retriever | None = None
_lock = asyncio.Lock()


async def get_retriever(settings: RagSettings | None = None) -> Retriever:
    """Process-wide singleton — it owns the models and the Qdrant connection."""
    global _retriever
    async with _lock:
        if _retriever is None:
            _retriever = Retriever(settings=settings)
    return _retriever
