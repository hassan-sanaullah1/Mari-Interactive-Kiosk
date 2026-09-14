"""Turns one reply sentence into audio: spoken-form normalization, then TTS."""

from __future__ import annotations

from .. import providers
from ..normalization import normalize_for_tts, spoken_units


async def speak(text: str, lang: str, avatar: str = "female") -> tuple[bytes, str]:
    provider = providers.get_tts_provider(lang, avatar)
    text = (text or "").strip()
    if text and provider.wants_spoken_form:
        text = normalize_for_tts(text, provider.lang)
    elif text:
        # English-only engines (Kokoro) must not get the Uplift rewrites, which put names
        # in Urdu script, but they still spell unit symbols out: "50kW" as "K W".
        text = spoken_units(text, "en")
    return await provider.synthesize(text)
