# 0003 — Every speech and LLM vendor behind a Protocol

**Status:** accepted · 2026-10

## Context

Speech to text is Soniox for Urdu and faster-whisper for English. Text to speech is
Uplift, Matcha-TTS or Kokoro depending on language, presenter and deployment. The LLM
is Qwen on vLLM or DeepSeek. Which one runs is a per-deployment setting.

Without an interface, that choice leaks into every call site. It had: three separate
`httpx` clients for the same LLM — in the provider, in the retrieval query rewriter and
in the answer evaluator — which had drifted apart, one of them silently not sending a
parameter the others did.

## Decision

`typing.Protocol` interfaces in `providers/base.py`; one adapter class per vendor; one
selection function per kind, which is the only code that names a vendor.

Structural typing rather than inheritance: an adapter satisfies the Protocol by having
the right methods, so it carries no dependency on our framework and is trivial to fake
in a test.

## Considered

**Abstract base classes.** Equivalent in practice. `Protocol` was chosen so adapters
need not import anything of ours.

**Call vendors directly and configure with if-statements.** What it was. Adding a
vendor meant touching every call site.

## Consequences

- Adding a vendor is one class and one line in the selection function.
- Tests fake a provider by passing an object with two methods.
- The Protocols must stay honest. One had drifted — it declared `transcribe_pcm` while
  callers used `transcribe` — which mypy could not catch because nothing was typed
  against it. They are now checked.
- Streaming speech to text does not fit the simple interface and has its own.
