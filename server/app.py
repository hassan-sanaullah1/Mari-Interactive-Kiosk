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
import logging
import os
import re

import httpx
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import config as C

try:  # voice_config is optional — without it the model's own opener is used as-is
    from voice_config import (
        force_salam as _force_salam,
        gender_agreement as _gender_agreement,
    )
except ImportError:  # pragma: no cover - only hit if the folder is removed
    def _force_salam(reply: str, lang: str = "ur") -> str:
        return reply

    def _gender_agreement(reply: str, lang: str = "ur", avatar: str = "female") -> str:
        return reply

from . import knowledge
from . import providers
from . import avatar
from . import rag

logger = logging.getLogger(__name__)

WEB_DIR = C.WEB_DIR

# The canned lines below are spoken by whichever presenter is on screen, so in Urdu —
# where the verb carries the speaker's gender — each one needs both forms. English is
# ungendered here, so both personas share the one string.
#
# These bypass the LLM entirely, which is exactly why they are keyed by persona rather
# than left to voice_config.gender_agreement: that pass only rewrites a self-description
# clause ("میں ... کا نمائندہ ہوں"), and these are plain first-person sentences that
# would sail straight through it in the feminine.
_DEMO_UR = (
    "میں نے آپ کی بات سن لی، لیکن لینگویج ماڈل تک رسائی نہیں، اس لیے ابھی Mari Energies کی "
    "معلومات سے جواب نہیں دے {v}۔ یہی تفصیل marienergies.com.pk پر موجود ہے۔"
)

DEMO_REPLY = {
    "female": {
        "en": "I heard you, but the language model isn't reachable from here, so I can't answer "
        "from the Mari Energies knowledge base right now. You'll find the same information at "
        "marienergies.com.pk.",
        "ur": _DEMO_UR.format(v="سکتی"),
    },
    "male": {
        "en": "I heard you, but the language model isn't reachable from here, so I can't answer "
        "from the Mari Energies knowledge base right now. You'll find the same information at "
        "marienergies.com.pk.",
        "ur": _DEMO_UR.format(v="سکتا"),
    },
}

# Spoken when STT comes back with nothing — a turn that caught only silence, or a
# tail that never finalized. Before this the socket answered {done, spoken:false}
# and the kiosk simply went quiet, which to a visitor standing in front of it is
# indistinguishable from a crash; they have no way to tell they should try again.
# Short on purpose: it is heard after a failed attempt, not read.
NO_SPEECH_REPLY = {
    "female": {
        "en": "Sorry, I didn't catch that. Could you say it again?",
        "ur": "معاف کیجیے، میں سن نہیں سکی۔ ذرا دوبارہ کہیے گا؟",
    },
    "male": {
        "en": "Sorry, I didn't catch that. Could you say it again?",
        "ur": "معاف کیجیے، میں سن نہیں سکا۔ ذرا دوبارہ کہیے گا؟",
    },
}

# The presenters the browser may ask for, mirroring AvatarId in
# frontend/components/avatar/models.ts. Anything else on the wire is ignored and
# the turn falls back to the default rig rather than reaching the TTS layer with
# an id it has no voice for.
AVATARS = frozenset({"female", "male"})

# ── DEMO PITCH — temporary, for a recording ─────────────────────────
# While MARI_PITCH_ONLY=1, every Urdu turn on the female rig answers with this one
# fixed line, whatever the visitor said, and without calling the LLM at all. It is a
# recording aid, NOT a product behaviour: the kiosk stops answering questions while
# it is on. Unset the env var (or set it to 0) to hand Urdu back to the model.
#
# Deliberately checked at request time rather than at import, so the flag can be
# flipped without a code change; the server still needs a restart to re-read .env.
PITCH_ONLY_UR = (
    "Assalamualaikum میں Maryam ہوں، اور میں Mari Energies کی ایک representative ہوں۔ "
    "Sky47، جو Mari Energies کا Data Center اور AI کلاؤڈ Infrastructure Vertical ہے، "
    "پاکستان کا سب سے بڑا کلاؤڈ AI Farm چلاتا ہے۔ یہ Huawei Ascend NPU اور NVIDIA GPU "
    "clusters کی مدد سے GPU-as-a-Service فراہم کرتا ہے۔ اس میں liquid-cooled racks "
    "استعمال ہوتے ہیں جو فی rack پچاس Kilo Watts تک handle کر سکتے ہیں۔"
)


