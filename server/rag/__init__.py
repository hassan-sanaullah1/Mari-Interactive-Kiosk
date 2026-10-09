"""Retrieval: the corpus, the index, and the system prompt one turn is grounded on.

This package is the app's single entry point into retrieval, and it owns the
degradation policy. The kiosk must always speak, so if Qdrant is unreachable, the
models failed to download or ingestion never ran, ``system_prompt`` still returns
persona, greeting and core brief, with no retrieved sections and the "say you don't
have that information" instruction active. The reason shows up in ``/healthz`` and
the logs.

Inside:

    settings.py     every tunable (MARI_RAG_*); importable with no model or network
    chunking.py     structure-aware markdown/PDF chunking with heading paths
    documents.py    file parsing and content hashing
    embedding.py    FastEmbed dense + sparse + cross-encoder reranker
    store.py        Qdrant collection management and the hybrid RRF query
    ingestion.py    idempotent, hash-based startup ingest
    metadata.py     SQLite record of what is indexed
    transcript.py   STT domain-term correction for the retrieval query
    rewriter.py     conditional, timeout-guarded follow-up query rewriting
    expansion.py    Urdu to English query expansion (tables in expansion_tables.py)
    glossary.py     abbreviation definitions mined from the corpus
    retriever.py    the single retrieve path
    generation.py   system prompt assembly
"""

from __future__ import annotations

import asyncio
import logging

from .. import config
from ..agent.greeting import is_greeting
from ..prompts import get_prompts
from .generation import GenerationService
from .retriever import RetrievalResult, Retriever, get_retriever
from .settings import get_settings

logger = logging.getLogger(__name__)

_retriever: Retriever | None = None
_generation: GenerationService | None = None
_status: dict = {"enabled": False, "state": "not started"}


def enabled() -> bool:
    return _retriever is not None


async def startup(ingest: bool = True) -> None:
    """Warm models, ensure the collection, ingest the corpus. Safe to fail.

    Run as a background task: a cold container spends minutes downloading models, and
    the kiosk answers from the core brief meanwhile.
    """
    global _retriever, _status
    settings = get_settings()
    try:
        _status = {"enabled": True, "state": "warming"}
        retriever = await get_retriever(settings)

        _generator()  # must be ready even if the rest of this fails

        if ingest:
            from .ingestion import IngestionService

            service = IngestionService(retriever.store, retriever.embedding, settings=settings)
            report = await service.ingest_all()
            _status["ingest"] = report.as_dict()

        await retriever.warmup()
        retriever.clear_caches()

        _retriever = retriever
        _status["state"] = "ready"
        logger.info("RAG layer ready")
    except Exception as exc:  # noqa: BLE001
        _status = {"enabled": False, "state": "failed", "error": f"{type(exc).__name__}: {exc}"}
        logger.exception("RAG startup failed; serving prompts with no retrieved context")


async def shutdown() -> None:
    if _retriever is not None:
        await _retriever.close()


def prestart(text: str) -> None:
    """Begin embedding a transcript before the turn handler needs it. See Retriever.prestart."""
    if _retriever is not None and text:
        try:
            _retriever.prestart(text)
        except Exception:  # noqa: BLE001 - an optimisation must never break a turn
            logger.debug("prestart failed", exc_info=True)


async def retrieve(
    text: str, lang: str = "en", history: list[dict] | None = None
) -> RetrievalResult | None:
    if _retriever is None:
        return None
    return await _retriever.retrieve(
        text,
        lang=lang,
        history=history,
        llm_base=config.LLM_BASE,
        llm_key=config.LLM_KEY,
        llm_model=config.LLM_MODEL,
    )


def _generator() -> GenerationService:
    """The prompt builder. Needs no models or Qdrant, so it works on the degraded path."""
    global _generation
    if _generation is None:
        _generation = GenerationService(get_settings())
        _generation.load_templates()
    return _generation


def _build(result: RetrievalResult, lang: str, text: str, avatar: str | None = None) -> str:
    return (
        _generator()
        .build_prompt(
            result,
            lang,
            core_brief=get_prompts().core_brief,
            greeting=is_greeting(text),
            avatar=avatar,
        )
        .system
    )


async def system_prompt(
    lang: str, text: str = "", history: list[dict] | None = None, avatar: str | None = None
) -> str:
    """The full system prompt for one turn, minus retrieved sections if retrieval fails."""
    if _retriever is None:
        return _build(
            RetrievalResult(degraded=_status.get("state", "unavailable")), lang, text, avatar
        )
    try:
        result = await retrieve(text, lang, history)
        if result is None:  # shutdown cleared the retriever after the check above
            result = RetrievalResult(degraded=_status.get("state", "unavailable"))
        return _build(result, lang, text, avatar)
    except Exception as exc:  # noqa: BLE001
        logger.exception("prompt assembly failed; serving this turn with no retrieved context")
        return _build(RetrievalResult(degraded=f"{type(exc).__name__}: {exc}"), lang, text, avatar)


async def readiness(timeout_s: float = 0.8) -> str:
    """Qdrant's state for /health/ready: "ok", "warming" or "fail". Never raises.

    Warming counts as able to serve, because turns are answered from the core brief
    until retrieval is up. The timeout keeps the whole health check under a second.
    """
    if _retriever is None:
        return "warming" if _status.get("state") in ("not started", "warming") else "fail"
    try:
        store_health = await asyncio.wait_for(_retriever.store.health(), timeout=timeout_s)
    except Exception:  # noqa: BLE001 - a timeout or a dropped connection is just "fail"
        return "fail"
    return "ok" if store_health.get("reachable") else "fail"


async def health() -> dict:
    out = dict(_status)
    if _retriever is not None:
        try:
            out["retriever"] = await asyncio.wait_for(_retriever.health(), timeout=3.0)
        except Exception as exc:  # noqa: BLE001
            out["retriever"] = {"error": f"{type(exc).__name__}: {exc}"}
    return out
