"""Embedding, sparse encoding and reranking, via FastEmbed (ONNX Runtime).

  dense     semantic and cross-lingual similarity (Urdu questions, English corpus)
  sparse    BM25, for identifiers with no useful semantics ("Bhitai-6", "1414673")
  reranker  a cross-encoder that judges relevance, not just similarity

Every entry point has an async variant on a worker thread: ONNX inference is CPU-bound,
and running it on the event loop stalls the audio being streamed to the visitor.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Sequence

import numpy as np

from .settings import RagSettings, get_settings

log = logging.getLogger(__name__)


class EmbeddingService:
    """Owns the three models and every code path that touches them."""

    def __init__(self, settings: RagSettings | None = None) -> None:
        self.settings = settings or get_settings()
        self._dense: Any = None
        self._sparse: Any = None
        self._reranker: Any = None
        self._tokenizer: Any = None
        # Model construction is not thread-safe and warmup loads three of them at once.
        self._lock = threading.Lock()
        # Bounded, ordered query->vector cache. A plain functools.lru_cache would work,
        # but it cannot be cleared per-ingest without clearing unrelated caches, and it
        # hides its size from /healthz.
        self._query_cache: dict[str, np.ndarray] = {}
        self._cache_lock = threading.Lock()

    # ── model loading ───────────────────────────────────────────────

    @property
    def dense(self) -> Any:
        if self._dense is None:
            with self._lock:
                if self._dense is None:
                    from fastembed import TextEmbedding

                    t0 = time.perf_counter()
                    self._dense = TextEmbedding(model_name=self.settings.dense_model)
                    log.info(
                        "loaded dense model %s in %.1fs",
                        self.settings.dense_model,
                        time.perf_counter() - t0,
                    )
        return self._dense

    @property
    def sparse(self) -> Any:
        if self._sparse is None:
            with self._lock:
                if self._sparse is None:
                    from fastembed import SparseTextEmbedding

                    self._sparse = SparseTextEmbedding(model_name=self.settings.sparse_model)
                    log.info("loaded sparse model %s", self.settings.sparse_model)
        return self._sparse

    @property
    def reranker(self) -> Any:
        if self._reranker is None:
            with self._lock:
                if self._reranker is None:
                    from fastembed.rerank.cross_encoder import TextCrossEncoder

                    t0 = time.perf_counter()
                    kwargs: dict[str, Any] = {"model_name": self.settings.reranker_model}
                    if self.settings.rerank_providers:
                        kwargs["providers"] = list(self.settings.rerank_providers)
                    self._reranker = TextCrossEncoder(**kwargs)
                    log.info(
                        "loaded reranker %s in %.1fs",
                        self.settings.reranker_model,
                        time.perf_counter() - t0,
                    )
        return self._reranker

    @property
    def tokenizer(self) -> Any:
        """The dense model's own tokenizer, used to size chunks.

        Falls back to None (and chunking's word-based estimate) rather than failing:
        a tokenizer that cannot be fetched should degrade chunk sizing, not stop the
        kiosk from starting.
        """
        if self._tokenizer is None:
            with self._lock:
                if self._tokenizer is None:
                    try:
                        from tokenizers import Tokenizer

                        self._tokenizer = Tokenizer.from_pretrained(self.settings.dense_model)
                    except Exception as exc:  # noqa: BLE001 - any failure means fall back
                        log.warning(
                            "no tokenizer for %s (%s); chunk sizing falls back to an "
                            "estimate, so chunks will be approximate",
                            self.settings.dense_model,
                            exc,
                        )
                        self._tokenizer = False
        return self._tokenizer or None

    def count_tokens(self, text: str) -> int:
        """Token count as the embedding model will see it. Injected into the chunker."""
        if tok := self.tokenizer:
            return len(tok.encode(text, add_special_tokens=False).ids)
        from .chunking import approx_token_count

        return approx_token_count(text)

    # ── warmup ──────────────────────────────────────────────────────

    def warmup(self) -> None:
        """Load and exercise every model before the first request.

        Loaded in parallel, and each run once: ONNX Runtime defers allocation to the
        first inference, which would otherwise land inside a visitor's turn.
        """
        t0 = time.perf_counter()
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = {
                "dense": pool.submit(lambda: list(self.dense.query_embed(["warmup"]))),
                "sparse": pool.submit(lambda: list(self.sparse.embed(["warmup"]))),
                "tokenizer": pool.submit(self.count_tokens, "warmup"),
            }
            if self.settings.rerank_enabled:
                futures["reranker"] = pool.submit(
                    lambda: list(self.reranker.rerank("warmup", ["warmup passage"]))
                )
            for name, future in futures.items():
                try:
                    future.result()
                except Exception:  # noqa: BLE001
                    log.exception("warmup failed for %s", name)
        log.info("embedding warmup finished in %.1fs", time.perf_counter() - t0)

    async def warmup_async(self) -> None:
        await asyncio.to_thread(self.warmup)

    # ── dense ───────────────────────────────────────────────────────

    @staticmethod
    def _normalize(vectors: np.ndarray) -> np.ndarray:
        """L2-normalize, so a cosine-distance collection is exact and a dot product works.

        FastEmbed normalizes most models already; doing it again is idempotent and costs
        microseconds. Relying on the model's default here is a silent-correctness bet
        that only shows up as subtly wrong rankings if a future model swap changes it.
        """
        norms = np.linalg.norm(vectors, axis=-1, keepdims=True)
        return vectors / np.maximum(norms, 1e-12)

    def embed(self, texts: Sequence[str]) -> np.ndarray:
        """Embed passages for indexing. Batched, normalized, passage-prefixed."""
        if not texts:
            return np.zeros((0, self.settings.dense_dim), dtype=np.float32)
        prefixed = [f"{self.settings.passage_prefix}{t}" for t in texts]
        vectors = np.asarray(list(self.dense.embed(prefixed)), dtype=np.float32)
        return self._normalize(vectors)

    def embed_query(self, query: str) -> np.ndarray:
        """Embed one query. Query-prefixed, normalized, and cached.

        The cache is worth more here than it looks: a kiosk gets the same handful of
        questions all day, and a repeat costs a dict lookup instead of a model call.
        """
        with self._cache_lock:
            if (hit := self._query_cache.get(query)) is not None:
                return hit

        vector = self._normalize(
            np.asarray(
                list(self.dense.query_embed([f"{self.settings.query_prefix}{query}"])),
                dtype=np.float32,
            )
        )[0]

        with self._cache_lock:
            self._query_cache[query] = vector
            # Plain FIFO eviction. True LRU would need a touch on every read and the hit
            # rate difference on a few-hundred-entry cache of kiosk questions is noise.
            while len(self._query_cache) > self.settings.embed_cache_size:
                self._query_cache.pop(next(iter(self._query_cache)))
        return vector

    async def embed_query_async(self, query: str) -> np.ndarray:
        """embed_query off the event loop. Use this from anything async."""
        with self._cache_lock:
            if (hit := self._query_cache.get(query)) is not None:
                return hit
        return await asyncio.to_thread(self.embed_query, query)

    async def embed_async(self, texts: Sequence[str]) -> np.ndarray:
        return await asyncio.to_thread(self.embed, list(texts))

    # ── sparse ──────────────────────────────────────────────────────
    # No prefixes: BM25 is lexical, and a prefix would just add constant term noise to
    # every vector.

    def embed_sparse(self, texts: Sequence[str]) -> list[Any]:
        return list(self.sparse.embed(list(texts))) if texts else []

    def embed_sparse_query(self, query: str) -> Any:
        # query_embed differs from embed for BM25: it skips the document-frequency
        # weighting that only makes sense over a corpus. Using embed() here would score
        # the query's own terms as if the query were a document.
        return next(iter(self.sparse.query_embed([query])))

    async def embed_sparse_query_async(self, query: str) -> Any:
        return await asyncio.to_thread(self.embed_sparse_query, query)

    # ── rerank ──────────────────────────────────────────────────────

    def _truncate_for_rerank(self, text: str) -> str:
        """Cut a candidate to settings.rerank_doc_tokens using the reranker's tokenizer.

        Cost is linear in tokens (255 ms → 58 ms at 128). Safe because chunks start with
        their heading path and opening lines.
        """
        cap = self.settings.rerank_doc_tokens
        if cap <= 0:
            return text
        try:
            tokenizer = self.reranker.model.tokenizer
            ids = tokenizer.encode(text, add_special_tokens=False).ids
            if len(ids) <= cap:
                return text
            return tokenizer.decode(ids[:cap])
        except Exception:  # noqa: BLE001 - fall back to a character estimate
            # ~4 characters per token is a deliberate over-estimate: cutting slightly
            # long costs a little latency, cutting short costs accuracy.
            return text[: cap * 4]

    def rerank(self, query: str, documents: Sequence[str]) -> list[float]:
        """Cross-encoder relevance scores, one per document, in the order given.

        Returned as raw logits — `to_probability` converts them. Keeping the raw value
        available matters for calibrating the threshold against the eval set.
        """
        if not documents:
            return []
        docs = [self._truncate_for_rerank(d) for d in documents]
        return [float(s) for s in self.reranker.rerank(query, docs)]

    @staticmethod
    def to_probability(score: float) -> float:
        """Sigmoid over the cross-encoder logit, so the threshold is a real probability.

        Thresholding on raw logits would make settings.score_threshold meaningless
        across a model change — logit scales differ wildly between rerankers, while
        "0.3 probability of relevance" transfers.
        """
        return float(1.0 / (1.0 + np.exp(-score)))

    async def rerank_async(self, query: str, documents: Sequence[str]) -> list[float]:
        return await asyncio.to_thread(self.rerank, query, list(documents))

    # ── cache management ────────────────────────────────────────────

    def clear_caches(self) -> None:
        """Called after ingest: cached vectors are still valid, cached results are not."""
        with self._cache_lock:
            self._query_cache.clear()

    def stats(self) -> dict:
        return {
            "dense_model": self.settings.dense_model,
            "dense_loaded": self._dense is not None,
            "sparse_model": self.settings.sparse_model,
            "sparse_loaded": self._sparse is not None,
            "reranker_model": self.settings.reranker_model if self.settings.rerank_enabled else None,
            "reranker_loaded": self._reranker is not None,
            "query_cache": len(self._query_cache),
        }


_service: EmbeddingService | None = None
_service_lock = threading.Lock()


def get_embedding_service(settings: RagSettings | None = None) -> EmbeddingService:
    """Process-wide singleton. The models are hundreds of MB; there must be exactly one."""
    global _service
    if _service is None:
        with _service_lock:
            if _service is None:
                _service = EmbeddingService(settings)
    return _service
