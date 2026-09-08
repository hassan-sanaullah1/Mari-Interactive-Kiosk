"""Retrieval layer for the MARI kiosk.

    settings.py    every tunable, with the reason for its value
    chunking.py    structure-aware markdown/PDF chunking with heading paths
    documents.py   file parsing and content hashing
    embedding.py   FastEmbed dense + sparse + cross-encoder reranker
    store.py       Qdrant collection management and the hybrid RRF query
    ingestion.py   idempotent, hash-based startup ingest
    metadata.py    SQLite record of what is indexed
    transcript.py  STT domain-term correction
    rewriter.py    conditional, timeout-guarded query rewriting
    retriever.py   the single shared retrieve path
    generation.py  prompt assembly and streaming

Import order matters only in that `settings` must be importable without any model or
network dependency — eval and tests rely on that.
"""

from .settings import RagSettings, get_settings

__all__ = ["RagSettings", "get_settings"]
