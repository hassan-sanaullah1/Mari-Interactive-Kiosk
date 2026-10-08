"""Produces the presenter's reply to one visitor message.

Pitch line, demo line or LLM reply, grounded through server/rag.py, sized to the context
window, and passed through the reply fixes. ``respond_sentences`` streams it one
sentence at a time so the first sentence can be spoken before the rest is generated.
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import AsyncIterator

from .. import rag
from ..providers import llm
from .context_budget import fit_history, fit_system_prompt, history_messages, max_tokens
from .greeting import is_greeting, said_salam
from .policy import failure_reply, fallback_reply
from .reply_fixes import force_salam, gender_agreement
from .script_fixes import latin_terms

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


async def build_messages(text: str, lang: str, history: list | None,
                         avatar: str | None = None) -> tuple[list[dict], int]:
    """The exact message list and reply cap one turn sends to the LLM.

    Public because the answer eval (eval/run_answers.py) grades the real prompt, and
    reaching in for a private name let a rename swap the graded path silently.
    """
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
                  avatar: str | None = None) -> str:
    """The whole reply in one call. Raises on LLM failure; the caller falls back."""
    messages, reply_tokens = await build_messages(text, lang, history, avatar)
    reply = await llm.complete(messages, reply_tokens)
    if is_greeting(text):
        reply = force_salam(reply, lang, returning=said_salam(text))
    return gender_agreement(latin_terms(reply, lang), lang, avatar)


class _SentenceSplitter:
    """Cuts a streaming reply into sentences as the characters arrive.

    Separate from the streaming loop so the text held back mid-sentence stays
    reachable: when the stream fails part-way, that partial sentence is still worth
    speaking, and it is also what decides whether a retry is safe.
    """

    def __init__(self) -> None:
        self._buffer = ""

    def feed(self, delta: str) -> list[str]:
        """Add streamed text; return whatever complete sentences that produced."""
        self._buffer += delta
        complete = []
        while (match := _SENTENCE_END_RE.search(self._buffer)) is not None:
            cut = match.end()
            sentence = self._buffer[:cut].strip()
            self._buffer = self._buffer[cut:]
            if sentence:
                complete.append(sentence)
        return complete

    @property
    def pending(self) -> str:
        """Text received but not yet a whole sentence."""
        return self._buffer.strip()

    def reset(self) -> None:
        self._buffer = ""


class _ReplyFixer:
    """The per-sentence corrections one reply needs, in order.

    Stateful because the salam belongs on the first sentence only — applying it per
    sentence would have the kiosk greet the visitor four times in one answer.
    """

    def __init__(self, lang: str, avatar: str | None, question: str) -> None:
        self._lang = lang
        self._avatar = avatar
        self._needs_salam = is_greeting(question)
        self._returning = said_salam(question)

    def fix(self, sentence: str) -> str:
        sentence = gender_agreement(latin_terms(sentence, self._lang), self._lang, self._avatar)
        if self._needs_salam:
            self._needs_salam = False
            return force_salam(sentence, self._lang, self._returning)
        return sentence


async def respond_sentences(text: str, lang: str, history: list | None = None,
                            avatar: str | None = None) -> AsyncIterator[tuple[str, bool]]:
    """Yield (sentence, is_demo) as the reply streams. Never raises for LLM failures."""
    if (stand_in := fallback_reply(lang, avatar)) is not None:
        for sentence in split_sentences(stand_in.text):
            yield sentence, True
        return

    messages, reply_tokens = await build_messages(text, lang, history, avatar)
    fixer = _ReplyFixer(lang, avatar, text)
    splitter = _SentenceSplitter()
    emitted = False

    for attempt in range(llm.CONNECT_ATTEMPTS):
        splitter.reset()
        try:
            async for delta in llm.stream(messages, reply_tokens):
                for sentence in splitter.feed(delta):
                    emitted = True
                    yield fixer.fix(sentence), False
            if splitter.pending:
                yield fixer.fix(splitter.pending), False
            return
        except Exception as exc:
            # Nothing said yet: a fresh connection usually lands, so try again.
            if not emitted and not splitter.pending and attempt + 1 < llm.CONNECT_ATTEMPTS:
                logger.warning("LLM stream attempt %d/%d failed, retrying: %s",
                               attempt + 1, llm.CONNECT_ATTEMPTS, exc)
                await asyncio.sleep(llm.RETRY_BACKOFF * (attempt + 1))
                continue
            logger.warning("LLM reply failed after %d attempt(s), falling back to demo line: %s",
                           attempt + 1, exc)
            for sentence, is_demo in _salvage(splitter, fixer, emitted, lang, avatar):
                yield sentence, is_demo
            return


def _salvage(splitter: _SentenceSplitter, fixer: _ReplyFixer, emitted: bool,
             lang: str, avatar: str | None) -> list[tuple[str, bool]]:
    """What to say after the stream failed: the partial reply, or the demo line.

    Half an answer is better than an apology, so anything already received is spoken.
    The demo line only stands in when the turn produced nothing at all.
    """
    if splitter.pending:
        return [(fixer.fix(splitter.pending), False)]
    if emitted:
        return []
    failed = failure_reply(lang, avatar)
    return [(sentence, failed.is_demo) for sentence in split_sentences(failed.text)]
