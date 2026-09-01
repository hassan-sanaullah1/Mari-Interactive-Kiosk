"""MARI · Voice — configuration.

Single source of truth for the web server + providers. Reads ``.env`` (real
environment variables win) and exposes typed settings per stage. All providers are
plain HTTP/WebSocket clients — no LiveKit, no speech_to_speech runtime dependency —
so they run standalone under this project.
"""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB_DIR = ROOT / "web"


def _load_env(path: Path) -> dict:
    env: dict[str, str] = {}
    if not path.exists():
        return env
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        val = val.split(" #")[0].strip().strip('"').strip("'")
        env[key.strip()] = val
    return env


# real env vars take precedence over .env file
ENV = {**_load_env(ROOT / ".env"), **os.environ}


def env(key: str, default: str = "") -> str:
    v = ENV.get(key, "")
    return v if v else default


FORCE_DEMO = ENV.get("MARI_FORCE_DEMO") == "1"

# ── LLM — prefer DeepSeek (APP_LLM_*) when configured, else vLLM Qwen (APP_VLLM_*).
#    Force either with APP_LLM_PROVIDER = "deepseek" | "vllm". ─────────
_LLM_FORCED = env("APP_LLM_PROVIDER").lower()
_DS_BASE, _DS_KEY = env("APP_LLM_API_BASE"), env("APP_LLM_API_KEY")
_USE_DEEPSEEK = _LLM_FORCED == "deepseek" or (_LLM_FORCED != "vllm" and bool(_DS_BASE and _DS_KEY))

if _USE_DEEPSEEK:
    LLM_PROVIDER = "deepseek"
    LLM_BASE = _DS_BASE.rstrip("/")
    LLM_KEY = _DS_KEY
    LLM_MODEL = env("APP_LLM_MODEL", "deepseek-chat")
else:
    LLM_PROVIDER = "vllm"
    LLM_BASE = env("APP_VLLM_API_BASE").rstrip("/")
    LLM_KEY = env("APP_VLLM_API_KEY")
    LLM_MODEL = env("APP_VLLM_MODEL", "qwen3.5")

# ── Urdu STT — Soniox realtime (websocket) ──────────────────────────
SONIOX_KEY = env("APP_SONIOX_API_KEY")
SONIOX_URL = env("APP_SONIOX_BASE_URL", "wss://stt-rt.jp.soniox.com/transcribe-websocket")
SONIOX_MODEL = env("APP_SONIOX_MODEL", "stt-rt-v4")

# ── Urdu TTS — UpliftAI (REST, returns mp3) ─────────────────────────
UPLIFT_KEY = env("APP_UPLIFT_API_KEY")
UPLIFT_BASE = env("APP_UPLIFT_TTS_BASE_URL", "https://ap-southeast-1.api.upliftai.org").rstrip("/")
UPLIFT_PATH = env("APP_UPLIFT_TTS_API_PATH", "/v1/synthesis/text-to-speech")
UPLIFT_VOICE = env("APP_UPLIFT_VOICE_ID", "v_8eelc901v6")
# Uplift also handles English (see APP_EN_TTS=uplift below). Same voice by default so
# the kiosk keeps one persona across both languages; override for a separate English one.
UPLIFT_VOICE_EN = env("APP_UPLIFT_VOICE_ID_EN", UPLIFT_VOICE)
UPLIFT_FORMAT = env("APP_UPLIFT_OUTPUT_FORMAT", "MP3_22050_32")

# ── English STT/TTS. STT runs LOCALLY by default (the s2s built-in faster-whisper).
#    English TTS defaults to Uplift — the same provider (and voice) as Urdu, reading
#    English text — because no Kokoro instance is deployed right now. Point APP_EN_TTS
#    back at "local"/"remote" once one is. Urdu always stays on Soniox/Uplift. ──
EN_STT = env("APP_EN_STT", "local")     # "local" (faster-whisper) | "remote"
EN_TTS = env("APP_EN_TTS", "uplift")    # "uplift" | "local" (kokoro) | "remote"