def _pitch_override(lang: str, avatar_id: str) -> str | None:
    """The fixed pitch line when MARI_PITCH_ONLY is on, else None.

    Scoped to Urdu on the female rig only — the language and presenter being recorded —
    so an English turn or the male rig still behaves normally if one gets used by mistake.
    """
    if C.ENV.get("MARI_PITCH_ONLY", "0") not in ("1", "true", "yes", "on"):
        return None
    if lang == "ur" and avatar_id == "female":
        return PITCH_ONLY_UR
    return None


def _canned(table: dict, lang: str, avatar_id: str = "female") -> str:
    """Pick a canned line for the presenter on screen and the turn's language.

    Both keys degrade to the default female presenter / English rather than raising,
    so an unexpected avatar id or language still gets a spoken line out of the kiosk.
    """
    persona = table.get(avatar_id) or table["female"]
    return persona.get(lang) or persona["en"]

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
    # Retrieval layer: model load and corpus ingest. Backgrounded because a cold
    # container spends minutes downloading ONNX weights, and until it is ready turns are
    # answered from the core brief alone rather than being refused — the kiosk speaks
    # from the moment it boots, and says what it does not yet know.
    asyncio.create_task(rag.startup())


@app.on_event("shutdown")
async def _shutdown() -> None:
    await rag.shutdown()


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")


@app.get("/healthz")
async def healthz() -> dict:
    return {
        "ok": True,
        **await C.status(),
        "rag": await rag.health(),
    }


# How much of the conversation rides along with a turn. The kiosk is a walk-up
# device on a latency budget, so this stays small: enough for "and what about
# Urdu?" to resolve against the previous answer, not a full transcript.
# Reaching the LLM. The hosted endpoint sits behind a CDN edge that, from some
# networks, accepts the TCP connection and then never answers — so a turn can die
# on the dial while the service itself is perfectly healthy. A retry on a fresh
# connection almost always lands, and costs only the connect timeout, so a visitor
# gets a real answer instead of the demo line.
LLM_CONNECT_ATTEMPTS = 3
LLM_RETRY_BACKOFF = 0.4  # seconds, multiplied by the attempt number
LLM_STREAM_TIMEOUT = httpx.Timeout(connect=4, read=12, write=8, pool=4)

MAX_HISTORY_TURNS = 8
MAX_HISTORY_CHARS = 400

# The served model's context window, and what we keep free inside it.
#
# The endpoint is Qwen behind vLLM with an 8192-token window, and it counts the
# WHOLE request: system prompt + retrieved context + history + question + the
# max_tokens reserved for the answer. Overflow is not a normal HTTP error — the
# stream opens 200 OK and carries one {"error"} frame instead of content, which
# is why this failed as total silence rather than as an error (see the error
# frame check in llm_stream_sentences).
#
# Urdu is what pushes it over. The same reply is far more tokens in Urdu script
# than in Latin — roughly one token per 1.5-2 characters against 3-4 for English —
# so an English turn fits comfortably while the Urdu turn built from the same
# prompt and the same retrieved sections does not.
#
# Budget in characters rather than tokens on purpose: a real tokenizer for the
# served model is not available in this process, and a character bound is cheap.
# Trimming the oldest history first keeps the current question and its retrieved
# context intact, which is what the answer is actually built from.
LLM_CONTEXT_TOKENS = 8192
# Measured against the served model rather than guessed. The same Urdu prompt was
# counted twice, and the two counts are why this is deliberately conservative:
# 14,831 characters came back as 5,863 prompt_tokens through the plain endpoint
# (2.53 chars/token) but as 7,773 input_tokens through the streaming path that
# the kiosk actually uses (1.91) — the chat template's own scaffolding, and the
# reasoning-model parameters, are counted there too.
#
# 1.75 sits below the worst of those, because the two errors are not symmetric:
# overflow costs the visitor the entire turn and used to do it silently, while
# an over-tight estimate costs one old exchange of history nobody will miss.
LLM_CHARS_PER_TOKEN = 1.75
# Headroom for the chat template's own scaffolding and tokenizer disagreement.
LLM_CONTEXT_SAFETY_TOKENS = 256


