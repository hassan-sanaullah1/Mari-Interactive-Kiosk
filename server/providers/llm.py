"""OpenAI-compatible chat-completions client for the configured LLM (vLLM Qwen or DeepSeek)."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import NamedTuple

import httpx

from .. import config

# The hosted endpoint's CDN edge sometimes accepts the TCP connection and never answers.
# A fresh connection almost always lands, so a failed dial is retried.
CONNECT_ATTEMPTS = 3
RETRY_BACKOFF = 0.4  # seconds, multiplied by the attempt number

# The read timeout applies between streamed chunks, so a half-open tunnel fails at ~12s
# instead of hanging the turn.
STREAM_TIMEOUT = httpx.Timeout(connect=4, read=12, write=8, pool=4)
COMPLETE_TIMEOUT = httpx.Timeout(60, connect=5)


def _extra_params() -> dict:
    # Qwen3.5 on vLLM is a reasoning model; DeepSeek rejects this parameter.
    if config.LLM_PROVIDER == "vllm":
        return {"chat_template_kwargs": {"enable_thinking": False}}
    return {}


def _headers() -> dict:
    headers = {"Content-Type": "application/json"}
    if config.LLM_KEY:
        headers["Authorization"] = f"Bearer {config.LLM_KEY}"
    return headers


def _payload(messages: list[dict], max_tokens: int, stream: bool) -> dict:
    return {
        "model": config.LLM_MODEL,
        "messages": messages,
        "temperature": config.LLM_TEMPERATURE,
        "max_tokens": max_tokens,
        "stream": stream,
        **_extra_params(),
    }


class Completion(NamedTuple):
    """One non-streamed reply, with the accounting the answer eval grades against."""

    text: str
    usage: dict
    finish_reason: str


async def complete_verbose(messages: list[dict], max_tokens: int) -> Completion:
    """``complete()`` plus the usage and finish_reason it discards.

    Separate from ``complete()`` only because almost every caller wants the text and
    nothing else. ``eval/run_answers.py`` needs ``finish_reason`` to tell a reply that
    ran out of tokens from one that simply ended, which is the difference between a
    prompt problem and a cap problem.
    """
    payload = _payload(messages, max_tokens, stream=False)
    last: Exception | None = None
    for attempt in range(CONNECT_ATTEMPTS):
        try:
            async with httpx.AsyncClient(timeout=COMPLETE_TIMEOUT) as client:
                r = await client.post(
                    f"{config.LLM_BASE}/chat/completions", headers=_headers(), json=payload
                )
                r.raise_for_status()
                body = r.json()
            choice = body["choices"][0]
            return Completion(
                text=choice["message"]["content"].strip(),
                usage=body.get("usage") or {},
                finish_reason=choice.get("finish_reason") or "",
            )
        except (httpx.TransportError, httpx.HTTPStatusError) as exc:
            # A 4xx is the server's considered answer, so it is not retried.
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if status is not None and status < 500:
                raise
            last = exc
            if attempt + 1 < CONNECT_ATTEMPTS:
                await asyncio.sleep(RETRY_BACKOFF * (attempt + 1))
    raise last  # type: ignore[misc]


async def complete(messages: list[dict], max_tokens: int) -> str:
    """One non-streamed reply. Retries dropped connections and 5xx; raises otherwise."""
    return (await complete_verbose(messages, max_tokens)).text


async def stream(messages: list[dict], max_tokens: int) -> AsyncIterator[str]:
    """Yield content deltas from one streamed request (no retries; the caller decides).

    An upstream failure such as a context-length overflow arrives inside a 200 stream as
    a single {"error": ...} frame. It is raised, so the turn does not end silently.
    """
    payload = _payload(messages, max_tokens, stream=True)
    async with httpx.AsyncClient(timeout=STREAM_TIMEOUT) as client, client.stream(
        "POST", f"{config.LLM_BASE}/chat/completions", headers=_headers(), json=payload
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
            if isinstance(frame, dict) and frame.get("error"):
                err = frame["error"]
                msg = err.get("message") if isinstance(err, dict) else str(err)
                raise RuntimeError(f"llm upstream: {msg}")
            try:
                delta = frame["choices"][0]["delta"].get("content", "")
            except Exception:
                continue
            if delta:
                yield delta
