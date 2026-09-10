"""Bridge between the FastAPI app and the retrieval layer.

`server/app.py` used to call `knowledge.system_prompt(lang, text)` — one synchronous
function that did retrieval and prompt assembly together. The retrieval layer is async
and has more moving parts, so this module keeps that single-call shape for the app while
the complexity lives behind it.

It is also where the degradation policy lives. The kiosk is a physical device in a lobby:
it must answer, or visibly say it cannot, but it must never fail to speak. So if Qdrant
is unreachable, the models failed to download, or ingestion never ran, `system_prompt`
still returns a usable prompt — persona, rules, greeting and the always-on core brief,
with no retrieved sections and the "say you don't have that information" branch active.

What it does *not* do is quietly answer from a second, unevaluated retriever. There used
to be a BM25 index here for exactly that, and it made an outage invisible: the kiosk kept
talking, from a differently-chunked copy of the corpus that no eval run ever scored.
Degradation now shows up where it can be acted on — in `/healthz` and in the logs — while
the visitor gets an honest answer rather than a confident one built on an unknown path.
"""

from __future__ import annotations

import asyncio
import logging

from . import config as C
from . import knowledge
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

    Runs as a background task from the app's startup hook rather than blocking it: model
    download is minutes on a cold container, and a kiosk that serves a degraded answer
    immediately is better than one that refuses connections until it is perfect.
    """
    global _retriever, _status
    settings = get_settings()
    try:
        _status = {"enabled": True, "state": "warming"}
        retriever = await get_retriever(settings)

        _generator()  # cheap, and it must be ready even if the rest of this fails

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
        # Degraded, not dead: system_prompt() still returns persona + core brief, with
        # no retrieved sections. The kiosk keeps talking and says what it does not know.
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
    """The prompt builder, whether or not retrieval ever came up.

    Prompt assembly needs no models and no Qdrant — it is the persona files plus the
    core brief — so it stays available on the degraded path and one code path builds
    every prompt the kiosk speaks.
    """
    global _generation
    if _generation is None:
        _generation = GenerationService(get_settings())
        _generation.load_templates()
    return _generation


def _build(result: RetrievalResult, lang: str, text: str, avatar: str = "female") -> str:
    return _generator().build_prompt(
        result, lang,
        core_brief=knowledge.CORE_BRIEF,
        greeting=knowledge.is_greeting(text),
        avatar=avatar,
    ).system


async def system_prompt(lang: str, text: str = "", history: list[dict] | None = None,
                        avatar: str = "female") -> str:
    """The full system prompt for one turn.

    When retrieval is unavailable or fails, this returns the same prompt minus the
    retrieved sections: the persona holds, the core brief is still there, and the
    "say you don't have that information" branch fires. The visitor hears an honest
    answer; `/healthz` and the logs carry the reason.
    """
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