def _fit_history(system_prompt: str, question: str, history: list[dict],
                 reply_tokens: int) -> list[dict]:
    """Drop the oldest history messages until the request fits the context window.

    Returns the messages that fit, oldest-first order preserved. The system prompt
    and the question are never trimmed here: if those alone overflow, there is no
    history left to drop and the request goes out as-is, so the upstream error
    surfaces as an error rather than being hidden by a silently truncated prompt.
    """
    budget_tokens = LLM_CONTEXT_TOKENS - reply_tokens - LLM_CONTEXT_SAFETY_TOKENS
    budget_chars = int(max(budget_tokens, 0) * LLM_CHARS_PER_TOKEN)
    fixed = len(system_prompt) + len(question)
    room = budget_chars - fixed
    if room <= 0:
        return []
    kept: list[dict] = []
    used = 0
    # Newest first: the most recent exchange is the one an elliptical follow-up
    # ("and what about that one?") actually needs.
    for msg in reversed(history):
        cost = len(msg.get("content", "")) + 8  # + role/framing overhead
        if used + cost > room:
            break
        kept.append(msg)
        used += cost
    kept.reverse()
    if len(kept) < len(history):
        logger.info(
            "history trimmed to fit context: %d/%d messages, ~%d of %d chars",
            len(kept), len(history), fixed + used, budget_chars,
        )
    return kept


# The marker the prompt assembler puts in front of the retrieved sections; see
# services/generation.py build_prompt. Everything from here to the end of the
# prompt is retrieved knowledge, which is the only part safe to shorten: the
# persona, the core brief and the glossary all sit above it, deliberately, so
# that truncation never costs the kiosk its identity or its abbreviations.
_CONTEXT_MARKERS = (
    "MARI ENERGIES KNOWLEDGE — sections relevant to this question:",
)


def _fit_system_prompt(system_prompt: str, question: str, reply_tokens: int) -> str:
    """Trim retrieved sections until the prompt itself fits the context window.

    Trimming history is not enough on its own. The Urdu prompt overflowed with an
    EMPTY history — 7,773 input tokens plus 420 reserved for the answer against an
    8,192 window, over by a single token — because the Urdu base rules alone are
    ~11.7k characters and retrieval adds ~3.8k more on top.

    The alternative, asking for a shorter answer, is worse: it cuts the reply
    mid-sentence, which the visitor hears. Dropping the tail of the retrieved
    context costs at most the least-relevant section (they arrive ranked, best
    first) and usually costs nothing the answer needed.
    """
    budget_chars = int(
        max(LLM_CONTEXT_TOKENS - reply_tokens - LLM_CONTEXT_SAFETY_TOKENS, 0)
        * LLM_CHARS_PER_TOKEN
    )
    room = budget_chars - len(question)
    if len(system_prompt) <= room:
        return system_prompt

    cut = -1
    for marker in _CONTEXT_MARKERS:
        found = system_prompt.find(marker)
        if found != -1:
            cut = found + len(marker)
            break
    if cut == -1:
        # No retrieved section to drop — everything present is persona and core
        # brief, which must not be cut. Send it and let the error surface.
        logger.warning(
            "system prompt is %d chars against a %d budget and has no retrieved "
            "context to trim", len(system_prompt), room,
        )
        return system_prompt

    keep = max(room - cut, 0)
    trimmed = system_prompt[:cut + keep].rstrip()
    logger.info(
        "retrieved context trimmed to fit: prompt %d -> %d chars (budget %d)",
        len(system_prompt), len(trimmed), room,
    )
    return trimmed


