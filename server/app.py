"""MARI · Voice — web front-end server.

Serves the sleek one-tap voice UI in ``web/`` and runs speech-to-speech server-side
without LiveKit:

    POST /voice   audio (16 kHz mono WAV) + ?lang=en|ur
                  → STT → vLLM Qwen (LLM) → TTS
                  → {transcript, reply, audio(base64), mime}

    POST /chat    {text, lang} → LLM reply text only (used as a fallback / for testing)

Per-language providers (see server/providers.py, server/config.py):
    Urdu     Soniox STT  ·  Uplift TTS
    English  Whisper STT ·  Kokoro TTS
    LLM      vLLM Qwen (OpenAI-compatible, APP_VLLM_*)

Any stage that isn't configured/reachable degrades gracefully: the response carries
what succeeded plus an ``error`` note, and the browser falls back to local speech so
the UI never dead-ends.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import re

import httpx
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import config as C
from . import knowledge
from . import providers
from . import avatar

WEB_DIR = C.WEB_DIR

DEMO_REPLY = {
    "en": "I heard you, but the language model isn't reachable from here, so I can't answer "
    "from the Sky47 knowledge base right now. You'll find the same information at sky47.com.pk.",
    "ur": "میں نے آپ کی بات سن لی، لیکن لینگویج ماڈل تک رسائی نہیں، اس لیے ابھی Sky47 کی معلومات "
    "سے جواب نہیں دے سکتی۔ یہی تفصیل sky47.com.pk پر موجود ہے۔",
}

app = FastAPI(title="MARI · Voice")


@app.on_event("startup")
async def _warmup() -> None:
    """Preload the local English models in the background so the first English turn
    isn't slowed by model load. No-op if English uses the remote APIs / models absent."""
    import asyncio

    asyncio.create_task(providers.warm("en"))
    # Dial the Audio2Face gRPC channel eagerly so the first reply's lipsync
    # isn't delayed by connection setup. No-op when A2F isn't configured.
    asyncio.create_task(avatar.warm())


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")


@app.get("/healthz")
async def healthz() -> dict:
    return {
        "ok": True,
        **C.status(),
        "knowledge": {"ready": knowledge.ready(), "sections": len(knowledge.CHUNKS)},
    }


def _llm_extra() -> dict:
    """Extra request params per provider. vLLM Qwen3.5 is a reasoning model, so we
    disable its chain-of-thought; DeepSeek would reject that param, so send nothing."""
    if C.LLM_PROVIDER == "vllm":
        return {"chat_template_kwargs": {"enable_thinking": False}}
    return {}


async def run_llm(text: str, lang: str) -> str:
    """Ask the LLM for a spoken-style reply, grounded in the Sky47 knowledge base.
    Raises on failure (caller handles)."""
    payload = {
        "model": C.LLM_MODEL,
        "messages": [
            {"role": "system", "content": knowledge.system_prompt(lang, text)},
            {"role": "user", "content": text},
        ],
        "temperature": 0.7,
        "max_tokens": 220,
        "stream": False,
        **_llm_extra(),
    }
    headers = {"Content-Type": "application/json"}
    if C.LLM_KEY:
        headers["Authorization"] = f"Bearer {C.LLM_KEY}"
    async with httpx.AsyncClient(timeout=httpx.Timeout(60, connect=5)) as client:
        r = await client.post(f"{C.LLM_BASE}/chat/completions", headers=headers, json=payload)
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"].strip()


class ChatIn(BaseModel):
    text: str
    lang: str = "en"


@app.post("/chat")
async def chat(body: ChatIn) -> dict:
    text = (body.text or "").strip()
    lang = body.lang if body.lang in knowledge.LANGS else "en"
    if not text:
        return {"reply": "", "demo": not C.llm_ready()}
    if not C.llm_ready():
        return {"reply": DEMO_REPLY[lang], "demo": True}
    try:
        return {"reply": await run_llm(text, lang), "demo": False}
    except Exception as exc:
        return {"reply": DEMO_REPLY[lang], "demo": True, "error": str(exc)}


