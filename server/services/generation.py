"""System prompt assembly for one turn, from a RetrievalResult and the prompt files.

The persona prompt is always included, even when retrieval returns nothing or fails:
an empty index must produce "I don't have that information", not a generic assistant.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from ..prompts import LANGS, PERSONAS, PromptLibrary, get_prompts
from .retriever import RetrievalResult
from .settings import RagSettings, get_settings

log = logging.getLogger(__name__)

CORE_FACTS_HEADER = "MARI ENERGIES KNOWLEDGE — core facts:"
# Everything after this header is retrieved context, the only part safe to trim when
# the prompt is too long (see server/agent/context_budget.py).
CONTEXT_HEADER = "MARI ENERGIES KNOWLEDGE — sections relevant to this question:"


@dataclass
class Prompt:
    system: str
    sources: list[str]
    grounded: bool  # whether any retrieved context reached the prompt


class GenerationService:
    DEFAULT_PERSONA = "female"

    def __init__(self, settings: RagSettings | None = None) -> None:
        self.settings = settings or get_settings()
        self._templates: dict[tuple[str, str], str] = {}
        self._greetings: dict[tuple[str, str], str] = {}
        self._no_context: dict[str, str] = {}

    def load_templates(self, prompts: PromptLibrary | None = None) -> None:
        """Take the prompt text once, so an edit mid-shift cannot change a conversation."""
        prompts = prompts or get_prompts()
        self._templates = dict(prompts.system)
        self._greetings = dict(prompts.greeting)
        self._no_context = dict(prompts.no_context)
        log.info("loaded prompt templates for %s", sorted(self._templates))

    def rules(self, lang: str, avatar: str = DEFAULT_PERSONA) -> str:
        if not self._templates:
            self.load_templates()
        persona = avatar if avatar in PERSONAS else self.DEFAULT_PERSONA
        return self._templates.get((persona, lang)) or self._templates[(persona, "en")]

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

        ``avatar`` picks the persona: the presenter's name and, in Urdu, the gender
        agreement every sentence uses.
        """
        lang = lang if lang in LANGS else "en"
        persona = avatar if avatar in PERSONAS else self.DEFAULT_PERSONA
        parts: list[str] = [self.rules(lang, persona)]

        # The greeting block is added per turn: each turn is a stateless call, so a
        # "greet only at the start" rule in the base prompt would fire every time.
        if greeting and (text := self._greetings.get((persona, lang))):
            parts.append(text)

        if core_brief:
            parts += [CORE_FACTS_HEADER, core_brief]

        # Before the retrieved sections, so trimming context never cuts a definition.
        if result.glossary_block:
            parts.append(result.glossary_block)

        if result.context:
            parts += [CONTEXT_HEADER, result.context]
        else:
            # Without this the model treats empty context as licence to answer from memory.
            parts.append(self._no_context[lang])

        return Prompt(
            system="\n\n".join(parts),
            sources=list(result.sources),
            grounded=bool(result.context),
        )