def _history_messages(history) -> list[dict]:
    """Normalise the client's conversation history into OpenAI chat messages.

    History is whatever the browser is holding for this visitor — it lives in the
    tab and dies with a reload, deliberately: a kiosk should greet the next person
    fresh. So it is untrusted input; only user/assistant text survives, trimmed and
    capped, and anything malformed is dropped rather than rejected."""
    if not isinstance(history, list):
        return []
    out: list[dict] = []
    for item in history[-MAX_HISTORY_TURNS:]:
        if not isinstance(item, dict):
            continue
        role = item.get("role")
        text = item.get("text") or item.get("content") or ""
        if role not in ("user", "assistant") or not isinstance(text, str):
            continue
        text = text.strip()[:MAX_HISTORY_CHARS]
        if text:
            out.append({"role": role, "content": text})
    return out


# Urdu costs far more tokens than English for the same sentence: the script is outside
# the tokenizer's Latin-heavy vocabulary, so a reply of the length the prompt asks for
# (one to three spoken sentences) ran past a flat 220 and was cut mid-word — the visitor
# heard the avatar stop in the middle of a clause. The prompt, not the cap, is what
# keeps replies short; this budget only has to be generous enough not to truncate one.
_MAX_TOKENS = {"en": 220, "ur": 420}


def _max_tokens(lang: str) -> int:
    return _MAX_TOKENS.get(lang, _MAX_TOKENS["en"])


def _llm_extra() -> dict:
    """Extra request params per provider. vLLM Qwen3.5 is a reasoning model, so we
    disable its chain-of-thought; DeepSeek would reject that param, so send nothing."""
    if C.LLM_PROVIDER == "vllm":
        return {"chat_template_kwargs": {"enable_thinking": False}}
    return {}


async def run_llm(text: str, lang: str, history: list | None = None,
                  avatar_id: str = "female") -> str:
    """Ask the LLM for a spoken-style reply, grounded in the Mari Energies knowledge base.

    ``avatar_id`` picks the persona — Maryam for the female rig, Hamza for the male one —
    which decides the name in the introduction and, in Urdu, the gender agreement.
    Raises on failure (caller handles)."""
    system_prompt = await rag.system_prompt(lang, text, history, avatar_id)
    reply_tokens = _max_tokens(lang)
    # Trim the oldest history until the whole request fits the served context
    # window; overflow comes back as a 200 stream carrying an error frame, not as
    # an HTTP error. See _fit_history.
    system_prompt = _fit_system_prompt(system_prompt, text, reply_tokens)
    messages = _fit_history(system_prompt, text, _history_messages(history), reply_tokens)
    payload = {
        "model": C.LLM_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            *messages,
            {"role": "user", "content": text},
        ],
        "temperature": 0.7,
        "max_tokens": reply_tokens,
        "stream": False,
        **_llm_extra(),
    }
    headers = {"Content-Type": "application/json"}
    if C.LLM_KEY:
        headers["Authorization"] = f"Bearer {C.LLM_KEY}"
    last: Exception | None = None
    for attempt in range(LLM_CONNECT_ATTEMPTS):
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(60, connect=5)) as client:
                r = await client.post(
                    f"{C.LLM_BASE}/chat/completions", headers=headers, json=payload
                )
                r.raise_for_status()
                reply = r.json()["choices"][0]["message"]["content"].strip()
                # The Urdu prompt asks a greeting reply to open with "السلام علیکم";
                # Qwen complies only about two thirds of the time (DeepSeek always did),
                # so on a turn the server has already identified as a greeting the
                # opener is normalised here rather than left to the model.
                if knowledge.is_greeting(text):
                    reply = _force_salam(reply, lang)
                # Urdu marks gender on the verb and the possessive, and Qwen slips on
                # both — writing "Mari Energies کا نمائندہ" for the female presenter and
                # feminine verb endings for the male one. Which way to correct depends on
                # who is on screen.
                return _gender_agreement(reply, lang, avatar_id)
        except (httpx.TransportError, httpx.HTTPStatusError) as exc:
            # Retry a dropped/hung dial (see LLM_CONNECT_ATTEMPTS); a 4xx is the
            # server's considered answer, so don't hammer it.
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if status is not None and status < 500:
                raise
            last = exc
            if attempt + 1 < LLM_CONNECT_ATTEMPTS:
                await asyncio.sleep(LLM_RETRY_BACKOFF * (attempt + 1))
    raise last  # type: ignore[misc]


