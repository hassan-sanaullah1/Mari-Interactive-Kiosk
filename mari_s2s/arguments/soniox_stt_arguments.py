"""CLI/config arguments for the Soniox STT handler.

Mirrors s2s's `arguments_classes/*` dataclass pattern: fields become
`--soniox_stt_<field>` flags and are forwarded to `SonioxSTTHandler.setup()`.
Values default from the APP_* environment so it lines up with the kiosk repo.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass
class SonioxSTTHandlerArguments:
    soniox_stt_api_key: str = field(
        default_factory=lambda: os.getenv("APP_SONIOX_API_KEY", "")
    )
    soniox_stt_api_base: str = field(
        default_factory=lambda: os.getenv(
            "APP_SONIOX_API_BASE", "wss://stt-rt.soniox.com/transcribe-websocket"
        )
    )
    soniox_stt_model: str = field(
        default_factory=lambda: os.getenv("APP_SONIOX_MODEL", "stt-rt-preview")
    )
    soniox_stt_language: str = "ur"

    def to_setup_kwargs(self) -> dict:
        return {
            "api_key": self.soniox_stt_api_key,
            "api_base": self.soniox_stt_api_base,
            "model": self.soniox_stt_model,
            "language": self.soniox_stt_language,
        }