@app.post("/voice")
async def voice(request: Request, lang: str = "en") -> dict:
    """Full turn: audio → STT → LLM → TTS. Returns transcript, reply, and reply audio."""
    lang = lang if lang in knowledge.LANGS else "en"
    wav = await request.body()
    out: dict = {"lang": lang, "transcript": "", "reply": "", "audio": None, "mime": None}

    # 1) speech-to-text
    try:
        out["transcript"] = await providers.stt(wav, lang)
    except Exception as exc:
        out["error"] = f"stt: {exc}"
        return out
    if not out["transcript"]:
        out["error"] = "no-speech"
        return out

    # 2) LLM reply (falls back to a spoken demo line if vLLM is unreachable)
    if C.llm_ready():
        try:
            out["reply"] = await run_llm(out["transcript"], lang)
        except Exception as exc:
            out["reply"] = DEMO_REPLY[lang]
            out["error"] = f"llm: {exc}"
    else:
        out["reply"] = DEMO_REPLY[lang]
        out["demo"] = True

    # 3) text-to-speech (optional — browser speaks the text if this is empty)
    if out["reply"] and C.tts_ready(lang):
        try:
            audio, mime = await providers.tts(out["reply"], lang)
            if audio:
                out["audio"] = base64.b64encode(audio).decode("ascii")
                out["mime"] = mime
        except Exception as exc:
            out["error"] = (out.get("error", "") + f" tts: {exc}").strip()

    return out


# ------------------------------------------------------------------ #
# Streaming pipeline over WebSocket — the low-latency path the UI uses.
#   client → {"start",lang}  <wav bytes…>  {"end"}
#   server → {"stt",text} · then per sentence: {"reply",text} {"tts",mime,clip} <audio> ·
#            finally {"done",spoken}
#            plus, out of band, {"lipsync",uid,names?,frames} — Audio2Face blendshape
#            keyframes for the avatar, keyed to the matching {"tts"} message's `clip`.
# Streaming the LLM sentence-by-sentence and synthesizing each as it lands means the
# first audio plays long before the full reply is finished.
# ------------------------------------------------------------------ #
_SENTENCE_END = re.compile(r"[.!?۔؟…]+[\"'”’)]?\s|\n+")


def _split_sentences(text: str) -> list[str]:
    out, buf = [], ""
    for ch in text:
        buf += ch
        if ch in ".!?۔؟…\n" and len(buf.strip()) > 1:
            out.append(buf.strip())
            buf = ""
    if buf.strip():
        out.append(buf.strip())
    return out


async def llm_stream_sentences(text: str, lang: str):
    """Yield MARI's reply — grounded in the Sky47 knowledge base — one sentence at a
    time as the LLM streams tokens.
    Falls back to the demo line (also sentence-split) if vLLM is unreachable."""
    if not C.llm_ready():
        for s in _split_sentences(DEMO_REPLY[lang]):
            yield s, True
        return

    payload = {
        "model": C.LLM_MODEL,
        "messages": [
            {"role": "system", "content": knowledge.system_prompt(lang, text)},
            {"role": "user", "content": text},
        ],
        "temperature": 0.7,
        "max_tokens": 220,
        "stream": True,
        **_llm_extra(),
    }
    headers = {"Content-Type": "application/json"}
    if C.LLM_KEY:
        headers["Authorization"] = f"Bearer {C.LLM_KEY}"

    buf = ""
    emitted = False
    try:
        # read timeout applies between streamed chunks, so a real reply is fine; a dead
        # vLLM (half-open tunnel) fails at ~12s instead of hanging the whole turn.
        async with httpx.AsyncClient(timeout=httpx.Timeout(connect=4, read=12, write=8, pool=4)) as client:
            async with client.stream(
                "POST", f"{C.LLM_BASE}/chat/completions", headers=headers, json=payload
            ) as r:
                r.raise_for_status()
                async for line in r.aiter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        delta = json.loads(data)["choices"][0]["delta"].get("content", "")
                    except Exception:
                        continue
                    if not delta:
                        continue
                    buf += delta
                    while True:
                        m = _SENTENCE_END.search(buf)
                        if not m:
                            break
                        cut = m.end()
                        sent = buf[:cut].strip()
                        buf = buf[cut:]
                        if sent:
                            emitted = True
                            yield sent, False
        if buf.strip():
            yield buf.strip(), False
    except Exception:
        # LLM failed (unreachable / mid-stream) — speak what we have or the demo line
        if buf.strip():
            yield buf.strip(), False
        elif not emitted:
            for s in _split_sentences(DEMO_REPLY[lang]):
                yield s, True


_turn_seq = 0


