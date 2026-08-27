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
from . import providers

WEB_DIR = C.WEB_DIR

SYSTEM_PROMPT = {
    "en": (
        "You are MARI, a warm, concise voice assistant. Answer from your own knowledge. "
        "Because your reply will be spoken aloud, keep it natural and brief — usually one "
        "to three sentences, no markdown, no bullet points, no emoji. If asked something "
        "you cannot know, say so briefly."
    ),
    "ur": (
        "آپ ماری ہیں، ایک گرم مزاج اور مختصر بات کرنے والا صوتی معاون۔ اپنے علم سے جواب دیں۔ "
        "چونکہ آپ کا جواب بول کر سنایا جائے گا، اسے فطری اور مختصر رکھیں — عموماً ایک سے تین "
        "جملے، بغیر مارک ڈاؤن، بغیر فہرست، بغیر ایموجی۔ جواب اردو میں دیں۔"
    ),
}

DEMO_REPLY = {
    "en": "I heard you, but the language model isn't reachable from here. Once vLLM is "
    "connected I'll answer from the real model.",
    "ur": "میں نے آپ کی بات سن لی، لیکن لینگویج ماڈل تک رسائی نہیں۔ vLLM جڑنے پر میں اصل ماڈل سے جواب دوں گا۔",
}

app = FastAPI(title="MARI · Voice")


@app.on_event("startup")
async def _warmup() -> None:
    """Preload the local English models in the background so the first English turn
    isn't slowed by model load. No-op if English uses the remote APIs / models absent."""
    import asyncio

    asyncio.create_task(providers.warm("en"))


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")


@app.get("/healthz")
async def healthz() -> dict:
    return {"ok": True, **C.status()}


def _llm_extra() -> dict:
    """Extra request params per provider. vLLM Qwen3.5 is a reasoning model, so we
    disable its chain-of-thought; DeepSeek would reject that param, so send nothing."""
    if C.LLM_PROVIDER == "vllm":
        return {"chat_template_kwargs": {"enable_thinking": False}}
    return {}


async def run_llm(text: str, lang: str) -> str:
    """Ask vLLM Qwen for a spoken-style reply. Raises on failure (caller handles)."""
    payload = {
        "model": C.LLM_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT[lang]},
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
    lang = body.lang if body.lang in SYSTEM_PROMPT else "en"
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
    lang = lang if lang in SYSTEM_PROMPT else "en"
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
#   server → {"stt",text} · then per sentence: {"reply",text} {"tts",mime} <audio> ·
#            finally {"done",spoken}
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
    """Yield MARI's reply one sentence at a time as vLLM streams tokens.
    Falls back to the demo line (also sentence-split) if vLLM is unreachable."""
    if not C.llm_ready():
        for s in _split_sentences(DEMO_REPLY[lang]):
            yield s, True
        return

    payload = {
        "model": C.LLM_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT[lang]},
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


async def run_reply(sock: WebSocket, transcript: str, lang: str) -> None:
    """From the final transcript: stream LLM sentences → TTS each → push audio."""
    await sock.send_json({"type": "stt", "text": transcript, "lang": lang})
    if not transcript:
        await sock.send_json({"type": "done", "spoken": False})
        return
    spoken = False
    async for sentence, is_demo in llm_stream_sentences(transcript, lang):
        await sock.send_json({"type": "reply", "text": sentence, "demo": is_demo})
        if C.tts_ready(lang):
            try:
                audio, mime = await providers.tts(sentence, lang)
                if audio:
                    await sock.send_json({"type": "tts", "mime": mime})
                    await sock.send_bytes(audio)
                    spoken = True
            except Exception as exc:
                await sock.send_json({"type": "warn", "message": f"tts: {exc}"})
    await sock.send_json({"type": "done", "spoken": spoken})


@app.websocket("/ws")
async def ws(sock: WebSocket) -> None:
    """Streaming turn. Client streams raw 16 kHz PCM frames as it captures; for Urdu we
    relay them to Soniox live (partials sent back as captions); English buffers to a WAV
    for Whisper. On {end} we finalize STT and stream the reply."""
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
                lang = lang if lang in SYSTEM_PROMPT else "en"
                pcm.clear()
                if lang == "ur" and C.SONIOX_KEY:
                    stream = providers.SonioxStream(lang, on_partial=on_partial)
                    try:
                        await stream.start()
                    except Exception as exc:
                        await sock.send_json({"type": "error", "message": f"stt: {exc}"})
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
