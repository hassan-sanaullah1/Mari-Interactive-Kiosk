"""MARI kiosk backend: the API the Next.js kiosk in frontend/ talks to.

    GET  /healthz   provider, avatar and retrieval status
    POST /chat      {text, lang, history?, avatar?} → reply text only
    WS   /ws        the streaming turn the UI uses (see server/agent/turn.py)

Any stage that isn't configured or reachable degrades: the response carries what
succeeded plus an ``error`` note, and a canned line stands in for the LLM.
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import FastAPI, WebSocket
from pydantic import BaseModel

from . import avatar, config, providers, rag
from .agent.policy import failure_reply, fallback_reply
from .agent.responder import respond
from .agent.session import VoiceSession
from .personas import get_persona
from .prompts import get_prompts

logger = logging.getLogger(__name__)

app = FastAPI(title="MARI · Voice")


@app.on_event("startup")
async def _startup() -> None:
    get_prompts()  # a missing prompt file stops startup here
    asyncio.create_task(providers.warm("en"))
    if config.UR_TTS == "matcha":
        # Only checks the local TTS server; Soniox has nothing to preload.
        asyncio.create_task(providers.warm("ur"))
    asyncio.create_task(avatar.warm())
    # Minutes on a cold container; turns are answered from the core brief meanwhile.
    asyncio.create_task(rag.startup())


@app.on_event("shutdown")
async def _shutdown() -> None:
    await rag.shutdown()


@app.get("/healthz")
async def healthz() -> dict:
    return {
        "ok": True,
        **await config.status(),
        "rag": await rag.health(),
    }


class ChatIn(BaseModel):
    text: str
    lang: str = "en"
    # Prior turns, oldest first, as [{"role": "user"|"assistant", "text": ...}].
    history: list[dict] | None = None
    # A presenter id from server/personas.toml; anything else becomes the default.
    avatar: str | None = None


@app.post("/chat")
async def chat(body: ChatIn) -> dict:
    text = (body.text or "").strip()
    lang = body.lang if body.lang in config.LANGS else "en"
    avatar_id = get_persona(body.avatar).id
    if not text:
        return {"reply": "", "demo": not config.llm_ready()}
    if (stand_in := fallback_reply(lang, avatar_id)) is not None:
        return {"reply": stand_in.text, "demo": stand_in.is_demo}
    try:
        return {"reply": await respond(text, lang, body.history, avatar_id), "demo": False}
    except Exception as exc:
        logger.warning("/chat: LLM call failed, falling back to demo line: %s", exc)
        failed = failure_reply(lang, avatar_id)
        return {"reply": failed.text, "demo": failed.is_demo, "error": str(exc)}


@app.websocket("/ws")
async def ws(sock: WebSocket) -> None:
    """One streaming turn per socket; the state and handlers are in VoiceSession."""
    await VoiceSession(sock).run()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("server.app:app", host=config.HOST, port=config.PORT, reload=False)