class ChatIn(BaseModel):
    text: str
    lang: str = "en"
    # Prior turns of this visitor's conversation, oldest first, as
    # [{"role":"user"|"assistant","text":...}]. Client-held and short-lived.
    history: list[dict] | None = None
    # Which presenter is on screen, mirroring AvatarId in the frontend. Picks the
    # persona; anything not in AVATARS falls back to the default rig.
    avatar: str = "female"


@app.post("/chat")
async def chat(body: ChatIn) -> dict:
    text = (body.text or "").strip()
    lang = body.lang if body.lang in knowledge.LANGS else "en"
    avatar_id = body.avatar if body.avatar in AVATARS else "female"
    if not text:
        return {"reply": "", "demo": not C.llm_ready()}
    if (pitch := _pitch_override(lang, avatar_id)) is not None:
        return {"reply": pitch, "demo": False}
    if not C.llm_ready():
        return {"reply": _canned(DEMO_REPLY, lang, avatar_id), "demo": True}
    try:
        return {"reply": await run_llm(text, lang, body.history, avatar_id), "demo": False}
    except Exception as exc:
        logger.warning("/chat: LLM call failed, falling back to demo line: %s", exc)
        return {"reply": _canned(DEMO_REPLY, lang, avatar_id), "demo": True, "error": str(exc)}


@app.post("/voice")
async def voice(request: Request, lang: str = "en", avatar: str = "female") -> dict:
    """Full turn: audio → STT → LLM → TTS. Returns transcript, reply, and reply audio."""
    lang = lang if lang in knowledge.LANGS else "en"
    avatar_id = avatar if avatar in AVATARS else "female"
    wav = await request.body()
    out: dict = {"lang": lang, "transcript": "", "reply": "", "audio": None, "mime": None}

    # 1) speech-to-text
    try:
        out["transcript"] = await providers.stt(wav, lang)
        rag.prestart(out["transcript"])
    except Exception as exc:
        out["error"] = f"stt: {exc}"
        return out
    if not out["transcript"]:
        out["error"] = "no-speech"
        return out

    # 2) LLM reply (falls back to a spoken demo line if vLLM is unreachable)
    if (pitch := _pitch_override(lang, avatar_id)) is not None:
        out["reply"] = pitch
    elif C.llm_ready():
        try:
            # single-shot: no history
            out["reply"] = await run_llm(out["transcript"], lang, None, avatar_id)
        except Exception as exc:
            logger.warning("/voice: LLM call failed, falling back to demo line: %s", exc)
            out["reply"] = _canned(DEMO_REPLY, lang, avatar_id)
            out["error"] = f"llm: {exc}"
    else:
        out["reply"] = _canned(DEMO_REPLY, lang, avatar_id)
        out["demo"] = True

    # 3) text-to-speech (optional — browser speaks the text if this is empty)
    if out["reply"] and C.tts_ready(lang):
        try:
            audio, mime = await providers.tts(out["reply"], lang, avatar_id)
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


