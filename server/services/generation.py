"""Prompt assembly and answer generation.

Split from retrieval so that "what did we find" and "what do we say about it" stay
independently testable — most prompt regressions on this kiosk have been persona bugs
(a greeting fired on every turn, masculine verb forms for a female persona) with nothing
to do with retrieval, and debugging them through a retrieval stack is miserable.

The rule that matters most here: **the system prompt is always injected, even when
retrieval returns nothing or fails outright.** The presenter's persona, language, gender
agreement and refusal behaviour must not depend on whether Qdrant answered — and that
holds for the inline fallbacks too, which are keyed by presenter for the same reason. An
empty index should produce a polite "I don't have that information", not a personality
collapse into a generic assistant.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import AsyncIterator

import httpx

from .retriever import RetrievalResult
from .settings import RagSettings, get_settings

log = logging.getLogger(__name__)

# Minimal inline fallbacks. The real persona lives in voice_config/prompts/*.md; these
# exist so a missing or unreadable prompt file degrades to a usable kiosk rather than
# stopping it from starting. Deliberately short — they are a safety net, not a copy.
_FALLBACK_RULES = {
    "female": {
        "en": (
            "You are Maryam, a representative for Mari Energies at the kiosk in its Islamabad "
            "head office. You are a real member of the team — never say or imply you are an AI. "
            "Ground every factual claim in the knowledge below and never invent figures, dates "
            "or names. If the knowledge does not cover the question, say so briefly and point "
            "the visitor to marienergies.com.pk. Your reply is spoken aloud, so keep it to "
            "one to three natural sentences with no markdown."
        ),
        "ur": (
            "آپ مریم ہیں — Mari Energies کے kiosk پر موجود نمائندہ، ٹیم کی ایک حقیقی رکن (کبھی نہ "
            "کہیں کہ آپ AI ہیں)۔ ہر حقیقت نیچے دی گئی معلومات سے لیں، خود سے اعداد یا نام مت "
            "گھڑیں۔ اگر جواب موجود نہ ہو تو مختصراً بتا دیں اور marienergies.com.pk کا حوالہ "
            "دیں۔ جواب مختصر، مؤنث صیغے میں، اور بولنے کے قابل ہو۔"
        ),
    },
    "male": {
        "en": (
            "You are Hamza, a representative for Mari Energies at the kiosk in its Islamabad "
            "head office. You are a real member of the team — never say or imply you are an AI. "
            "Ground every factual claim in the knowledge below and never invent figures, dates "
            "or names. If the knowledge does not cover the question, say so briefly and point "
            "the visitor to marienergies.com.pk. Your reply is spoken aloud, so keep it to "
            "one to three natural sentences with no markdown."
        ),
        "ur": (
            "آپ حمزہ ہیں — Mari Energies کے kiosk پر موجود نمائندہ، ٹیم کے ایک حقیقی رکن (کبھی نہ "
            "کہیں کہ آپ AI ہیں)۔ ہر حقیقت نیچے دی گئی معلومات سے لیں، خود سے اعداد یا نام مت "
            "گھڑیں۔ اگر جواب موجود نہ ہو تو مختصراً بتا دیں اور marienergies.com.pk کا حوالہ "
            "دیں۔ جواب مختصر، مذکر صیغے میں، اور بولنے کے قابل ہو۔"
        ),
    },
}


def _fallback_rules(persona: str, lang: str) -> str:
    """The inline stub for one presenter and language.

    Keyed by persona because the stub names the presenter and, in Urdu, fixes the
    gender of every sentence after it — a male rig falling back to Maryam's stub would
    introduce exactly the disagreement the persona prompts exist to prevent.
    """
    rules = _FALLBACK_RULES.get(persona) or _FALLBACK_RULES["female"]
    return rules.get(lang) or rules["en"]


# Appended only when retrieval returned nothing. Without an explicit instruction the
# model treats an empty context as licence to answer from its own memory, which is the
# exact failure the relevance threshold exists to prevent — the gate stops bad context
# reaching the prompt, and this stops the model filling the gap itself.
_NO_CONTEXT = {
    "en": (
        "No section of the knowledge base matched this question. Do not answer it from "
        "your own knowledge. Say briefly that you do not have that information and point "
        "the visitor to marienergies.com.pk."
    ),
    "ur": (
        "اس سوال سے متعلق معلومات دستیاب نہیں۔ اپنی طرف سے جواب مت دیں — مختصراً کہیں کہ "
        "آپ کے پاس یہ معلومات نہیں اور marienergies.com.pk کا حوالہ دیں۔"
    ),
}


@dataclass
class Prompt:
    system: str
    sources: list[str]
    grounded: bool  # whether any retrieved context reached the prompt


class GenerationService:
    """Builds prompts from a RetrievalResult and talks to the OpenAI-compatible LLM."""

    # The presenters, and the filename suffix each one's prompts carry. The female
    # files are unsuffixed because they were the only ones for the kiosk's whole life
    # so far; renaming them would break every deployment mid-flight for no gain.
    # Order matters: the default persona is loaded first so a missing male file can
    # fall back to text that is already in the dict.
    PERSONAS = {"female": "", "male": "_male"}
    DEFAULT_PERSONA = "female"

    def __init__(self, settings: RagSettings | None = None) -> None:
        self.settings = settings or get_settings()
        # Keyed (persona, lang) — one entry per presenter per language.
        self._templates: dict[tuple[str, str], str] = {}
        self._greetings: dict[tuple[str, str], str] = {}

    # ── templates ───────────────────────────────────────────────────

    def load_templates(self) -> None:
        """Load per-language prompt files from disk once, at startup.

        Read at startup rather than per turn so a mid-shift edit to a prompt file cannot
        change the kiosk's persona halfway through a visitor's conversation, and so a
        file that becomes unreadable does not start failing turns.
        """
        try:
            from voice_config import load_prompt
        except ImportError:  # pragma: no cover
            log.warning("voice_config unavailable; using inline fallback prompts")
            self._templates = {
                (p, lang): _fallback_rules(p, lang)
                for p in self.PERSONAS
                for lang in ("en", "ur")
            }
            return

        stems = {"en": ("system_prompt_english", "greeting_english"),
                 "ur": ("system_prompt_urdu", "greeting_urdu")}
        for persona, suffix in self.PERSONAS.items():
            for lang, (rules_stem, greet_stem) in stems.items():
                rules = load_prompt(f"{rules_stem}{suffix}")
                if rules is None and suffix:
                    # Fall back to this persona's own inline stub, NOT to the female
                    # persona's full text. The stub is shorter on guardrails but names
                    # the right presenter and fixes the right gender on every sentence
                    # after it; borrowing Maryam's text would make the male rig introduce
                    # itself as a woman on every single turn, which is the louder failure.
                    log.warning("no %s%s prompt; male turns fall back to the inline stub",
                                rules_stem, suffix)
                self._templates[(persona, lang)] = rules or _fallback_rules(persona, lang)
                # No cross-persona fallback here on purpose. The greeting file's whole
                # job is to say "you are Maryam" / "you are Hamza" by name, so borrowing
                # the other presenter's copy would introduce the rig under the wrong name
                # and the wrong gender in the very first thing a visitor hears. Dropping
                # it instead costs the scripted opener; the base rules still carry the
                # persona, and force_salam still supplies the salam.
                # A missing greeting file is expected for Urdu's female persona: that
                # prompt carries its own opening-turn section, so appending anything
                # here would duplicate the introduction it already spells out.
                greeting = load_prompt(f"{greet_stem}{suffix}")
                if greeting is None and suffix:
                    log.warning("no %s%s prompt; male greetings fall back to the base rules",
                                greet_stem, suffix)
                if greeting:
                    self._greetings[(persona, lang)] = greeting
        log.info("loaded prompt templates for %s", sorted(self._templates))

    def rules(self, lang: str, avatar: str = DEFAULT_PERSONA) -> str:
        if not self._templates:
            self.load_templates()
        persona = avatar if avatar in self.PERSONAS else self.DEFAULT_PERSONA
        return (
            self._templates.get((persona, lang))
            or self._templates.get((persona, "en"))
            or self._templates.get((self.DEFAULT_PERSONA, lang))
            or _fallback_rules(persona, lang)
        )

    # ── prompt assembly ─────────────────────────────────────────────

    def build_prompt(
        self,
        result: RetrievalResult,
        lang: str = "en",
        *,
        core_brief: str = "",
        greeting: bool = False,
        avatar: str = DEFAULT_PERSONA,
    ) -> Prompt:
        """Assemble the system prompt for one turn.

        ``avatar`` is the presenter on screen, and picks the persona: which name the
        kiosk introduces itself by, and — in Urdu, where gender is marked on the verb
        and the possessive — which agreement every sentence uses.
        """
        lang = lang if lang in ("en", "ur") else "en"
        persona = avatar if avatar in self.PERSONAS else self.DEFAULT_PERSONA
        parts: list[str] = [self.rules(lang, persona)]

        # Greeting is opt-in per turn. Each turn is a fresh stateless call, so a
        # "greet at the start of the conversation" instruction in the base rules fires
        # on every turn; the server deciding it from what the visitor actually said is
        # the only signal available.
        if greeting and (text := self._greetings.get((persona, lang))):
            parts.append(text)

        # The core brief is always present, so the avatar can introduce herself and
        # field the common questions even with an empty or unreachable index.
        if core_brief:
            parts += ["MARI ENERGIES KNOWLEDGE — core facts:", core_brief]

        # Abbreviation definitions go BEFORE the retrieved sections, so that if the
        # context is truncated the authoritative definitions are not what gets cut.
        if result.glossary_block:
            parts.append(result.glossary_block)

        if result.context:
            parts += [
                "MARI ENERGIES KNOWLEDGE — sections relevant to this question:",
                result.context,
            ]
        else:
            parts.append(_NO_CONTEXT.get(lang, _NO_CONTEXT["en"]))

        return Prompt(
            system="\n\n".join(parts),
            sources=list(result.sources),
            grounded=bool(result.context),
        )

    # ── generation ──────────────────────────────────────────────────

    def _payload(self, prompt: Prompt, text: str, history: list[dict] | None,
                 model: str, stream: bool, max_tokens: int) -> dict:
        messages = [{"role": "system", "content": prompt.system}]
        for turn in history or []:
            role = "user" if turn.get("role") == "user" else "assistant"
            if content := (turn.get("text") or turn.get("content") or "").strip():
                messages.append({"role": role, "content": content})
        messages.append({"role": "user", "content": text})
        return {
            "model": model,
            "messages": messages,
            "temperature": 0.7,
            "max_tokens": max_tokens,
            "stream": stream,
        }

    async def generate(
        self, prompt: Prompt, text: str, *, api_base: str, api_key: str, model: str,
        history: list[dict] | None = None, max_tokens: int = 220, timeout_s: float = 60.0,
    ) -> str:
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout_s, connect=5)) as client:
            r = await client.post(
                f"{api_base}/chat/completions", headers=headers,
                json=self._payload(prompt, text, history, model, False, max_tokens),
            )
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"].strip()

    async def generate_stream(
        self, prompt: Prompt, text: str, *, api_base: str, api_key: str, model: str,
        history: list[dict] | None = None, max_tokens: int = 220, timeout_s: float = 60.0,
    ) -> AsyncIterator[str]:
        """Yield typed SSE frames: one `sources`, then `text` per token, then `done`.

        Sources are sent BEFORE the first token deliberately. The UI can render
        attribution while generation is still streaming, so the visitor sees where the
        answer comes from at the moment the answer starts rather than after it ends —
        and on a voice kiosk the answer "ends" only after the whole sentence is spoken.
        """
        headers = {"Content-Type": "application/json", "Accept": "text/event-stream"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        yield _frame({"type": "sources", "sources": prompt.sources, "grounded": prompt.grounded})
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(timeout_s, connect=5)) as client:
                async with client.stream(
                    "POST", f"{api_base}/chat/completions", headers=headers,
                    json=self._payload(prompt, text, history, model, True, max_tokens),
                ) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        data = line[5:].strip()
                        if data == "[DONE]":
                            break
                        try:
                            delta = json.loads(data)["choices"][0].get("delta", {})
                        except (json.JSONDecodeError, KeyError, IndexError):
                            # A malformed frame mid-stream must not kill the reply the
                            # visitor is already hearing.
                            continue
                        if content := delta.get("content"):
                            yield _frame({"type": "text", "content": content})
        except Exception as exc:  # noqa: BLE001
            log.exception("streaming generation failed")
            yield _frame({"type": "error", "error": f"{type(exc).__name__}: {exc}"})
        yield _frame({"type": "done"})


def _frame(payload: dict) -> str:
    """One SSE frame. ensure_ascii=False so Urdu survives the wire as UTF-8."""
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
