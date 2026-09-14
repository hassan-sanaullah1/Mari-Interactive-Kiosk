"""The app's single entry point into retrieval and prompt assembly.

It also owns the degradation policy. The kiosk must always speak, so if Qdrant is
unreachable, the models failed to download or ingestion never ran, ``system_prompt``
still returns persona, greeting and core brief, with no retrieved sections and the
"say you don't have that information" instruction active. The reason shows up in
``/healthz`` and the logs.
"""

from __future__ import annotations

import asyncio
import logging

from . import config as C
from .agent.greeting import is_greeting
from .prompts import get_prompts
from .services.generation import GenerationService
from .services.retriever import RetrievalResult, Retriever, get_retriever
from .services.settings import get_settings

log = logging.getLogger(__name__)

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
            from .services.ingestion import IngestionService

            service = IngestionService(retriever.store, retriever.embedding, settings=settings)
            report = await service.ingest_all()
            _status["ingest"] = report.as_dict()

        await retriever.warmup()
        retriever.clear_caches()

        _retriever = retriever
        _status["state"] = "ready"
        log.info("RAG layer ready")
    except Exception as exc:  # noqa: BLE001
        _status = {"enabled": False, "state": "failed", "error": f"{type(exc).__name__}: {exc}"}
        log.exception("RAG startup failed; serving prompts with no retrieved context")


async def shutdown() -> None:
    if _retriever is not None:
        await _retriever.close()


def prestart(text: str) -> None:
    """Begin embedding a transcript before the turn handler needs it. See Retriever.prestart."""
    if _retriever is not None and text:
        try:
            _retriever.prestart(text)
        except Exception:  # noqa: BLE001 - an optimisation must never break a turn
            log.debug("prestart failed", exc_info=True)


async def retrieve(text: str, lang: str = "en", history: list[dict] | None = None):
    if _retriever is None:
        return None
    return await _retriever.retrieve(
        text, lang=lang, history=history,
        llm_base=C.LLM_BASE, llm_key=C.LLM_KEY, llm_model=C.LLM_MODEL,
    )


def _generator() -> GenerationService:
    """The prompt builder. Needs no models or Qdrant, so it works on the degraded path."""
    global _generation
    if _generation is None:
        _generation = GenerationService(get_settings())
        _generation.load_templates()
    return _generation


def _build(result: RetrievalResult, lang: str, text: str, avatar: str = "female") -> str:
    return _generator().build_prompt(
        result, lang,
        core_brief=get_prompts().core_brief,
        greeting=is_greeting(text),
        avatar=avatar,
    ).system


async def system_prompt(lang: str, text: str = "", history: list[dict] | None = None,
                        avatar: str = "female") -> str:
    """The full system prompt for one turn, minus retrieved sections if retrieval fails."""
    if _retriever is None:
        return _build(
            RetrievalResult(degraded=_status.get("state", "unavailable")), lang, text, avatar
        )
    try:
        return _build(await retrieve(text, lang, history), lang, text, avatar)
    except Exception as exc:  # noqa: BLE001
        log.exception("prompt assembly failed; serving this turn with no retrieved context")
        return _build(RetrievalResult(degraded=f"{type(exc).__name__}: {exc}"), lang, text, avatar)


async def health() -> dict:
    out = dict(_status)
    if _retriever is not None:
        try:
            out["retriever"] = await asyncio.wait_for(_retriever.health(), timeout=3.0)
        except Exception as exc:  # noqa: BLE001
            out["retriever"] = {"error": f"{type(exc).__name__}: {exc}"}
    return out