# local faster-whisper
WHISPER_LOCAL_MODEL = env("APP_ASR_MODEL_SIZE", "base.en")

# remote Whisper (fallback if APP_EN_STT=remote)
WHISPER_URL = env("APP_REMOTE_WHISPER_URL")
WHISPER_TOKEN = env("APP_REMOTE_WHISPER_TOKEN")
WHISPER_MODEL = env("APP_REMOTE_WHISPER_MODEL", "whisper-1")

# remote Kokoro (fallback if APP_EN_TTS=remote)
KOKORO_BASE = env("APP_REMOTE_TTS_API_BASE").rstrip("/")
KOKORO_PATH = env("APP_REMOTE_TTS_API_PATH", "/v1/audio/speech")
KOKORO_TOKEN = env("APP_REMOTE_TTS_TOKEN")
KOKORO_MODEL = env("APP_REMOTE_TTS_MODEL", "kokoro")
KOKORO_FORMAT = env("APP_REMOTE_TTS_RESPONSE_FORMAT", "mp3")

# ── Audio2Face-3D (avatar lipsync) — NVIDIA NIM over gRPC ───────────
#    Unset APP_A2F_URL ⇒ no lipsync frames; everything else runs unchanged.
#    Forms: host:port · grpc://host:port · grpcs://host[:port] (TLS + API key)
A2F_URL = env("APP_A2F_URL")
A2F_API_KEY = env("APP_A2F_API_KEY")
A2F_TLS_CA = env("APP_A2F_TLS_CA")
# How many reply sentences may be in flight at the NIM at once. Must not exceed
# the NIM's own `stream_number` (deploy/a2f/configs/deployment_config.yaml),
# which is 1 on a 6GB GPU and 3 on a full-size one.
A2F_MAX_CLIPS = max(1, int(env("APP_A2F_MAX_CLIPS", "1")))

# ── Voices ──────────────────────────────────────────────────────────
# Kokoro voice names. Urdu always uses Uplift (UPLIFT_VOICE) and English uses Uplift
# too while APP_EN_TTS=uplift (UPLIFT_VOICE_EN), so these only apply when either
# language is routed to Kokoro.
VOICE_EN = env("APP_TTS_VOICE_ENGLISH", "af_heart")
VOICE_UR = env("APP_TTS_VOICE_URDU", "af_heart")


def llm_ready() -> bool:
    return bool(LLM_BASE and LLM_KEY) and not FORCE_DEMO


def stt_ready(lang: str) -> bool:
    if lang == "ur":
        return bool(SONIOX_KEY)
    return True if EN_STT == "local" else bool(WHISPER_URL)


def tts_ready(lang: str) -> bool:
    if lang == "ur" or EN_TTS == "uplift":
        return bool(UPLIFT_KEY)
    return True if EN_TTS == "local" else bool(KOKORO_BASE)


def status() -> dict:
    """Compact config snapshot for /healthz (no secrets)."""
    en_stt = f"whisper-local:{WHISPER_LOCAL_MODEL}" if EN_STT == "local" else "whisper-remote"
    en_tts = {"uplift": "uplift", "local": "kokoro-local"}.get(EN_TTS, "kokoro-remote")
    return {
        "llm": {"ready": llm_ready(), "provider": LLM_PROVIDER, "model": LLM_MODEL, "base": LLM_BASE or None},
        "stt": {
            "ur": {"provider": "soniox", "ready": stt_ready("ur"), "model": SONIOX_MODEL},
            "en": {"provider": en_stt, "ready": stt_ready("en")},
        },
        "tts": {
            "ur": {"provider": "uplift", "ready": tts_ready("ur"), "voice": UPLIFT_VOICE},
            "en": {
                "provider": en_tts,
                "ready": tts_ready("en"),
                "voice": UPLIFT_VOICE_EN if EN_TTS == "uplift" else VOICE_EN,
            },
        },
        "avatar": _avatar_status(),
    }


def _avatar_status() -> dict:
    """Lipsync readiness — imported lazily so config stays dependency-free."""
    from .avatar import a2f_status

    return {"a2f": a2f_status()}
