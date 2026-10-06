"""Retrieval layer for the MARI kiosk.

    settings.py           every tunable (MARI_RAG_*)
    chunking.py           structure-aware markdown/PDF chunking with heading paths
    documents.py          file parsing and content hashing
    embedding.py          FastEmbed dense + sparse + cross-encoder reranker
    store.py              Qdrant collection management and the hybrid RRF query
    ingestion.py          idempotent, hash-based startup ingest
    metadata.py           SQLite record of what is indexed
    transcript.py         STT domain-term correction for the retrieval query
    rewriter.py           conditional, timeout-guarded follow-up query rewriting
    expansion.py          Urdu → English query expansion (tables in expansion_tables.py)
    glossary.py           abbreviation definitions mined from the corpus
    retriever.py          the single retrieve path
    generation.py         system prompt assembly

``settings`` must stay importable without any model or network dependency.
"""

from .settings import RagSettings, get_settings

__all__ = ["RagSettings", "get_settings"]
