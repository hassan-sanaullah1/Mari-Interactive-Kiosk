"""The request has to fit the served model's context window.

The endpoint is Qwen behind vLLM with an 8192-token window, and it counts the whole
request — system prompt, retrieved context, history, question and the tokens reserved
for the answer. Going over does NOT come back as an HTTP error: the stream opens
200 OK and carries a single {"error"} frame instead of content.

That combination produced the kiosk's worst failure mode. The old parser skipped any
frame without "choices", so the generator ended having yielded nothing, run_reply sent
{done, spoken:false}, and the turn went silent with no error logged anywhere — while
STT captions had just shown the visitor their own question on screen.

Urdu is what tipped it over: Urdu script costs far more tokens per character than
Latin, so the same conversation that fit in English did not fit in Urdu.
"""

from __future__ import annotations

from server.agent import context_budget as A
from server.services.generation import CONTEXT_HEADER


def _msgs(n: int, chars: int) -> list[dict]:
    return [{"role": "user" if i % 2 == 0 else "assistant", "content": "x" * chars}
            for i in range(n)]


def test_history_is_trimmed_until_the_request_fits() -> None:
    # Sized against the real budget rather than hard-coded, so this test keeps
    # meaning if the per-script ratios are re-measured: leave room for a few
    # messages, then offer far more than that.
    budget = A.LLM_CONTEXT_TOKENS - 420 - A.LLM_CONTEXT_SAFETY_TOKENS
    system = "s" * int((budget - 800) * A.LLM_CHARS_PER_TOKEN_LATIN)
    history = _msgs(20, 400)       # far more than the ~800 tokens of room left for it
    kept = A.fit_history(system, "q" * 60, history, reply_tokens=420)
    assert len(kept) < len(history)
    used = (A.estimate_tokens(system) + A.estimate_tokens("q" * 60)
            + sum(A.estimate_tokens(m["content"]) + 4 for m in kept))
    assert used <= budget


def test_the_newest_exchange_is_the_one_kept() -> None:
    """An elliptical follow-up ("and what about that one?") resolves against the most
    recent turn, so trimming has to take from the front, not the back."""
    budget = A.LLM_CONTEXT_TOKENS - 420 - A.LLM_CONTEXT_SAFETY_TOKENS
    system = "s" * int((budget - 800) * A.LLM_CHARS_PER_TOKEN_LATIN)
    history = _msgs(20, 400)
    history[-1] = {"role": "user", "content": "NEWEST"}
    kept = A.fit_history(system, "q", history, reply_tokens=420)
    assert kept, "at least the newest message should survive"
    assert kept[-1]["content"] == "NEWEST"


def test_order_is_preserved() -> None:
    system = "s" * 10_000
    history = [{"role": "user", "content": f"m{i}"} for i in range(6)]
    kept = A.fit_history(system, "q", history, reply_tokens=420)
    assert [m["content"] for m in kept] == sorted(
        (m["content"] for m in kept), key=lambda c: int(c[1:])
    )


def test_a_short_conversation_is_left_alone() -> None:
    """The budget must not trim a turn that already fits — that would silently cost
    the model context it was entitled to."""
    system = "s" * 2_000  # small enough to fit under any sane ratio
    history = _msgs(4, 200)
    assert A.fit_history(system, "q", history, reply_tokens=420) == history


def test_an_oversized_system_prompt_drops_all_history() -> None:
    """If the prompt alone overflows there is no history left to drop. Returning
    empty (rather than raising) lets the request go out and the upstream error
    surface, instead of hiding the real problem behind a truncated prompt."""
    assert A.fit_history("s" * 100_000, "q", _msgs(4, 200), reply_tokens=420) == []


def test_an_upstream_error_frame_is_not_swallowed(monkeypatch) -> None:
    """The failure that hid this bug for a whole session.

    vLLM answers an over-long request with 200 OK and one SSE frame carrying
    {"error": ...} — no "choices" key. The parser skipped it as unparseable, the
    generator finished having yielded nothing, and the turn went silent with
    nothing logged. It must raise instead, so the retry/demo path can see it.
    """
    import asyncio

    from server import config as C
    from server.agent import responder
    from server.providers import llm

    frames = [
        'data: {"error": {"message": "This model\'s maximum context length is 8192 tokens."}}',
        "",
        "data: [DONE]",
    ]

    class _Resp:
        status_code = 200
        def raise_for_status(self): pass
        async def aiter_lines(self):
            for f in frames:
                yield f
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False

    class _Client:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        def stream(self, *a, **k): return _Resp()

    monkeypatch.setattr(llm.httpx, "AsyncClient", _Client)
    monkeypatch.setattr(C, "llm_ready", lambda: True)

    async def _collect():
        return [s async for s, _ in responder.respond_sentences("سوال", "ur", [], "female")]

    out = asyncio.run(_collect())
    # It must not come back empty and silent. The demo line is the visible
    # fallback — what matters is that SOMETHING is said and the error surfaced.
    assert out, "an upstream error must not yield an empty, silent turn"


def test_retrieved_context_is_trimmed_before_the_reply_is_shortened() -> None:
    """The prompt can overflow with an EMPTY history — the real failure was 7,773
    input tokens plus 420 reserved against an 8,192 window, over by one token.

    Shortening the answer instead would cut the reply mid-sentence, which the
    visitor hears. Dropping the tail of the retrieved context costs at most the
    least-relevant section, since they arrive ranked best-first.
    """
    marker = CONTEXT_HEADER
    head = "PERSONA AND CORE BRIEF\n\n"
    prompt = head + marker + "\n" + ("ک " * 20_000)
    out = A.fit_system_prompt(prompt, "سوال", reply_tokens=420)
    assert len(out) < len(prompt)
    # Everything above the marker is persona/core brief and must survive intact.
    assert out.startswith(head + marker)
    budget = A.LLM_CONTEXT_TOKENS - 420 - A.LLM_CONTEXT_SAFETY_TOKENS
    assert A.estimate_tokens(out) + A.estimate_tokens("سوال") <= budget


def test_a_prompt_that_already_fits_is_untouched() -> None:
    """Trimming a prompt that fits would silently cost the model retrieved context
    it was entitled to."""
    prompt = "PERSONA\n\n" + CONTEXT_HEADER + "\nshort context"
    assert A.fit_system_prompt(prompt, "q", reply_tokens=420) == prompt


def test_a_prompt_with_no_retrieved_context_is_never_cut() -> None:
    """With no retrieved section there is only persona and core brief left, and
    cutting those costs the kiosk its identity. Send it and let the error show."""
    prompt = "PERSONA AND CORE BRIEF " * 5_000   # no context marker at all
    assert A.fit_system_prompt(prompt, "q", reply_tokens=420) == prompt


def test_urdu_script_is_priced_higher_than_latin() -> None:
    """One Urdu prompt mixes Urdu-script rules with English knowledge; pricing both at
    the Urdu rate threw away retrieved knowledge that would have fit."""
    assert A.estimate_tokens("ک" * 100) > A.estimate_tokens("k" * 100)


def test_english_knowledge_in_an_urdu_prompt_is_kept_when_it_fits() -> None:
    """The Board question: ~3k tokens of Urdu rules plus ~7.5k chars of English knowledge
    is ~5k real tokens. The flat Urdu ratio cut 40-65% of that knowledge."""
    head = "ک " * 2_500 + "\n\n" + CONTEXT_HEADER + "\n"
    prompt = head + "Board member Syed Bakhtiyar Kazmi, Non-Executive Director. " * 125
    assert A.fit_system_prompt(prompt, "board ke baray mein bataiye", reply_tokens=420) == prompt
