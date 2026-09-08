"""Conversational query rewriting — resolving elliptical follow-ups before retrieval.

Speech is far more elliptical than typing. A visitor who has just been told about Mari
Minerals asks "and how much do they produce?" — embedded verbatim, that query retrieves
against "they", which matches nothing in particular and everything a little. The right
section is not even in the candidate set, so no amount of reranking recovers it.

Rewriting fixes that by folding the last few turns back into the query. The cost is an
LLM call in the middle of a latency budget that has no room for one, so this module is
built around avoiding it:

  * It is conditional. Rewriting only fires when the query actually looks elliptical —
    a pronoun, a deictic, or too few content words to stand alone. On the eval set that
    is a small minority of questions, and a self-contained question is passed straight
    through with no network call at all.
  * It is timeout-guarded, hard. On timeout the original transcript is used and the turn
    continues. A rewrite is an optimisation; it is never allowed to delay speech.
  * It fails open. Any error — connection, malformed response, empty output — returns
    the original text.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time

import httpx

from .settings import RagSettings, get_settings

log = logging.getLogger(__name__)

# Words that cannot be resolved without the previous turn. English and Urdu, because the
# kiosk takes both and an Urdu follow-up is every bit as elliptical ("اس کا کیا فائدہ؟").
_DEICTIC_RE = re.compile(
    r"\b(it|its|it's|they|them|their|theirs|that|this|those|these|there|he|she|his|her|"
    r"hers|him|the\s+same|above|previous|earlier)\b"
    r"|(?:^|\s)(یہ|وہ|اس|ان|اسی|انہی|اُس|اُن|ویسا|ایسا|مذکورہ)(?=\s|$)",
    re.IGNORECASE,
)

# Stopwords stripped before counting "content words". A four-word question that is three
# stopwords and a noun is not self-contained.
_STOPWORDS = {
    "a", "an", "the", "is", "are", "was", "were", "be", "am", "do", "does", "did",
    "what", "who", "when", "where", "why", "how", "which", "and", "or", "of", "in",
    "on", "at", "to", "for", "with", "about", "me", "you", "i", "please", "tell",
    "کیا", "ہے", "ہیں", "کا", "کی", "کے", "کو", "سے", "میں", "پر", "اور", "بتائیں",
    "بتائیے", "براہ", "کرم", "مجھے", "آپ",
}

_WORD_RE = re.compile(r"[\w؀-ۿ]+", re.UNICODE)

_SYSTEM = (
    "Rewrite the user's latest question into a single self-contained search query. "
    "Resolve every pronoun and reference using the conversation. Keep the original "
    "language and the original wording wherever possible — you are only replacing "
    "references with what they refer to, not rephrasing or answering. Output the "
    "rewritten query alone, with no preamble, quotes or explanation."
)


def needs_rewrite(text: str, has_history: bool, settings: RagSettings) -> bool:
    """Whether this query is worth spending a rewrite call on.

    `has_history` gates everything: the first turn of a conversation has nothing to
    resolve against, and rewriting it can only invent context that was never said.
    """
    if not settings.rewrite_enabled or not has_history or not text.strip():
        return False
    if _DEICTIC_RE.search(text):
        return True
    content = [w for w in _WORD_RE.findall(text.lower()) if w not in _STOPWORDS]
    return len(content) < settings.rewrite_min_content_words


class QueryRewriter:
    def __init__(self, settings: RagSettings | None = None) -> None:
        self.settings = settings or get_settings()

    async def rewrite(
        self,
        text: str,
        history: list[dict] | None,
        *,
        api_base: str,
        api_key: str,
        model: str,
    ) -> tuple[str, bool, float]:
        """Return (query, was_rewritten, elapsed_ms). Never raises."""
        t0 = time.perf_counter()
        history = history or []
        if not needs_rewrite(text, bool(history), self.settings):
            return text, False, (time.perf_counter() - t0) * 1000

        turns = history[-self.settings.rewrite_history_turns * 2 :]
        messages = [{"role": "system", "content": _SYSTEM}]
        messages += [
            {"role": "user" if t.get("role") == "user" else "assistant",
             "content": (t.get("text") or t.get("content") or "")[:500]}
            for t in turns
        ]
        messages.append({"role": "user", "content": text})

        timeout_s = self.settings.rewrite_timeout_ms / 1000
        try:
            rewritten = await asyncio.wait_for(
                self._call(messages, api_base, api_key, model, timeout_s),
                timeout=timeout_s,
            )
        except (asyncio.TimeoutError, Exception) as exc:  # noqa: BLE001
            elapsed = (time.perf_counter() - t0) * 1000
            log.debug("query rewrite skipped after %.0f ms (%s)", elapsed, type(exc).__name__)
            return text, False, elapsed

        elapsed = (time.perf_counter() - t0) * 1000
        # A rewrite that comes back much longer than the question is the model answering
        # rather than rewriting; a rewrite that comes back empty is a malformed response.
        # Both are rejected in favour of the original — the original is never wrong, only
        # under-specified.
        if not rewritten or len(rewritten) > max(200, len(text) * 4):
            return text, False, elapsed
        log.debug("rewrote %r -> %r in %.0f ms", text, rewritten, elapsed)
        return rewritten, True, elapsed

    async def _call(self, messages, api_base: str, api_key: str, model: str,
                    timeout_s: float) -> str:
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout_s, connect=timeout_s)) as c:
            r = await c.post(
                f"{api_base}/chat/completions",
                headers=headers,
                json={
                    "model": self.settings.rewrite_model or model,
                    "messages": messages,
                    # Deterministic and short: this is a mechanical transformation, and
                    # sampling would occasionally produce a differently-worded query for
                    # the same input, making retrieval non-reproducible turn to turn.
                    "temperature": 0.0,
                    "max_tokens": 60,
                    "stream": False,
                },
            )
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"].strip().strip('"')
