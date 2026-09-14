"""Produces the presenter's reply to one visitor message.

Pitch line, demo line or LLM reply, grounded through server/rag.py, sized to the context
window, and passed through the reply fixes. ``respond_sentences`` streams it one
sentence at a time so the first sentence can be spoken before the rest is generated.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import AsyncIterator

from .. import config as C
from .. import rag
from ..providers import llm
from .context_budget import fit_history, fit_system_prompt, history_messages, max_tokens
from .greeting import is_greeting, said_salam
from .replies import canned, pitch_override
from .reply_fixes import force_salam, gender_agreement

logger = logging.getLogger(__name__)

_SENTENCE_END_RE = re.compile(r"[.!?۔؟…]+[\"'”’)]?\s|\n+")


def split_sentences(text: str) -> list[str]:
    out, buf = [], ""
    for ch in text:
        buf += ch
        if ch in ".!?۔؟…\n" and len(buf.strip()) > 1:
            out.append(buf.strip())
            buf = ""
    if buf.strip():
        out.append(buf.strip())
    return out


async def _messages(text: str, lang: str, history: list | None,
                    avatar: str) -> tuple[list[dict], int]:
    system_prompt = await rag.system_prompt(lang, text, history, avatar)
    reply_tokens = max_tokens(lang)
    system_prompt = fit_system_prompt(system_prompt, text, reply_tokens)
    kept = fit_history(system_prompt, text, history_messages(history), reply_tokens)
    messages = [
        {"role": "system", "content": system_prompt},
        *kept,
        {"role": "user", "content": text},
    ]
    return messages, reply_tokens


async def respond(text: str, lang: str, history: list | None = None,
                  avatar: str = "female") -> str:
    """The whole reply in one call. Raises on LLM failure; the caller falls back."""
    messages, reply_tokens = await _messages(text, lang, history, avatar)
    reply = await llm.complete(messages, reply_tokens)
    if is_greeting(text):
        reply = force_salam(reply, lang, returning=said_salam(text))
    return gender_agreement(reply, lang, avatar)


async def respond_sentences(text: str, lang: str, history: list | None = None,
                            avatar: str = "female") -> AsyncIterator[tuple[str, bool]]:
    """Yield (sentence, is_demo) as the reply streams. Never raises for LLM failures."""
    if (pitch := pitch_override(lang, avatar)) is not None:
        for s in split_sentences(pitch):
            yield s, True
        return
    if not C.llm_ready():
        for s in split_sentences(canned("demo", lang, avatar)):
            yield s, True
        return

    messages, reply_tokens = await _messages(text, lang, history, avatar)

    buf = ""
    emitted = False
    needs_salam = is_greeting(text)
    returning = said_salam(text)

    def fix(sentence: str) -> str:
        nonlocal needs_salam
        # Gender agreement on every sentence; the salam only on the first.
        sentence = gender_agreement(sentence, lang, avatar)
        if needs_salam:
            needs_salam = False
            return force_salam(sentence, lang, returning)
        return sentence

    for attempt in range(llm.CONNECT_ATTEMPTS):
        buf = ""
        try:
            async for delta in llm.stream(messages, reply_tokens):
                buf += delta
                while True:
                    m = _SENTENCE_END_RE.search(buf)
                    if not m:
                        break
                    cut = m.end()
                    sent = buf[:cut].strip()
                    buf = buf[cut:]
                    if sent:
                        emitted = True
                        yield fix(sent), False
            if buf.strip():
                yield fix(buf.strip()), False
            return
        except Exception as exc:
            # Nothing said yet: a fresh connection usually lands, so try again.
            if not emitted and not buf.strip() and attempt + 1 < llm.CONNECT_ATTEMPTS:
                logger.warning("LLM stream attempt %d/%d failed, retrying: %s",
                               attempt + 1, llm.CONNECT_ATTEMPTS, exc)
                await asyncio.sleep(llm.RETRY_BACKOFF * (attempt + 1))
                continue
            logger.warning("LLM reply failed after %d attempt(s), falling back to demo line: %s",
                           attempt + 1, exc)
            if buf.strip():
                yield fix(buf.strip()), False
            elif not emitted:
                for s in split_sentences(canned("demo", lang, avatar)):
                    yield s, True
            return
