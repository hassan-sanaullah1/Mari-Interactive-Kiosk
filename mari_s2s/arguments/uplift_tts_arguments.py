"""CLI/config arguments for the Uplift TTS handler.

Mirrors s2s's `arguments_classes/*` dataclass pattern: fields become
`--uplift_tts_<field>` flags and are forwarded to `UpliftTTSHandler.setup()`.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass
class UpliftTTSHandlerArguments:
    uplift_tts_api_key: str = field(
        default_factory=lambda: os.getenv("APP_UPLIFT_API_KEY", "")
    )
    uplift_tts_api_base: str = field(
        default_factory=lambda: os.getenv(
            "APP_UPLIFT_TTS_BASE_URL", "https://ap-southeast-1.api.upliftai.org"
        )
    )
    uplift_tts_voice_id: str = field(
        default_factory=lambda: os.getenv("APP_UPLIFT_VOICE_ID", "v_8eelc901v6")
    )
    uplift_tts_output_format: str = field(
        default_factory=lambda: os.getenv("APP_UPLIFT_OUTPUT_FORMAT", "MP3_22050_128")
    )
    uplift_tts_blocksize: int = 512

    def to_setup_kwargs(self) -> dict:
        return {
            "api_key": self.uplift_tts_api_key,
            "api_base": self.uplift_tts_api_base,
            "voice_id": self.uplift_tts_voice_id,
            "output_format": self.uplift_tts_output_format,
            "blocksize": self.uplift_tts_blocksize,
        }
