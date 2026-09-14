"""The one retrieval path. Anything that needs retrieval calls ``Retriever.retrieve``.

Stages, in order:

  1. transcript correction   domain terms fixed before anything reads the query
  2. query rewrite           elliptical follow-ups only, timeout-guarded (rewriter.py)
  3. embed (dense + sparse)  usually already started by ``prestart``
  4. hybrid search + RRF     one Qdrant round trip, fused server-side
  5. rerank                  optional cross-encoder over the fused candidates
  6. threshold               calibrated relevance gate: lets the kiosk say "I don't know"
  7. section expansion       completes the section the top chunk came from
  8. glossary injection      abbreviation definitions, whatever retrieval returned
  9. context assembly        joined, deduped, length-capped

Every stage is timed, and a failure degrades the result rather than failing the turn.
Measurements behind these choices: docs/retrieval_tuning_notes.md.
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
from .glossary import extract_glossary, find_glossary_matches, format_glossary_block
from .rewriter import QueryRewriter
from .settings import RagSettings, get_settings
from .expansion import expand_for_lexical, has_urdu, strip_corpus_subject
from .store import Hit, QdrantStore
from .transcript import correct_transcript

log = logging.getLogger(__name__)

@dataclass
class RetrievedChunk:
    text: str
    source: str
    heading_path: str
    score: float           # rerank probability when reranked, else the RRF score
    fusion_score: float    # always the RRF score, kept for tuning
    reranked: bool
    # Appended by section expansion, not ranked. Its score is 0 and must not be
    # compared with a ranked chunk's.
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
    """Records per-stage wall clock into a dict."""

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
        # Independent, so loaded concurrently: roughly halves cold start.
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
        """Scan the whole corpus once for "ABBR (Full Form)" pairs.

        A corpus can use an abbreviation fifty times and define it once, and top-k
        returns the chunks that use it, so the definition is injected deterministically.
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
        """Begin embedding `text` as soon as STT produces it, so the 15-40 ms is off the
        visitor's wait. Safe to call repeatedly: one task per distinct string."""
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
        """Cancel all but the newest few unclaimed tasks (one per STT partial)."""
        while len(self._prestarted) > keep:
            oldest = next(iter(self._prestarted))
            self._prestarted.pop(oldest).cancel()

    async def _embed_both(self, text: str) -> tuple[np.ndarray, object, list[str]]:
        # The channels get different text. Sparse gets the Urdu-expanded form, since BM25
        # is purely lexical; dense gets the query as spoken, which the multilingual
        # model aligns better than a bag of translated keywords.
        lexical, _terms = (
            expand_for_lexical(text) if self.settings.expand_urdu_lexical else (text, [])
        )
        # Dense also drops the company's own name (see strip_corpus_subject).
        focused = (
            strip_corpus_subject(text) if self.settings.strip_subject_for_dense else text
        )
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
            # Explains a near-zero embed timing.
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
            # Never fatal: the persona and core brief still go in, and the visitor hears
            # an honest "I don't have that". There is deliberately no fallback retriever;
            # empty context is the visible signal, and /healthz reports why.
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
        """A total, deterministic order on the fused hits.

        RRF scores tie often, and Qdrant returns ties in an order that is not stable
        across processes. The tie-break is document order: content-neutral, for
        reproducibility only. A tie-break that moves hit@1 is not a retrieval improvement.
        """
        return sorted(hits, key=lambda h: (-h.score, h.source, h.chunk_index))

    async def _rerank_and_gate(self, query: str, hits: list[Hit], top_k: int) -> list[RetrievedChunk]:
        s = self.settings
        if not hits:
            return []
        hits = self._order(hits)

        # Only for an English-only cross-encoder, which scores Urdu queries as noise.
        skip = s.rerank_skip_for_urdu and has_urdu(query)

        if not s.rerank_enabled or skip:
            # Order by RRF, but gate on dense cosine: RRF is rank-based, so something is
            # always rank 1 and its score does not separate answerable questions.
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
        """The section that owns rank 1, and only that one.

        Completing more sections raised recall but filled the context with the company
        overview and made answers worse (see docs/retrieval_tuning_notes.md).
        """
        top = chunks[0].heading_path.split(" > ")[0].strip()
        return [top] if top else []

    def _gate(self, chunks: list[RetrievedChunk], threshold: float) -> list[RetrievedChunk]:
        """Apply the threshold to the result as a whole, not to each chunk.

        The question is whether anything relevant exists, which is a property of the best
        match. Filtering every chunk cut the supporting chunks and cost 23 points of
        hit@5. The relative floor still drops the long tail.
        """
        if not chunks:
            return []
        # The best chunk, not the rank-1 chunk: RRF's rank 1 is often a lexical winner
        # with mediocre dense similarity.
        if max(c.score for c in chunks) < threshold:
            # Nothing relevant: the prompt's "say you don't know" instruction takes over.
            return []
        floor = max(c.score for c in chunks) * self.settings.relative_score_floor
        return [c for c in chunks if c.score >= floor]

    async def _expand_section(
        self, chunks: list[RetrievedChunk]
    ) -> tuple[list[RetrievedChunk], int]:
        """Append the unretrieved chunks of the winning section.

        Most sections are enumerations ("eleven discoveries"), and top-k returns two
        entries of one. Appended chunks carry ``expanded=True`` and score 0, and come
        after the ranked chunks, in document order.
        """
        s = self.settings
        if not s.section_expansion or not chunks:
            return chunks, 0

        sections = self._sections_to_complete(chunks)
        if not sections:
            return chunks, 0

        # Matched on leading text, since overlapping chunks share their tails.
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
                    # Skip rather than stop, so one long chunk does not hide shorter ones.
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
            # An exact duplicate is a re-ingest artefact.
            key = chunk.text[:200]
            if key in seen:
                continue
            seen.add(key)
            if used + len(chunk.text) > self.settings.max_context_chars:
                # Skip rather than stop, so one long chunk does not drop shorter ones.
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
