"""Keeps each LLM request inside the served model's context window.

The endpoint (Qwen on vLLM, 8192 tokens) counts system prompt, history, question and
the reserved answer tokens together, and an overflow comes back as an error frame
inside a 200 stream. Urdu is what overflows: Urdu script costs far more tokens per
character than Latin. No tokenizer for the served model is available here, so tokens are
estimated from character counts, per script.
"""

from __future__ import annotations

import logging
import re

from ..services.generation import CONTEXT_HEADER

logger = logging.getLogger(__name__)

LLM_CONTEXT_TOKENS = 8192
# Tokens per character differ by script, and one Urdu prompt holds both: Urdu-script rules
# and replies, and English knowledge, names and terms. A flat per-language ratio had to
# assume the worst script for the whole prompt — 2.2 chars/token for any Urdu turn — and
# over-counted Urdu prompts by ~2,200 tokens on average, which the trim took out of the
# retrieved knowledge (35-65% of it on a Board of Directors question). Measured against the
# served Qwen over 172 real prompts (both languages, both presenters, with and without
# history): Urdu script ~2.0 chars/token, everything else ~4.1. These values are lower so
# the estimate is never under the real count; on that set it was over by 199-1,089 tokens.
LLM_CHARS_PER_TOKEN_URDU = 1.8
LLM_CHARS_PER_TOKEN_LATIN = 3.5
_URDU_SCRIPT = re.compile(r"[\u0600-\u06ff\u0750-\u077f\ufb50-\ufdff\ufe70-\ufeff]")
# Headroom for the chat template's own scaffolding and tokenizer disagreement.
LLM_CONTEXT_SAFETY_TOKENS = 256

# Enough history for "and what about Urdu?" to resolve, not a full transcript.
MAX_HISTORY_TURNS = 8
MAX_HISTORY_CHARS = 400

# Room for the answer. The prompt asks for complete, fact-dense answers (three to five
# sentences, every item of a list), and a reply that reaches this cap is cut mid-sentence,
# which the visitor hears. Urdu costs more tokens per word: a full Urdu overview ran past
# 420. The per-script estimate above leaves room for these without overflowing the window.
_MAX_TOKENS = {"en": 400, "ur": 640}


def max_tokens(lang: str) -> int:
    return _MAX_TOKENS.get(lang, _MAX_TOKENS["en"])


def estimate_tokens(text: str) -> float:
    """A conservative token count for ``text``, priced per script."""
    urdu = len(_URDU_SCRIPT.findall(text))
    return urdu / LLM_CHARS_PER_TOKEN_URDU + (len(text) - urdu) / LLM_CHARS_PER_TOKEN_LATIN


def _budget_tokens(reply_tokens: int) -> int:
    return max(LLM_CONTEXT_TOKENS - reply_tokens - LLM_CONTEXT_SAFETY_TOKENS, 0)


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
    budget = _budget_tokens(reply_tokens)
    fixed = estimate_tokens(system_prompt) + estimate_tokens(question)
    room = budget - fixed
    if room <= 0:
        return []
    kept: list[dict] = []
    used = 0.0
    # Newest first: an elliptical follow-up needs the most recent exchange.
    for msg in reversed(history):
        cost = estimate_tokens(msg.get("content", "")) + 4  # + role/framing overhead
        if used + cost > room:
            break
        kept.append(msg)
        used += cost
    kept.reverse()
    if len(kept) < len(history):
        logger.info(
            "history trimmed to fit context: %d/%d messages, ~%d of %d tokens",
            len(kept), len(history), fixed + used, budget,
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
    room = _budget_tokens(reply_tokens) - estimate_tokens(question)
    total = estimate_tokens(system_prompt)
    if total <= room:
        return system_prompt

    found = system_prompt.find(CONTEXT_HEADER)
    if found == -1:
        logger.warning(
            "system prompt is ~%d tokens against a %d budget and has no retrieved "
            "context to trim", total, room,
        )
        return system_prompt

    cut = found + len(CONTEXT_HEADER)
    used = estimate_tokens(system_prompt[:cut])
    end = cut
    for ch in system_prompt[cut:]:
        cost = 1 / (LLM_CHARS_PER_TOKEN_URDU if _URDU_SCRIPT.match(ch) else LLM_CHARS_PER_TOKEN_LATIN)
        if used + cost > room:
            break
        used += cost
        end += 1
    trimmed = system_prompt[:end].rstrip()
    logger.info(
        "retrieved context trimmed to fit: prompt ~%d -> ~%d tokens (budget %d)",
        total, estimate_tokens(trimmed), room,
    )
    return trimmed