async def llm_stream_sentences(text: str, lang: str, history: list | None = None,
                               avatar_id: str = "female"):
    """Yield the presenter's reply — grounded in the Mari Energies knowledge base — one
    sentence at a time as the LLM streams tokens.

    ``avatar_id`` picks the persona (Maryam or Hamza), which decides both the prompt and
    which way the Urdu gender agreement below is corrected.
    Falls back to the demo line (also sentence-split) if vLLM is unreachable."""
    if (pitch := _pitch_override(lang, avatar_id)) is not None:
        for s in _split_sentences(pitch):
            yield s, True
        return
    if not C.llm_ready():
        for s in _split_sentences(_canned(DEMO_REPLY, lang, avatar_id)):
            yield s, True
        return

    system_prompt = await rag.system_prompt(lang, text, history, avatar_id)
    reply_tokens = _max_tokens(lang)
    # Trim the oldest history until the whole request fits the served context
    # window; overflow comes back as a 200 stream carrying an error frame, not as
    # an HTTP error. See _fit_history.
    system_prompt = _fit_system_prompt(system_prompt, text, reply_tokens)
    messages = _fit_history(system_prompt, text, _history_messages(history), reply_tokens)
    payload = {
        "model": C.LLM_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            *messages,
            {"role": "user", "content": text},
        ],
        "temperature": 0.7,
        "max_tokens": reply_tokens,
        "stream": True,
        **_llm_extra(),
    }
    headers = {"Content-Type": "application/json"}
    if C.LLM_KEY:
        headers["Authorization"] = f"Bearer {C.LLM_KEY}"

    buf = ""
    emitted = False
    # Only the FIRST sentence of a greeting turn carries the opener; normalising every
    # sentence would sprinkle a salam through the whole reply.
    needs_salam = knowledge.is_greeting(text)

    def _open(sentence: str) -> str:
        nonlocal needs_salam
        # Gender agreement applies to EVERY sentence — a self-description can appear
        # anywhere in the reply — but the salam only to the first.
        sentence = _gender_agreement(sentence, lang, avatar_id)
        if needs_salam:
            needs_salam = False
            return _force_salam(sentence, lang)
        return sentence

    for attempt in range(LLM_CONNECT_ATTEMPTS):
        buf = ""
        try:
            # read timeout applies between streamed chunks, so a real reply is fine; a dead
            # vLLM (half-open tunnel) fails at ~12s instead of hanging the whole turn.
            async with httpx.AsyncClient(timeout=LLM_STREAM_TIMEOUT) as client:
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
                            frame = json.loads(data)
                        except Exception:
                            continue
                        # An upstream failure arrives INSIDE a 200 stream, as one
                        # SSE frame carrying {"error": ...} and then [DONE]. It has
                        # no "choices", so the old parse simply skipped it and the
                        # generator ended having yielded nothing at all — the turn
                        # went silent with no error anywhere, which is what made a
                        # context-length overflow look exactly like a dead mic.
                        # Raise instead, so the retry/demo path below can see it.
                        if isinstance(frame, dict) and frame.get("error"):
                            err = frame["error"]
                            msg = err.get("message") if isinstance(err, dict) else str(err)
                            raise RuntimeError(f"llm upstream: {msg}")
                        try:
                            delta = frame["choices"][0]["delta"].get("content", "")
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
                                yield _open(sent), False
            if buf.strip():
                yield _open(buf.strip()), False
            return
        except Exception as exc:
            # Nothing spoken yet and the failure was in *reaching* the LLM: the
            # upstream path drops a sizeable share of connections outright, and a
            # fresh connection usually lands, so try again rather than sending the
            # visitor to the demo line over one unlucky dial.
            if not emitted and not buf.strip() and attempt + 1 < LLM_CONNECT_ATTEMPTS:
                logger.warning("LLM stream attempt %d/%d failed, retrying: %s", attempt + 1, LLM_CONNECT_ATTEMPTS, exc)
                await asyncio.sleep(LLM_RETRY_BACKOFF * (attempt + 1))
                continue
            # Mid-stream failure (or out of attempts) — speak what we have, else demo.
            # This is the path that made a real outage look identical to a normal
            # demo reply to anyone watching the UI — log it so it shows up in
            # `docker compose logs backend` instead of vanishing silently.
            logger.warning("LLM reply failed after %d attempt(s), falling back to demo line: %s", attempt + 1, exc)
            if buf.strip():
                yield _open(buf.strip()), False
            elif not emitted:
                for s in _split_sentences(_canned(DEMO_REPLY, lang, avatar_id)):
                    yield s, True
            return


_turn_seq = 0


