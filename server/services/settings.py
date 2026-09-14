"""Tunable configuration for the retrieval layer.

Every value was measured with eval/run_eval.py or eval/calibrate.py; the numbers are in
docs/retrieval_tuning_notes.md. Environment prefix is ``MARI_RAG_``, for example
``MARI_RAG_TOP_K=4`` or ``MARI_RAG_QDRANT_HOST=qdrant``.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent.parent


class RagSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="MARI_RAG_",
        env_file=ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── models ──────────────────────────────────────────────────────
    # Multilingual is required: the corpus is English, about half the questions are Urdu.
    dense_model: str = "intfloat/multilingual-e5-large"
    dense_dim: int = 1024
    # Catches exact tokens dense embeddings miss ("NTN 1414673", "Bhitai-6", "Sky47").
    sparse_model: str = "Qdrant/bm25"

    # The best ranker and relevance gate measured, but ~450 ms per turn, so it is off
    # by default. An English ms-marco reranker made ranking worse on this corpus.
    reranker_model: str = "jinaai/jina-reranker-v2-base-multilingual"
    # Cross-encoder cost is linear in tokens; the heading and opening sentences carry
    # the signal, and chunking puts them first.
    rerank_doc_tokens: int = 128
    rerank_skip_for_urdu: bool = False
    # e.g. ["CUDAExecutionProvider"] on a GPU host.
    rerank_providers: list[str] = []
    # Re-run eval/calibrate.py after turning this on: the thresholds differ per path.
    rerank_enabled: bool = False

    # Asymmetric-model prefixes; resolved from the model name when left empty.
    query_prefix: str = ""
    passage_prefix: str = ""

    # ── chunking ────────────────────────────────────────────────────
    # In tokens from the embedding tokenizer; word counts overran the 512-token input.
    chunk_tokens: int = 320
    chunk_overlap_ratio: float = 0.15
    # Shorter chunks are heading stubs that score deceptively high on short queries.
    min_chunk_tokens: int = 30

    # ── retrieval ───────────────────────────────────────────────────
    # RRF can only promote what a channel surfaced, so this is the recall ceiling.
    prefetch_limit: int = 30
    rerank_candidates: int = 10
    top_k: int = 5
    # Rerank-probability gate for off-topic questions. On-topic but unanswerable
    # questions are the system prompt's job; tightening this costs real recall.
    score_threshold: float = 0.02
    # Dense-cosine gate for the non-reranked path. Deliberately permissive: blocking an
    # answerable question is worse than answering an off-topic one.
    dense_score_threshold: float = 0.72
    # Drop supporting chunks below this fraction of the top chunk's score; 0 keeps top_k.
    relative_score_floor: float = 0.10
    # Big enough for the longest section (the full Board list) to arrive whole.
    max_context_chars: int = 8000

    # ── section expansion ───────────────────────────────────────────
    # Complete the top chunk's section with its remaining chunks, so a question answered
    # by a whole list is not given two items of it. Appends only; ranking is unchanged.
    section_expansion: bool = True
    # Inside max_context_chars, which binds first; this is the knee, not the maximum.
    section_expansion_chars: int = 3500
    section_expansion_max_chunks: int = 6
    # Completing more than the rank-1 section made answers worse.
    section_expansion_sections: int = 1

    # ── query rewriting ─────────────────────────────────────────────
    # Rewrites elliptical follow-ups ("what about their pricing?"). Conditional and
    # timeout-guarded: on timeout the raw transcript is used.
    rewrite_enabled: bool = True
    # Measured p90 for a rewrite is ~920 ms; a timeout below that disables it silently.
    rewrite_timeout_ms: int = 1200
    rewrite_min_content_words: int = 4
    rewrite_history_turns: int = 3
    rewrite_model: str = ""  # defaults to the main LLM model when empty

    # Urdu → English expansion for the sparse channel (services/expansion.py).
    expand_urdu_lexical: bool = True
    # Remove the company's name from the dense query (see strip_corpus_subject).
    strip_subject_for_dense: bool = True

    # ── caching ─────────────────────────────────────────────────────
    # Per-process, cleared on ingest. Visitors at a public terminal repeat questions.
    embed_cache_size: int = 512
    result_cache_size: int = 256
    result_cache_ttl_s: float = 300.0

    # ── qdrant ──────────────────────────────────────────────────────
    qdrant_host: str = "127.0.0.1"
    qdrant_port: int = 6333
    qdrant_api_key: str = ""
    qdrant_collection: str = "mari_knowledge"
    qdrant_timeout_s: float = 5.0
    # qdrant-client switches to HTTPS whenever an api_key is set; in-cluster Qdrant is plaintext.
    qdrant_https: bool = False

    # ── ingestion ───────────────────────────────────────────────────
    corpus_dir: Path = ROOT / "server" / "data"
    # README.md documents the corpus; the Sky47 file would duplicate facts the Mari
    # corpus already summarises, and the persona may only state the Mari corpus.
    corpus_exclude: list[str] = ["README.md", "sky47_knowledge_base.md"]
    metadata_db: Path = ROOT / "server" / "data" / ".rag_metadata.sqlite"
    force_reingest: bool = False
    # Startup only: trades memory against boot time, not turn latency.
    ingest_batch_size: int = 32

    # ── behaviour ───────────────────────────────────────────────────
    # Inject definitions of abbreviations in the query, whatever retrieval returned.
    glossary_injection: bool = True
    log_stage_timings: bool = True

    @model_validator(mode="after")
    def _resolve_prefixes(self) -> "RagSettings":
        """Fill in the asymmetric-model prefixes from the model name, unless overridden.

        A wrong prefix degrades recall without raising, so a model swap must not leave a
        stale one behind.
        """
        if not self.query_prefix and not self.passage_prefix:
            name = self.dense_model.lower()
            if "e5" in name:
                self.query_prefix, self.passage_prefix = "query: ", "passage: "
            elif "bge" in name and "-v1.5" in name and name.endswith("-en-v1.5"):
                # BGE v1.5 English: query side only.
                self.query_prefix = "Represent this sentence for searching relevant passages: "
            # bge-m3, mxbai, nomic, arctic and paraphrase-* are symmetric: no prefix.
        return self

    @property
    def chunk_overlap_tokens(self) -> int:
        return max(0, int(self.chunk_tokens * self.chunk_overlap_ratio))


@lru_cache(maxsize=1)
def get_settings() -> RagSettings:
    return RagSettings()
