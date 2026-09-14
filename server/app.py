"""MARI · Voice: FastAPI server for the kiosk UI.

    GET  /          the voice UI in web/
    GET  /healthz   provider, avatar and retrieval status
    POST /chat      {text, lang, history?, avatar?} → reply text only
    POST /voice     16 kHz WAV body, ?lang=&avatar= → transcript, reply, audio (base64)
    WS   /ws        the streaming turn the UI uses (see server/agent/turn.py)

Any stage that isn't configured or reachable degrades: the response carries what
succeeded plus an ``error`` note, and a canned line stands in for the LLM.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import avatar, providers, rag
from . import config as C
from .agent import speech
from .agent.replies import canned, pitch_override
from .agent.responder import respond
from .agent.turn import run_reply
from .prompts import get_prompts

logger = logging.getLogger(__name__)

# Mirrors AvatarId in frontend/components/avatar/models.ts. Anything else falls back to
# the default rig rather than reaching TTS with an id it has no voice for.
AVATARS = frozenset({"female", "male"})

app = FastAPI(title="MARI · Voice")


@app.on_event("startup")
async def _startup() -> None:
    get_prompts()  # a missing prompt file stops startup here
    asyncio.create_task(providers.warm("en"))
    asyncio.create_task(avatar.warm())
    # Minutes on a cold container; turns are answered from the core brief meanwhile.
    asyncio.create_task(rag.startup())


@app.on_event("shutdown")
async def _shutdown() -> None:
    await rag.shutdown()


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(C.WEB_DIR / "index.html")


@app.get("/healthz")
async def healthz() -> dict:
    return {
        "ok": True,
        **await C.status(),
        "rag": await rag.health(),
    }


class ChatIn(BaseModel):
    text: str
    lang: str = "en"
    # Prior turns, oldest first, as [{"role": "user"|"assistant", "text": ...}].
    history: list[dict] | None = None
    avatar: str = "female"


@app.post("/chat")
async def chat(body: ChatIn) -> dict:
    text = (body.text or "").strip()
    lang = body.lang if body.lang in C.LANGS else "en"
    avatar_id = body.avatar if body.avatar in AVATARS else "female"
    if not text:
        return {"reply": "", "demo": not C.llm_ready()}
    if (pitch := pitch_override(lang, avatar_id)) is not None:
        return {"reply": pitch, "demo": False}
    if not C.llm_ready():
        return {"reply": canned("demo", lang, avatar_id), "demo": True}
    try:
        return {"reply": await respond(text, lang, body.history, avatar_id), "demo": False}
    except Exception as exc:
        logger.warning("/chat: LLM call failed, falling back to demo line: %s", exc)
        return {"reply": canned("demo", lang, avatar_id), "demo": True, "error": str(exc)}


@app.post("/voice")
async def voice(request: Request, lang: str = "en", avatar: str = "female") -> dict:
    """Full single-shot turn: audio → STT → LLM → TTS."""
    lang = lang if lang in C.LANGS else "en"
    avatar_id = avatar if avatar in AVATARS else "female"
    wav = await request.body()
    out: dict = {"lang": lang, "transcript": "", "reply": "", "audio": None, "mime": None}

    try:
        out["transcript"] = await providers.stt(wav, lang)
        rag.prestart(out["transcript"])
    except Exception as exc:
        out["error"] = f"stt: {exc}"
        return out
    if not out["transcript"]:
        out["error"] = "no-speech"
        return out

    if (pitch := pitch_override(lang, avatar_id)) is not None:
        out["reply"] = pitch
    elif C.llm_ready():
        try:
            out["reply"] = await respond(out["transcript"], lang, None, avatar_id)
        except Exception as exc:
            logger.warning("/voice: LLM call failed, falling back to demo line: %s", exc)
            out["reply"] = canned("demo", lang, avatar_id)
            out["error"] = f"llm: {exc}"
    else:
        out["reply"] = canned("demo", lang, avatar_id)
        out["demo"] = True

    # Optional: the browser speaks the text itself if no audio comes back.
    if out["reply"] and C.tts_ready(lang):
        try:
            audio, mime = await speech.speak(out["reply"], lang, avatar_id)
            if audio:
                out["audio"] = base64.b64encode(audio).decode("ascii")
                out["mime"] = mime
        except Exception as exc:
            out["error"] = (out.get("error", "") + f" tts: {exc}").strip()

    return out


@app.websocket("/ws")
async def ws(sock: WebSocket) -> None:
    """One streaming turn per socket.

    Client → server: {"start", lang, avatar, history}, raw 16 kHz PCM frames, {"end", spoke}.
    Urdu PCM is relayed live to Soniox (partials come back as {"partial"}); English is
    buffered for Whisper. A typed turn sends {"text", text, lang, avatar, history} instead.
    """
    await sock.accept()
    lang = "en"
    avatar_id = "female"
    pcm = bytearray()
    stream: providers.SonioxStream | None = None
    # The browser's copy of the conversation; nothing about the visitor is kept here.
    history: list = []

    async def on_partial(text: str) -> None:
        try:
            await sock.send_json({"type": "partial", "text": text})
        except Exception:
            pass

    try:
        while True:
            msg = await sock.receive()
            if msg["type"] == "websocket.disconnect":
                break
            if (data := msg.get("bytes")) is not None:
                if stream is not None:
                    await stream.send(bytes(data))
                else:
                    pcm.extend(data)
                continue
            text = msg.get("text")
            if text is None:
                continue
            evt = json.loads(text)
            if evt.get("type") == "start":
                lang = evt.get("lang", "en")
                lang = lang if lang in C.LANGS else "en"
                if evt.get("avatar") in AVATARS:
                    avatar_id = evt["avatar"]
                history = evt.get("history") or []
                pcm.clear()
                if lang == "ur" and C.SONIOX_KEY:
                    stream = providers.SonioxStream(lang, on_partial=on_partial)
                    try:
                        await stream.start()
                    except Exception as exc:
                        await sock.send_json({"type": "error", "message": f"stt: {exc}"})
                        break
            elif evt.get("type") == "text":
                typed = (evt.get("text") or "").strip()
                if (want := evt.get("lang")) in C.LANGS:
                    lang = want
                if evt.get("avatar") in AVATARS:
                    avatar_id = evt["avatar"]
                history = evt.get("history") or []
                if stream is not None:
                    await stream.close()
                    stream = None
                rag.prestart(typed)
                await run_reply(
                    sock, typed, lang, echo_transcript=False, history=history, avatar_id=avatar_id
                )
                break
            elif evt.get("type") == "end":
                try:
                    if stream is not None:
                        transcript = await stream.finish()
                        stream = None
                    else:
                        transcript = await providers.stt(providers.pcm16_to_wav(bytes(pcm)), lang) if pcm else ""
                except Exception as exc:
                    await sock.send_json({"type": "error", "message": f"stt: {exc}"})
                    break
                # Embedding starts now, so retrieval finds the vector ready.
                rag.prestart(transcript)
                # An older browser sends a bare {"end"}; it keeps getting the apology.
                await run_reply(
                    sock, transcript, lang, history=history, avatar_id=avatar_id,
                    spoke=bool(evt.get("spoke", True)),
                )
                break
    except WebSocketDisconnect:
        pass
    except Exception as exc:  # pragma: no cover
        logger.exception("turn failed: %s", exc)
        try:
            await sock.send_json({"type": "error", "message": str(exc) or exc.__class__.__name__})
        except Exception:
            pass
    finally:
        if stream is not None:
            await stream.close()
        try:
            await sock.close()
        except Exception:
            pass


app.mount("/", StaticFiles(directory=str(C.WEB_DIR), html=True), name="static")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("server.app:app", host=C.HOST, port=C.PORT, reload=False)
