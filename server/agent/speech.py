"""Turns one reply sentence into audio: spoken-form normalization, then TTS."""

from __future__ import annotations

from .. import providers
from ..normalization import normalize_for_tts


async def speak(text: str, lang: str, avatar: str = "female") -> tuple[bytes, str]:
    provider = providers.get_tts_provider(lang, avatar)
    text = (text or "").strip()
    if text and provider.wants_spoken_form:
        # Kokoro is English-only, so it has no "lang"; Uplift carries the reply's language.
        text = normalize_for_tts(text, getattr(provider, "lang", "en"),
                                 getattr(provider, "engine", "uplift"))
    return await provider.synthesize(text)
