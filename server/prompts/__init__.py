"""The kiosk's prompt and spoken-line text, loaded once from the files in this folder.

    system/<persona>_<language>.md     persona and rules, always in the system prompt
    greeting/<persona>_<language>.md   added only on a turn that is a greeting
    core_brief.md                      short company brief, always in the system prompt
    no_context_<language>.md           added when retrieval found nothing
    query_rewriter.md                  system prompt for the follow-up query rewriter
    replies.toml                       fixed lines spoken without the LLM

A missing or empty file raises at load time, so a bad deploy fails at startup.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

PROMPT_DIR = Path(__file__).resolve().parent
PERSONAS = ("female", "male")
LANGS = ("en", "ur")
_LANGUAGE_NAMES = {"en": "english", "ur": "urdu"}


@dataclass(frozen=True)
class PromptLibrary:
    system: dict[tuple[str, str], str]      # (persona, lang) -> rules
    greeting: dict[tuple[str, str], str]    # (persona, lang) -> greeting instructions
    core_brief: str
    no_context: dict[str, str]              # lang -> instruction
    query_rewriter: str
    replies: dict[str, dict[str, dict[str, str]]]  # name -> persona -> lang -> line


def load_prompt(relative_path: str) -> str:
    """Read one prompt file, stripped. Raises if it is missing or empty."""
    path = PROMPT_DIR / relative_path
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        raise ValueError(f"prompt file is empty: {path}")
    return text


def load_prompts() -> PromptLibrary:
    def per_persona(kind: str) -> dict[tuple[str, str], str]:
        return {
            (persona, lang): load_prompt(f"{kind}/{persona}_{_LANGUAGE_NAMES[lang]}.md")
            for persona in PERSONAS
            for lang in LANGS
        }

    return PromptLibrary(
        system=per_persona("system"),
        greeting=per_persona("greeting"),
        core_brief=load_prompt("core_brief.md"),
        no_context={lang: load_prompt(f"no_context_{_LANGUAGE_NAMES[lang]}.md") for lang in LANGS},
        query_rewriter=load_prompt("query_rewriter.md"),
        replies=tomllib.loads((PROMPT_DIR / "replies.toml").read_text(encoding="utf-8")),
    )


@lru_cache(maxsize=1)
def get_prompts() -> PromptLibrary:
    return load_prompts()