async def run_reply(
    sock: WebSocket, transcript: str, lang: str, echo_transcript: bool = True
) -> None:
    """From the final transcript: stream LLM sentences → TTS each → push audio.

    ``transcript`` is whatever the user said — or, for a typed turn, whatever they
    typed; the two are identical from here on. ``echo_transcript`` is False for the
    typed path, where the browser already has the text on screen and doesn't need
    it read back.

    The synthesized audio is ALSO handed to Audio2Face (one clip per sentence)
    when it's configured; its blendshape frames are published on this same
    socket as {"type":"lipsync"} messages, tagged with the clip id carried on
    the sentence's {"type":"tts"} message so the browser can line the frames up
    with the exact <audio> element it plays. The A2F work runs in background
    tasks — the audio path's timing is unchanged.
    """
    global _turn_seq
    _turn_seq += 1
    turn_id = f"t{_turn_seq}"

    # The reply path and the A2F publishers both write to this socket; Starlette
    # WebSockets are not safe for concurrent sends, so everything goes through
    # one lock (which also keeps each {"tts"} header glued to its audio bytes).
    lock = asyncio.Lock()

    async def send_json(payload: dict) -> None:
        async with lock:
            await sock.send_json(payload)

    async def send_audio(header: dict, audio: bytes) -> None:
        async with lock:
            await sock.send_json(header)
            await sock.send_bytes(audio)

    a2f = avatar.get_a2f_client()
    lips = avatar.LipsyncTurn(a2f, send_json, turn_id) if a2f is not None else None

    try:
        if echo_transcript:
            await send_json({"type": "stt", "text": transcript, "lang": lang})
        if not transcript:
            await send_json({"type": "done", "spoken": False})
            return
        spoken = False
        async for sentence, is_demo in llm_stream_sentences(transcript, lang):
            await send_json({"type": "reply", "text": sentence, "demo": is_demo})
            if C.tts_ready(lang):
                # Open (and start priming) this sentence's A2F clip before
                # synthesis, so the stream is warm by the time audio exists.
                clip = lips.open_clip() if lips is not None else None
                try:
                    audio, mime = await providers.tts(sentence, lang)
                    if audio:
                        header = {"type": "tts", "mime": mime}
                        if clip is not None:
                            header["clip"] = clip
                        await send_audio(header, audio)
                        spoken = True
                        if clip is not None:
                            # The same bytes the user is about to hear — fanned
                            # out to A2F, with no second synthesis pass.
                            lips.feed(clip, audio, mime)
                    elif clip is not None:
                        lips.cancel(clip)
                except Exception as exc:
                    if clip is not None:
                        lips.cancel(clip)
                    await send_json({"type": "warn", "message": f"tts: {exc}"})
        await send_json({"type": "done", "spoken": spoken})
        if lips is not None:
            # Hold the socket open until the last clip's frames are out — the
            # browser is still playing the audio they belong to.
            await lips.drain()
    except Exception:
        if lips is not None:
            await lips.abort()
        raise


@app.websocket("/ws")
async def ws(sock: WebSocket) -> None:
    """Streaming turn. Client streams raw 16 kHz PCM frames as it captures; for Urdu we
    relay them to Soniox live (partials sent back as captions); English buffers to a WAV
    for Whisper. On {end} we finalize STT and stream the reply.

    A typed turn skips capture entirely: {"type":"text",text,lang} goes straight to
    the reply stream, so the chat composer gets spoken audio and lipsync too."""
    await sock.accept()
    lang = "en"
    pcm = bytearray()
    stream: providers.SonioxStream | None = None

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
                    await stream.send(bytes(data))   # Urdu: live to Soniox
                else:
                    pcm.extend(data)                 # English: buffer for Whisper
                continue
            text = msg.get("text")
            if text is None:
                continue
            evt = json.loads(text)
            if evt.get("type") == "start":
                lang = evt.get("lang", "en")
                lang = lang if lang in knowledge.LANGS else "en"
                pcm.clear()
                if lang == "ur" and C.SONIOX_KEY:
                    stream = providers.SonioxStream(lang, on_partial=on_partial)
                    try:
                        await stream.start()
                    except Exception as exc:
                        await sock.send_json({"type": "error", "message": f"stt: {exc}"})
                        break
            elif evt.get("type") == "text":
                # Typed turn: no capture, no STT — the composer's text enters the
                # very same reply pipeline the mic feeds, so it is spoken (and
                # lip-synced) exactly like a spoken question.
                typed = (evt.get("text") or "").strip()
                if (want := evt.get("lang")) in knowledge.LANGS:
                    lang = want
                if stream is not None:
                    await stream.close()
                    stream = None
                await run_reply(sock, typed, lang, echo_transcript=False)
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
                await run_reply(sock, transcript, lang)
                break
    except WebSocketDisconnect:
        pass
    except Exception as exc:  # pragma: no cover
        try:
            await sock.send_json({"type": "error", "message": str(exc)})
        except Exception:
            pass
    finally:
        if stream is not None:
            await stream.close()
        try:
            await sock.close()
        except Exception:
            pass


# static assets (style.css, app.js, …) served from /web at the site root
app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="static")


if __name__ == "__main__":
    import uvicorn

    host = os.getenv("MARI_HOST", "127.0.0.1")
    port = int(os.getenv("MARI_PORT", "8010"))
    uvicorn.run("server.app:app", host=host, port=port, reload=False)
