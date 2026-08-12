"""Registration helpers to make our custom handlers selectable in s2s.

s2s picks a backend from a name (e.g. ``--stt faster-whisper``) via a mapping in
its pipeline builder. There are two supported ways to add ours; see
docs/integration.md for the full walkthrough. This module centralises the names
and the handler/argument classes both approaches use.

IMPORTANT: s2s's internal builder/registry is version-specific. The exact symbol
to extend (the STT/TTS name→class dict) must be confirmed against the s2s commit
you pin — `try_autoregister()` attempts the common cases and no-ops (loudly) if it
can't find them, so nothing fails silently.
"""

from __future__ import annotations

import logging

from mari_s2s.arguments.soniox_stt_arguments import SonioxSTTHandlerArguments
from mari_s2s.arguments.uplift_tts_arguments import UpliftTTSHandlerArguments
from mari_s2s.handlers.soniox_stt_handler import SonioxSTTHandler
from mari_s2s.handlers.uplift_tts_handler import UpliftTTSHandler

logger = logging.getLogger("mari_s2s.register")

# CLI names we expose.
STT_NAME = "soniox"
TTS_NAME = "uplift"

STT_REGISTRATION = (STT_NAME, SonioxSTTHandler, SonioxSTTHandlerArguments)
TTS_REGISTRATION = (TTS_NAME, UpliftTTSHandler, UpliftTTSHandlerArguments)


def try_autoregister() -> bool:
    """Best-effort runtime registration into s2s's handler maps.

    Returns True if both handlers were registered, False otherwise (in which case
    use the drop-in file approach from docs/integration.md). Never raises.
    """
    ok = True
    try:
        from speech_to_speech import s2s_pipeline as builder  # type: ignore

        # Common shapes seen across s2s versions: a module-level dict mapping the
        # CLI name to the handler class. Try a few likely names.
        for dict_name in ("STT_HANDLERS", "STT_BACKENDS", "STT_MAP"):
            registry = getattr(builder, dict_name, None)
            if isinstance(registry, dict):
                registry[STT_NAME] = SonioxSTTHandler
                logger.info("Registered Soniox STT into %s.%s", builder.__name__, dict_name)
                break
        else:
            ok = False
        for dict_name in ("TTS_HANDLERS", "TTS_BACKENDS", "TTS_MAP"):
            registry = getattr(builder, dict_name, None)
            if isinstance(registry, dict):
                registry[TTS_NAME] = UpliftTTSHandler
                logger.info("Registered Uplift TTS into %s.%s", builder.__name__, dict_name)
                break
        else:
            ok = False
    except Exception as e:  # noqa: BLE001
        logger.warning("Autoregister failed (%s). Use the drop-in approach instead.", e)
        ok = False

    if not ok:
        logger.warning(
            "Could not locate s2s's handler registry automatically. "
            "Follow docs/integration.md to add the two lines to your pinned commit."
        )
    return ok