async def run_reply(
    sock: WebSocket,
    transcript: str,
    lang: str,
    echo_transcript: bool = True,
    history: list | None = None,
    avatar_id: str = "female",
    spoke: bool = True,
) -> None:
    """From the final transcript: stream LLM sentences → TTS each → push audio.

    ``transcript`` is whatever the user said — or, for a typed turn, whatever they
    typed; the two are identical from here on. ``echo_transcript`` is False for the
    typed path, where the browser already has the text on screen and doesn't need
    it read back.

    ``avatar_id`` is which presenter is on screen, and picks the voice — see
    providers.get_tts_provider. It is fixed for the whole turn: the browser sends
    the rig that was showing when the turn started, so a visitor who switches
    presenters mid-reply hears the rest of that reply in the voice it began in
    rather than changing voice between two sentences.

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
            # Two very different turns arrive here, and only one of them wants an
            # answer. ``spoke`` is the browser's VAD telling us which: False means
            # the hands-free loop re-opened the mic and nobody said anything for
            # eight seconds, so the turn closes in silence, exactly as it did
            # before this branch existed. Answering that case made the kiosk speak
            # into an empty room, which re-opened the mic, which timed out again.
            if not spoke:
                await send_json({"type": "done", "spoken": False})
                return
            # They did speak and the transcript was lost. Say so out loud rather
            # than going silent; see NO_SPEECH_REPLY. The line is spoken through
            # the same TTS path as a real reply, so it is lip-synced like one, and
            # is tagged demo so the browser can style it apart from something the
            # model actually said.
            line = _canned(NO_SPEECH_REPLY, lang, avatar_id)
            await send_json({"type": "reply", "text": line, "demo": True})
            spoken = False
            if C.tts_ready(lang):
                clip = lips.open_clip() if lips is not None else None
                try:
                    audio, mime = await providers.tts(line, lang, avatar_id)
                    if audio:
                        header = {"type": "tts", "mime": mime}
                        if clip is not None:
                            header["clip"] = clip
                        await send_audio(header, audio)
                        spoken = True
                        if clip is not None:
                            lips.feed(clip, audio, mime)
                    elif clip is not None:
                        lips.cancel(clip)
                except Exception as exc:
                    if clip is not None:
                        lips.cancel(clip)
                    await send_json({"type": "warn", "message": f"tts: {exc}"})
            await send_json({"type": "done", "spoken": spoken})
            if lips is not None:
                await lips.drain()
            return
        spoken = False
        async for sentence, is_demo in llm_stream_sentences(
            transcript, lang, history, avatar_id
        ):
            await send_json({"type": "reply", "text": sentence, "demo": is_demo})
            if C.tts_ready(lang):
                # Open (and start priming) this sentence's A2F clip before
                # synthesis, so the stream is warm by the time audio exists.
                clip = lips.open_clip() if lips is not None else None
                try:
                    audio, mime = await providers.tts(sentence, lang, avatar_id)
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
    # Which presenter is on screen, as the browser reported it on {start}/{text}.
    # Picks the reply voice; see run_reply. Defaults to the female rig, which is
    # the kiosk's own default presenter (frontend DEFAULT_AVATAR).
    avatar_id = "female"
    pcm = bytearray()
    stream: providers.SonioxStream | None = None
    # Conversation so far, as the browser remembers it. The socket is per turn, so
    # each turn brings its own copy; nothing about the visitor is kept server-side.
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
                # Typed turn: no capture, no STT — the composer's text enters the
                # very same reply pipeline the mic feeds, so it is spoken (and
                # lip-synced) exactly like a spoken question.
                typed = (evt.get("text") or "").strip()
                if (want := evt.get("lang")) in knowledge.LANGS:
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
                # Start embedding the transcript the instant STT finalises it, before
                # run_reply does anything else. Retrieval then claims the finished
                # vector instead of waiting on the model, which takes 30-40 ms off the
                # gap between the visitor finishing their sentence and the first audio
                # coming back — the part of the turn they actually feel.
                rag.prestart(transcript)
                # Default True: an older browser that sends a bare {"end"} keeps
                # the apology it used to get rather than falling silent.
                await run_reply(
                    sock, transcript, lang, history=history, avatar_id=avatar_id,
                    spoke=bool(evt.get("spoke", True)),
                )
                break
    except WebSocketDisconnect:
        pass
    except Exception as exc:  # pragma: no cover
        # Log before answering. Without this the turn died silently: the browser
        # got {"error"} with a str(exc) that is often empty, and the traceback —
        # the only thing that says WHERE it broke — was dropped on the floor.
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


# static assets (style.css, app.js, …) served from /web at the site root
app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="static")


if __name__ == "__main__":
    import uvicorn

    host = os.getenv("MARI_HOST", "127.0.0.1")
    port = int(os.getenv("MARI_PORT", "8010"))
    uvicorn.run("server.app:app", host=host, port=port, reload=False)
