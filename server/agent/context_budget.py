"""Keeps each LLM request inside the served model's context window.

The endpoint (Qwen on vLLM, 8192 tokens) counts system prompt, history, question and
the reserved answer tokens together, and an overflow comes back as an error frame
inside a 200 stream. Urdu is what overflows: Urdu script costs far more tokens per
character than Latin. The budget is in characters because no tokenizer for the served
model is available here.
"""

from __future__ import annotations

import logging

from ..services.generation import CONTEXT_HEADER

logger = logging.getLogger(__name__)

LLM_CONTEXT_TOKENS = 8192
# Urdu. Overflow costs the whole turn, but an over-tight estimate is not free either:
# the trim cuts retrieved knowledge, not history, and at the old 1.75 the female Urdu
# prompt kept only 23-39% of its knowledge. Re-measured with stream usage, full Urdu
# prompts plus an 8-message history came to 2.49-2.81 chars/token.
LLM_CHARS_PER_TOKEN = 2.2
# English packs far more characters into a token. Under the Urdu ratio the trim cut
# 91-98% of the retrieved knowledge off every English turn and the model answered from
# the brief alone. A full English prompt measured 3.99 chars/token; 3.0 keeps a margin.
LLM_CHARS_PER_TOKEN_EN = 3.0
# Headroom for the chat template's own scaffolding and tokenizer disagreement.
LLM_CONTEXT_SAFETY_TOKENS = 256

# Enough history for "and what about Urdu?" to resolve, not a full transcript.
MAX_HISTORY_TURNS = 8
MAX_HISTORY_CHARS = 400

# Urdu replies of the length the prompt asks for ran past 220 tokens and were cut
# mid-word. English was raised from 220 for the same reason: a broad overview answer
# names each part of the topic. The prompt keeps replies short; this only has to avoid
# truncating one.
_MAX_TOKENS = {"en": 320, "ur": 420}


def max_tokens(lang: str) -> int:
    return _MAX_TOKENS.get(lang, _MAX_TOKENS["en"])


def _chars_per_token(lang: str) -> float:
    """The conservative ratio for this turn's language; Urdu's is the default."""
    return LLM_CHARS_PER_TOKEN_EN if lang == "en" else LLM_CHARS_PER_TOKEN


def _budget_chars(reply_tokens: int, lang: str = "ur") -> int:
    return int(max(LLM_CONTEXT_TOKENS - reply_tokens - LLM_CONTEXT_SAFETY_TOKENS, 0)
               * _chars_per_token(lang))


def history_messages(history) -> list[dict]:
    """The browser's conversation history as chat messages.

    History lives in the browser tab and is untrusted: only user/assistant text
    survives, trimmed and capped, and anything malformed is dropped.
    """
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


def fit_history(system_prompt: str, question: str, history: list[dict],
                reply_tokens: int, lang: str = "ur") -> list[dict]:
    """Drop the oldest history messages until the request fits.

    The system prompt and question are never trimmed here. If they alone overflow,
    nothing is kept and the upstream error surfaces rather than being hidden.
    """
    budget_chars = _budget_chars(reply_tokens, lang)
    fixed = len(system_prompt) + len(question)
    room = budget_chars - fixed
    if room <= 0:
        return []
    kept: list[dict] = []
    used = 0
    # Newest first: an elliptical follow-up needs the most recent exchange.
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


def fit_system_prompt(system_prompt: str, question: str, reply_tokens: int,
                      lang: str = "ur") -> str:
    """Trim the tail of the retrieved context until the prompt itself fits.

    The Urdu prompt can overflow with no history at all. Retrieved sections arrive
    best-first, so cutting the tail costs the least relevant one; shortening the answer
    instead would cut the reply mid-sentence. Persona and core brief sit above
    CONTEXT_HEADER and are never cut.
    """
    room = _budget_chars(reply_tokens, lang) - len(question)
    if len(system_prompt) <= room:
        return system_prompt

    found = system_prompt.find(CONTEXT_HEADER)
    if found == -1:
        logger.warning(
            "system prompt is %d chars against a %d budget and has no retrieved "
            "context to trim", len(system_prompt), room,
        )
        return system_prompt

    cut = found + len(CONTEXT_HEADER)
    keep = max(room - cut, 0)
    trimmed = system_prompt[:cut + keep].rstrip()
    logger.info(
        "retrieved context trimmed to fit: prompt %d -> %d chars (budget %d)",
        len(system_prompt), len(trimmed), room,
    )
    return trimmed
