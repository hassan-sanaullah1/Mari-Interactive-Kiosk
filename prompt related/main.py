"""LiveKit voice agent for 3D chatbot with RAG, custom STT, and custom TTS."""

from __future__ import annotations

import asyncio
import httpx
import json
import logging
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from collections.abc import AsyncIterable


from livekit.agents import Agent, AgentSession, AgentServer, ModelSettings, cli, room_io
from livekit.agents import stt
from livekit.agents.llm import ChatMessage
from livekit.agents.metrics import EOUMetrics, LLMMetrics, STTMetrics, TTSMetrics, VADMetrics
from livekit.plugins import deepgram, elevenlabs, openai, silero, soniox, upliftai
# Not re-exported by the plugin package — imported from the module so the TTS
# socket can be opened during prewarm rather than on the first synthesize().
from livekit.plugins.upliftai.tts import WebSocketClient as _UpliftWebSocketClient
from openai import AsyncOpenAI

from plugins.whisper_stt import WhisperSTT
from plugins.kokoro_tts import KokoroTTS
from plugins.mms_tts import MMSTTS, load_model as load_mms_model
from plugins.remote_whisper_stt import RemoteWhisperSTT
from plugins.uplift_stt import UpliftSTT

try:
    from plugins.a2f_client import A2FClient
except ImportError as _a2f_err:  # nvidia-ace wheel not installed
    A2FClient = None
    logging.getLogger("chatbot-agent").warning("A2F client unavailable: %s", _a2f_err)

from urdu_normalised import find_safe_cut, urdu_text_tts_transform
from glossary import extract_glossary, find_glossary_matches, format_glossary_block

# Pre-import AlbertModel so it's available in the forkserver subprocess.
# Kokoro depends on transformers.AlbertModel internally. The transformers
# library uses lazy imports that break when loaded for the first time inside
# a forkserver child process. Importing here (in the main process) ensures
# the module is fully loaded before forking.
try:
    from transformers import AlbertModel as _AlbertModel  # noqa: F401
except ImportError:
    pass

logger = logging.getLogger("chatbot-agent")

# Keep livekit.agents at WARNING — DEBUG floods every audio frame and adds I/O overhead
logging.getLogger("livekit.agents").setLevel(logging.WARNING)

# ── Configuration from environment ───────────────────────────────
# LLM — OpenRouter (primary)
LLM_API_BASE = os.getenv("APP_LLM_API_BASE", "https://openrouter.ai/api/v1")
LLM_API_KEY = os.getenv("APP_LLM_API_KEY", "")
LLM_MODEL = os.getenv("APP_LLM_MODEL", "openai/gpt-4o-mini")

# LLM — vLLM (self-hosted, optional)
VLLM_API_BASE = os.getenv("APP_VLLM_API_BASE")
VLLM_API_KEY = os.getenv("APP_VLLM_API_KEY")
VLLM_MODEL = os.getenv("APP_VLLM_MODEL", "deepseek_v3")
QDRANT_HOST = os.getenv("APP_QDRANT_HOST", "localhost")
QDRANT_PORT = int(os.getenv("APP_QDRANT_PORT", "6333"))
QDRANT_COLLECTION = os.getenv("APP_QDRANT_COLLECTION", "documents")
QDRANT_API_KEY = os.getenv("APP_QDRANT_API_KEY", "")
EMBEDDING_MODEL = os.getenv(
    "APP_EMBEDDING_MODEL",
    "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
)
TOP_K = int(os.getenv("APP_TOP_K_RESULTS", "5"))
TTS_SPEED = float(os.getenv("APP_TTS_SPEED", "1.0"))
# Agent voices: Urdu and English
TTS_VOICE_URDU = os.getenv("APP_TTS_VOICE_URDU", "am_michael")  # Urdu male voice
TTS_VOICE_ENGLISH = os.getenv("APP_TTS_VOICE_ENGLISH", "am_michael")  # English male voice
TTS_VOICE_ENGLISH_FEMALE = os.getenv("APP_TTS_VOICE_ENGLISH_FEMALE", "af_heart")  # English female voice
TTS_VOICE = TTS_VOICE_URDU  # Default for backward compatibility
ASR_MODEL = os.getenv("APP_ASR_MODEL_SIZE", "large-v3-turbo")
ASR_DEVICE = os.getenv("APP_ASR_DEVICE", "cpu")
ASR_COMPUTE_TYPE = os.getenv("APP_ASR_COMPUTE_TYPE", "int8")
SYSTEM_PROMPT_PATH_URDU = os.getenv("APP_SYSTEM_PROMPT_PATH", "system_prompt_urdu.md")
SYSTEM_PROMPT_PATH_ENGLISH = os.getenv("APP_SYSTEM_PROMPT_PATH_ENGLISH", "system_prompt_english.md")
SYSTEM_PROMPT_PATH_ENGLISH_FEMALE = os.getenv(
    "APP_SYSTEM_PROMPT_PATH_ENGLISH_FEMALE", "system_prompt_english_female.md"
)
SYSTEM_PROMPT_PATH_URDU_FEMALE = os.getenv(
    "APP_SYSTEM_PROMPT_PATH_URDU_FEMALE", "system_prompt_urdu_female.md"
)
SYSTEM_PROMPT_PATH = SYSTEM_PROMPT_PATH_URDU  # Default for backward compatibility

# ElevenLabs (cloud TTS/STT alternative for latency benchmarking)
ELEVENLABS_API_KEY = os.getenv("APP_ELEVENLABS_API_KEY", "")
ELEVENLABS_VOICE_ID = os.getenv("APP_ELEVENLABS_VOICE_ID", "JBFqnCBsd6RMkjVDRZzb")
ELEVENLABS_VOICE_ID_URDU = os.getenv("APP_ELEVENLABS_VOICE_ID_URDU", "JBFqnCBsd6RMkjVDRZzb")  # Urdu male
ELEVENLABS_VOICE_ID_ENGLISH = os.getenv("APP_ELEVENLABS_VOICE_ID_ENGLISH", "EXAVITQu4vr4xnSDxMaL")  # English female
ELEVENLABS_MODEL_ID = os.getenv("APP_ELEVENLABS_MODEL_ID", "eleven_turbo_v2_5")

# UpliftAI (cloud TTS — Urdu voices)
UPLIFT_API_KEY = os.getenv("APP_UPLIFT_API_KEY", "")
UPLIFT_VOICE_ID = os.getenv("APP_UPLIFT_VOICE_ID", "v_8eelc901v6")
# Singapore region — UpliftAI's team measured 2-3x faster than other regions.
# Official plugin streams over WebSocket (vs. the old REST plugin's non-streaming
# request), so audio can start playing before the full response is synthesized.
UPLIFT_TTS_BASE_URL = os.getenv("APP_UPLIFT_TTS_BASE_URL", "wss://ap-southeast-1.api.upliftai.org")

# Audio2Face-3D (blendshape lipsync via NIM gRPC, e.g. host.docker.internal:52000)
A2F_URL = os.getenv("APP_A2F_URL", "")
# Production edge auth (grpcs:// URLs): bearer token checked by the reverse
# proxy in front of the NIM; optional CA bundle for private/internal CAs.
A2F_API_KEY = os.getenv("APP_A2F_API_KEY", "")
A2F_TLS_CA = os.getenv("APP_A2F_TLS_CA", "")
# Playback delay (s): audio is held this long per turn while A2F consumes it
# immediately, so blendshape frames lead playback.
#
# Now 0 — audio is released as soon as it is synthesized. The mouth is never
# dry during the gap: a2fMorphs.ts crossfades between wawa-lipsync visemes and
# A2F blendshapes (mix 0 -> 1 over ~200ms), so basic lipsync starts instantly
# and A2F takes over mid-sentence when its frames arrive.
#
# The previous 2.5s default was sized for whole-turn A2F clips, back when the
# UpliftAI plugin buffered the entire LLM response before synthesizing. With
# SentenceChunkedUpliftTTS each clip is one sentence, so frames return far
# sooner and the hold is no longer worth 2.5s of latency on every turn.
#
# Raise this (0.3-0.5) if A2F visibly pops in and out mid-turn.
A2F_PLAYBACK_DELAY = float(os.getenv("APP_A2F_PLAYBACK_DELAY", "0.0"))

# Deepgram (low-latency streaming STT)
DEEPGRAM_API_KEY = os.getenv("APP_DEEPGRAM_API_KEY", "")

# Soniox (low-latency streaming STT, Urdu + English)
SONIOX_API_KEY = os.getenv("APP_SONIOX_API_KEY", "")
# JP region endpoint — plugin default is the US endpoint, override via env if needed.
SONIOX_BASE_URL = os.getenv("APP_SONIOX_BASE_URL", "")

# Remote Whisper ASR
REMOTE_WHISPER_URL = os.getenv("APP_REMOTE_WHISPER_URL", "")
REMOTE_WHISPER_TOKEN = os.getenv("APP_REMOTE_WHISPER_TOKEN", "")
REMOTE_WHISPER_MODEL = os.getenv("APP_REMOTE_WHISPER_MODEL", "whisper")

# LangFuse observability (optional — disabled when keys are absent)
LANGFUSE_PUBLIC_KEY = os.getenv("APP_LANGFUSE_PUBLIC_KEY", "")
LANGFUSE_SECRET_KEY = os.getenv("APP_LANGFUSE_SECRET_KEY", "")
LANGFUSE_HOST = os.getenv("APP_LANGFUSE_HOST", "https://cloud.langfuse.com")

_langfuse_client = None
if LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY:
    try:
        from langfuse import Langfuse
        _langfuse_client = Langfuse(
            public_key=LANGFUSE_PUBLIC_KEY,
            secret_key=LANGFUSE_SECRET_KEY,
            host=LANGFUSE_HOST,
        )
        logger.info("LangFuse tracing enabled for agent (host=%s)", LANGFUSE_HOST)
    except Exception as _lf_err:
        logger.warning("Failed to initialise LangFuse in agent: %s", _lf_err)

# Arabic/Urdu Unicode detection
ARABIC_RE = re.compile(r"[\u0600-\u06FF\u0750-\u077F\uFB50-\uFDFF\uFE70-\uFEFF]")

_ROMAN_TO_CARDINAL = {
    "II": "two",
    "III": "three",
    "IV": "four",
    "V": "five",
    "VI": "six",
    "VII": "seven",
    "VIII": "eight",
    "IX": "nine",
    "X": "ten",
    "XI": "eleven",
    "XII": "twelve",
    "XIII": "thirteen",
    "XIV": "fourteen",
    "XV": "fifteen",
    "XVI": "sixteen",
    "XVII": "seventeen",
    "XVIII": "eighteen",
    "XIX": "nineteen",
    "XX": "twenty",
}

_ROMAN_TO_ORDINAL = {
    "II": "second",
    "III": "third",
    "IV": "fourth",
    "V": "fifth",
    "VI": "sixth",
    "VII": "seventh",
    "VIII": "eighth",
    "IX": "ninth",
    "X": "tenth",
    "XI": "eleventh",
    "XII": "twelfth",
    "XIII": "thirteenth",
    "XIV": "fourteenth",
    "XV": "fifteenth",
    "XVI": "sixteenth",
    "XVII": "seventeenth",
    "XVIII": "eighteenth",
    "XIX": "nineteenth",
    "XX": "twentieth",
}

# _ABBREVIATION_MAPPINGS = [
#     (re.compile(r"\b(kW)\b"),                  "Kilo Watt"),
#     (re.compile(r"\b(MW)\b"),                  "Mega Watt"),
#     (re.compile(r"\bNOC\b",   re.IGNORECASE),  "Network Operation Centre"),
#     (re.compile(r"\bSOC\b",   re.IGNORECASE),  "Security Operation Centre"),
#     (re.compile(r"\.com\.pk\b", re.IGNORECASE), "dot com dot pk"),
# ]


_ABBREVIATION_MAPPINGS = [
    # ── "as a Service" forms — MUST stay at the top of this list ─────────────
    # Every rule below is applied in order across the whole string, so a shorter
    # rule that fires first can strand the rest of a longer term. The hyphen is
    # what made this bite: "-" is a word boundary to Python's \b, so `\bAI\b`
    # (further down) matched inside "AI-aaS" and left a bare "aaS" behind, which
    # Kokoro then spelled out letter-by-letter -- the reported "Artificial
    # Intelligence a a s". Same trap for "GPU-as-a-Service" via `\bGPU\b`.
    #
    # Two defences, both applied before any bare acronym rule gets a turn:
    #   1) de-hyphenate the full spoken form, so no interior boundaries remain;
    #   2) expand each "…aaS" acronym straight to its COMPLETE spoken form, so
    #      the replacement text never contains an acronym that an already-passed
    #      rule would have been responsible for expanding.
    (re.compile(r"[\s-]as[\s-]a[\s-]Service\b", re.IGNORECASE), " as a Service"),

    # "BaaS/DRaaS" is written as a slash pair in the knowledge base; without
    # this the slash survives both acronym rules and is read aloud as "slash".
    (re.compile(r"\bBaaS\s*/\s*DRaaS\b"),            "Backup as a Service and Disaster Recovery as a Service"),

    (re.compile(r"\bAI[\s-]*aaS\b"),                 "Artificial Intelligence as a Service"),
    (re.compile(r"\bGPU[\s-]*aaS\b"),                "Graphics Processing Unit as a Service"),
    (re.compile(r"\bSECaaS\b"),                      "Security as a Service"),
    (re.compile(r"\bDRaaS\b"),                       "Disaster Recovery as a Service"),
    (re.compile(r"\bBaaS\b"),                        "Backup as a Service"),
    (re.compile(r"\bIaaS\b"),                        "Infrastructure as a Service"),
    (re.compile(r"\bPaaS\b"),                        "Platform as a Service"),
    (re.compile(r"\bSTaaS\b"),                       "Storage as a Service"),
    (re.compile(r"\bNaaS\b"),                        "Network as a Service"),
    (re.compile(r"\bSaaS\b"),                        "Software as a Service"),
    (re.compile(r"\bXaaS\b"),                        "Anything as a Service"),

    # ── Former Chairman ──────────────────────────────────────────────────────
    # Faheem Haider has been removed from the knowledge base entirely (the
    # Chairman is now Retired Lieutenant General Anwar Ali Haider), so any
    # occurrence of the old name in model output is a hallucination from the
    # LLM's own priors, not something it read in the retrieved context. Naming
    # the wrong person as Chairman is the worst factual error this agent can
    # make to a visitor, so it gets a deterministic backstop rather than
    # relying on the system prompt alone.
    (re.compile(r"\bFaheem\s+Ha?[iy]?der\b", re.IGNORECASE), "Anwar Ali Haider"),

    # ── Brand name ───────────────────────────────────────────────────────────
    # The company name is always spoken "Sky Forty Seven", never "Sky forty-seven"
    # as a quantity and never letter-spelled. Kokoro reads a bare "Sky47" as
    # "Sky four seven", so pin the spoken form here. Runs before everything else
    # so no later numeric rule sees the "47".
    (re.compile(r"\bSky\s*-?\s*47\b", re.IGNORECASE), "Sky Forty Seven"),

    # ── Original 5 (fixed escapes) ────────────────────────────────────────────
    (re.compile(r"\bkW\b"),                          "Kilo Watt"),
    (re.compile(r"\bMW\b"),                          "Mega Watt"),
    # When the LLM writes the abbreviation "NOC"/"SOC" it is spoken as a single
    # word ("nock"/"sock"), respelled phonetically so Kokoro reads it as a word
    # rather than an acronym. The full form ("Network Operations Center") is
    # left alone -- the LLM may use it when a caller needs the term explained.
    (re.compile(r"\bNOC\b"),                         "nock"),
    (re.compile(r"\bSOC\b"),                         "sock"),
    (re.compile(r"\.com\.pk\b", re.IGNORECASE),      "dot com dot pk"),

    # ── Numbers / symbols ─────────────────────────────────────────────────────
    # "24/7" — otherwise Kokoro reads the slash literally ("twenty four slash seven")
    (re.compile(r"\b24\s*/\s*7\b"),                  "twenty four seven"),

    # ── A ────────────────────────────────────────────────────────────────────
    (re.compile(r"\bAI\b"),                          "Artificial Intelligence"),

    # ── B ────────────────────────────────────────────────────────────────────
    (re.compile(r"\bB2B\b"),                         "Business to Business"),
    (re.compile(r"\bB2G\b"),                         "Business to Government"),
    (re.compile(r"\bBMS\b"),                         "Building Management System"),
 
    # ── C ────────────────────────────────────────────────────────────────────
    (re.compile(r"\bCC Attack\b", re.IGNORECASE),    "Credential Compromise Attack"),
    (re.compile(r"\bCEO\b"),                         "Chief Executive Officer"),
    (re.compile(r"\bCFO\b"),                         "Chief Financial Officer"),
    # CI/CD — match the slash literally
    (re.compile(r"\bCI/CD\b"),                       "Continuous Integration and Continuous Deployment"),
    (re.compile(r"\bCISO\b"),                        "Chief Information Security Officer"),
    (re.compile(r"\bCTIO\b"),                        "Chief Technology Information Officer"),
    (re.compile(r"\bCXO\b"),                         "C-level Executive"),
 
    # ── D ────────────────────────────────────────────────────────────────────
    (re.compile(r"\bDC\b"),                          "Data Center"),
    (re.compile(r"\bDCIM\b"),                        "Data Center Infrastructure Management"),
    (re.compile(r"\bDDoS\b"),                        "Distributed Denial of Service"),
    (re.compile(r"\bDRP\b"),                         "Digital Risk Protection"),
 
    # ── E ────────────────────────────────────────────────────────────────────
    # E&P — match ampersand literally
    (re.compile(r"\bE&P\b"),                         "Energy and Petroleum"),
    (re.compile(r"\bECS\b"),                         "Elastic Cloud Server"),
    (re.compile(r"\bEDR\b"),                         "Endpoint Detection and Response"),
    (re.compile(r"\bEGM\b"),                         "Extraordinary General Meeting"),
    (re.compile(r"\bESG\b"),                         "Environmental Social and Governance"),
 
    # ── F ────────────────────────────────────────────────────────────────────
    (re.compile(r"\bFAT\b"),                         "Factory Acceptance Test"),
    (re.compile(r"\bFBR\b"),                         "Federal Board of Revenue"),
 
    # ── G ────────────────────────────────────────────────────────────────────
    (re.compile(r"\bGenAI\b"),                       "Generative AI"),
    (re.compile(r"\bGPU\b"),                         "Graphics Processing Unit"),
    (re.compile(r"\bGRC\b"),                         "Governance Risk and Compliance"),
 
    # ── H ────────────────────────────────────────────────────────────────────
    (re.compile(r"\bHCS\b"),                         "Huawei Cloud Stack"),
    (re.compile(r"\bHPC\b"),                         "High Performance Computing"),
    (re.compile(r"\bHR\b"),                          "Human Resources"),
 
    # ── I ────────────────────────────────────────────────────────────────────
    (re.compile(r"\bIESCO\b"),                       "Islamabad Electric Supply Company"),
    (re.compile(r"\bIPS\b"),                         "Intrusion Prevention System"),
    (re.compile(r"\bISO\b"),                         "International Organization for Standardization"),
    (re.compile(r"\bIT\b"),                          "Information Technology"),
    (re.compile(r"\bIXP\b"),                         "Internet Exchange Point"),
 
    # ── K ────────────────────────────────────────────────────────────────────
    (re.compile(r"\bKMS\b"),                         "Key Management Service"),
 
    # ── L ────────────────────────────────────────────────────────────────────
    (re.compile(r"\bLEED\b"),                        "Leadership in Energy and Environmental Design"),
    (re.compile(r"\bLLM\b"),                         "Large Language Model"),
    (re.compile(r"\bLV\b"),                          "Low Voltage"),
 
    # ── M ────────────────────────────────────────────────────────────────────
    # MD/CEO — match slash literally
    (re.compile(r"\bMD/CEO\b"),                      "Managing Director and Chief Executive Officer"),
    (re.compile(r"\bMDB\b"),                         "Managed Database"),
    (re.compile(r"\bMEP\b"),                         "Mechanical Electrical and Plumbing"),
    (re.compile(r"\bMFA\b"),                         "Multi Factor Authentication"),
    (re.compile(r"\bMKS\b"),                         "Managed Kubernetes Services"),
    (re.compile(r"\bML\b"),                          "Machine Learning"),
    (re.compile(r"\bMPLS\b"),                        "Multiprotocol Label Switching"),
    (re.compile(r"\bMoU\b"),                         "Memorandum of Understanding"),
    (re.compile(r"\bMMR\b"),                         "Meet Me Room"),
 
    # ── N ────────────────────────────────────────────────────────────────────
    # N+1 / 2N — match the plus and slash literally
    (re.compile(r"\bN\+1\s*/\s*2N\b"),              "N plus one and two N redundancy"),
    (re.compile(r"\bN\+1\b"),                        "N plus one redundancy"),
    (re.compile(r"\b2N\b"),                          "two N redundancy"),
    (re.compile(r"\bNHA\b"),                         "National Highway Authority"),
    (re.compile(r"\bNGFW\b"),                        "Next Generation Firewall"),
    (re.compile(r"\bNPU\b"),                         "Neural Processing Unit"),
 
    # ── O ────────────────────────────────────────────────────────────────────
    (re.compile(r"\bOEM\b"),                         "Original Equipment Manufacturer"),
    (re.compile(r"\bOGRA\b"),                        "Oil and Gas Regulatory Authority"),
    (re.compile(r"\bOWASP\b"),                       "Open Web Application Security Project"),
 
    # ── P ────────────────────────────────────────────────────────────────────
    (re.compile(r"\bPAM\b"),                         "Privileged Access Management"),
    (re.compile(r"\bPCI DSS\b"),                     "Payment Card Industry Data Security Standard"),
    # PMO / EPMO — match slash literally
    (re.compile(r"\bEPMO\b"),                        "Enterprise Project Management Office"),
    (re.compile(r"\bPMO\b"),                         "Project Management Office"),
    (re.compile(r"\bPOE\b"),                         "Path of Entry"),
    (re.compile(r"\bPSX\b"),                         "Pakistan Stock Exchange"),
    (re.compile(r"\bPTA\b"),                         "Pakistan Telecommunication Authority"),
 
    # ── R ────────────────────────────────────────────────────────────────────
    (re.compile(r"\bRAG\b"),                         "Retrieval Augmented Generation"),
    (re.compile(r"\bRBAC\b"),                        "Role Based Access Control"),
    # RPO/RTO — match slash literally
    (re.compile(r"\bRPO/RTO\b"),                     "Recovery Point Objective and Recovery Time Objective"),
    (re.compile(r"\bRPO\b"),                         "Recovery Point Objective"),
    (re.compile(r"\bRTO\b"),                         "Recovery Time Objective"),
 
    # ── S ────────────────────────────────────────────────────────────────────
    (re.compile(r"\bSECP\b"),                        "Securities and Exchange Commission of Pakistan"),
    (re.compile(r"\bSIEM\b"),                        "Security Information and Event Management"),
    (re.compile(r"\bSLA\b"),                         "Service Level Agreement"),
    (re.compile(r"\bSTZA\b"),                        "Special Technology Zones Authority"),
 
    # ── T ────────────────────────────────────────────────────────────────────
    (re.compile(r"\bTCCD\b"),                        "Tier Certification of Constructed Design"),
    # Tier III/IV — match slash literally (Roman normalization handles III/IV separately)
    (re.compile(r"\bTier\s+III/IV\b", re.IGNORECASE), "Tier three and four"),
    (re.compile(r"\bTier\s+III\b", re.IGNORECASE), "Tier three"),
    (re.compile(r"\bTier\s+IV\b", re.IGNORECASE), "Tier four"),
 
    # ── U ────────────────────────────────────────────────────────────────────
    # UI/UX — match slash literally
    (re.compile(r"\bUI/UX\b"),                       "User Interface and User Experience"),
    (re.compile(r"\bUTM\b"),                         "Unified Threat Management"),
 
    # ── V ────────────────────────────────────────────────────────────────────
    (re.compile(r"\bVRF\b"),                         "Variable Refrigerant Flow"),
 
    # ── W ────────────────────────────────────────────────────────────────────
    (re.compile(r"\bWAF\b"),                         "Web Application Firewall"),
 
    # ── X ────────────────────────────────────────────────────────────────────
    (re.compile(r"\bXDR\b"),                         "Extended Detection and Response"),

    (re.compile(r"\bNVIDIA\b", re.IGNORECASE),       "invidia"),
    (re.compile(r"\bHuawei\b", re.IGNORECASE),       "wah way"),
    (re.compile(r"\bKubernetes\b", re.IGNORECASE),   "koober netties"),
]

def normalize_abbreviations_for_speech(text: str) -> tuple[str, list[tuple[str, str]]]:
    """Expand known abbreviations/short-forms to their spoken equivalents."""
    if not text or ARABIC_RE.search(text):
        return text, []

    applied_changes: list[tuple[str, str]] = []
    result = text

    for pattern, replacement in _ABBREVIATION_MAPPINGS:
        def _replace(match: re.Match, rep: str = replacement) -> str:
            original = match.group(0)
            applied_changes.append((original, rep))
            return rep

        result = pattern.sub(_replace, result)

    return result, applied_changes


# Parenthetical acronyms that follow their spelled-out form, e.g.
# "Disaster Recovery as a Service (DRaaS)" — the LLM writes the full form AND the
# short form, and expanding the short form would speak the full form twice. Drop
# the parenthetical when it looks like an acronym (a single token, >=2 uppercase
# letters), so only the full form is spoken. Legitimate parentheticals like
# "(for example)" or "(e.g.)" are left untouched.
_PAREN_ABBR_PATTERN = re.compile(r"\s*\(([A-Za-z0-9./+&-]{2,15})\)")


def strip_parenthetical_abbreviations(text: str) -> tuple[str, list[tuple[str, str]]]:
    """Remove trailing acronyms in parentheses so the avatar doesn't repeat them."""
    if not text:
        return text, []

    applied_changes: list[tuple[str, str]] = []

    def _replace(match: re.Match[str]) -> str:
        inner = match.group(1)
        if sum(1 for c in inner if c.isupper()) >= 2:
            applied_changes.append((match.group(0).strip(), ""))
            return ""
        return match.group(0)

    return _PAREN_ABBR_PATTERN.sub(_replace, text), applied_changes


_TIER_SLASH_PATTERN = re.compile(
    r"\b[Tt]ier\s+(II|III|IV|V|VI|VII|VIII|IX|X|XI|XII|XIII|XIV|XV|XVI|XVII|XVIII|XIX|XX)\s*/\s*(II|III|IV|V|VI|VII|VIII|IX|X|XI|XII|XIII|XIV|XV|XVI|XVII|XVIII|XIX|XX)\b"
)
_ROMAN_SLASH_PATTERN = re.compile(
    r"\b(II|III|IV|V|VI|VII|VIII|IX|X|XI|XII|XIII|XIV|XV|XVI|XVII|XVIII|XIX|XX)\s*/\s*(II|III|IV|V|VI|VII|VIII|IX|X|XI|XII|XIII|XIV|XV|XVI|XVII|XVIII|XIX|XX)\b"
)
_ROMAN_SINGLE_PATTERN = re.compile(
    r"\b(II|III|IV|V|VI|VII|VIII|IX|X|XI|XII|XIII|XIV|XV|XVI|XVII|XVIII|XIX|XX)\b"
)


# STT sometimes drops the "co-" prefix from "colocation" (heard as plain
# "location") since it's an uncommon term for the model's language priors.
# Fix the specific known mishearing rather than guessing at broader spelling
# variants, so genuine "location" queries (e.g. "what's your location") are
# left untouched.
_STT_TERM_FIXES = [
    (re.compile(r"\blocation(\s+services?)\b", re.IGNORECASE), r"colocation\1"),
    (re.compile(r"لوکیشن(\s*سروسز?)"), r"کولوکیشن\1"),
]


def correct_stt_domain_terms(text: str) -> str:
    """Fix known STT mishearings of Sky47-specific domain terms."""
    if not text:
        return text
    corrected = text
    for pattern, replacement in _STT_TERM_FIXES:
        corrected = pattern.sub(replacement, corrected)
    return corrected


def detect_language(text: str) -> str:
    """Detect if text is Urdu (Arabic script) or English."""
    if ARABIC_RE.search(text):
        return "ur"
    return "en"


def normalize_roman_numerals_for_speech(text: str) -> tuple[str, list[tuple[str, str]]]:
    if not text or ARABIC_RE.search(text):
        return text, []

    applied_changes: list[tuple[str, str]] = []

    def _replace_tier_slash(match: re.Match[str]) -> str:
        left, right = match.group(1), match.group(2)
        original = match.group(0)
        replacement = f"tier {_ROMAN_TO_ORDINAL[left]} and {_ROMAN_TO_ORDINAL[right]}"
        applied_changes.append((original, replacement))
        return replacement

    def _replace_roman_slash(match: re.Match[str]) -> str:
        left, right = match.group(1), match.group(2)
        original = match.group(0)
        replacement = f"{_ROMAN_TO_ORDINAL[left]} and {_ROMAN_TO_ORDINAL[right]}"
        applied_changes.append((original, replacement))
        return replacement

    def _replace_roman_single(match: re.Match[str]) -> str:
        original = match.group(1)
        replacement = _ROMAN_TO_CARDINAL[original]
        applied_changes.append((original, replacement))
        return replacement

    normalized = _TIER_SLASH_PATTERN.sub(_replace_tier_slash, text)
    normalized = _ROMAN_SLASH_PATTERN.sub(_replace_roman_slash, normalized)
    normalized = _ROMAN_SINGLE_PATTERN.sub(_replace_roman_single, normalized)
    return normalized, applied_changes


# def roman_numeral_tts_transform(text_stream: AsyncIterable[str]) -> AsyncIterable[str]:
#     async def _transform() -> AsyncIterable[str]:
#         stream_tail = ""
#         tail_size = 64

#         async for chunk in text_stream:
#             combined = stream_tail + chunk
#             if len(combined) <= tail_size:
#                 stream_tail = combined
#                 continue

#             safe_text = combined[:-tail_size]
#             stream_tail = combined[-tail_size:]
#             normalized, changes = normalize_roman_numerals_for_speech(safe_text)
#             if changes:
#                 preview = "; ".join(
#                     f"{before} -> {after}" for before, after in changes[:5]
#                 )
#                 if len(changes) > 5:
#                     preview += f"; ... ({len(changes)} changes total)"
#                 logger.info("Voice TTS Roman normalization applied: %s", preview)
#             if normalized:
#                 yield normalized

#         if stream_tail:
#             normalized_tail, changes = normalize_roman_numerals_for_speech(stream_tail)
#             if changes:
#                 preview = "; ".join(
#                     f"{before} -> {after}" for before, after in changes[:5]
#                 )
#                 if len(changes) > 5:
#                     preview += f"; ... ({len(changes)} changes total)"
#                 logger.info("Voice TTS Roman normalization applied: %s", preview)
#             if normalized_tail:
#                 yield normalized_tail

#     return _transform()


def _apply_tts_normalizations(text: str, *, tail: bool = False) -> str:
    """Strip parenthetical acronyms, expand abbreviations, normalize Roman numerals."""
    suffix = " (tail)" if tail else ""

    # Step 0: drop repeated "(ABBR)" so the full form isn't spoken twice
    text, paren_changes = strip_parenthetical_abbreviations(text)
    if paren_changes:
        preview = "; ".join(f"{b} -> (dropped)" for b, _ in paren_changes[:5])
        logger.info("TTS parenthetical strip%s: %s", suffix, preview)

    # Step 1: abbreviations
    text, abbr_changes = normalize_abbreviations_for_speech(text)
    if abbr_changes:
        preview = "; ".join(f"{b} -> {a}" for b, a in abbr_changes[:5])
        logger.info("TTS abbreviation expansion%s: %s", suffix, preview)

    # Step 2: Roman numerals
    text, roman_changes = normalize_roman_numerals_for_speech(text)
    if roman_changes:
        preview = "; ".join(f"{b} -> {a}" for b, a in roman_changes[:5])
        logger.info("TTS Roman normalization%s: %s", suffix, preview)

    return text


def tts_text_transform(text_stream: AsyncIterable[str]) -> AsyncIterable[str]:
    """Stream transform: strip parenthetical acronyms, expand abbreviations, and
    normalize Roman numerals.

    Buffering only ever splits the stream at a whitespace boundary and holds back
    at least ``min_tail`` characters, so multi-token patterns ("Tier III",
    "PCI DSS", "(DRaaS)", "24/7") are never cut across a chunk boundary — cutting
    mid-token is what made "Tier III" come out as "Tier two I".
    """
    async def _transform() -> AsyncIterable[str]:
        buffer = ""
        min_tail = max(8, int(os.getenv("APP_TTS_TEXT_TAIL_SIZE", "24")))

        async for chunk in text_stream:
            buffer += chunk
            if len(buffer) <= min_tail:
                continue

            # Cut at the last whitespace that leaves >= min_tail chars buffered,
            # so no token near the boundary is split. Keep the whitespace on the
            # buffered side so a following "(ABBR)" can still be stripped.
            cut = find_safe_cut(buffer, min_tail)
            if cut == -1:
                continue

            safe_text = buffer[:cut]
            buffer = buffer[cut:]

            normalized = _apply_tts_normalizations(safe_text)
            if normalized:
                yield normalized

        if buffer:
            normalized = _apply_tts_normalizations(buffer, tail=True)
            if normalized:
                yield normalized

    return _transform()


def build_system_prompt(
    language: str, context: str, template: str | None = None
) -> str:
    lang_instruction = (
        "Respond in Urdu using Arabic script."
        if language == "ur"
        else "Respond in English."
    )
    if not template:
        prompt_path = (
            Path(SYSTEM_PROMPT_PATH_URDU)
            if language == "ur"
            else Path(SYSTEM_PROMPT_PATH_ENGLISH)
        )
        if prompt_path.exists():
            template = prompt_path.read_text(encoding="utf-8")

    if template:
        return template.format(
            language_instruction=lang_instruction,
            context=context,
        )
    return f"""{lang_instruction}
Use the following context to answer the user's question. If the context does not contain relevant information, say so honestly.

Context:
{context}"""


def _read_prompt_template(path_value: str | None, *, language_label: str) -> str | None:
    """Read prompt template from common locations with clear diagnostics."""
    if not path_value:
        return None

    path = Path(path_value)
    candidates = [path]

    # If relative, also try paths relative to this file and repository backend dir.
    if not path.is_absolute():
        base_dir = Path(__file__).resolve().parent
        candidates.extend(
            [
                base_dir / path,
                base_dir.parent / "backend" / path,
            ]
        )

    for candidate in candidates:
        if candidate.exists():
            if not candidate.is_file():
                logger.warning(
                    "%s system prompt path exists but is not a file: %s",
                    language_label,
                    candidate,
                )
                continue

            try:
                template = candidate.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                logger.warning(
                    "Failed to read %s system prompt from %s: %s",
                    language_label,
                    candidate,
                    exc,
                )
                continue

            logger.info("Loaded %s system prompt from %s", language_label, candidate)
            return template

    logger.warning(
        "%s system prompt file not found. Checked: %s",
        language_label,
        ", ".join(str(p) for p in candidates),
    )
    return None


# ── UpliftAI TTS: sentence-level chunking ────────────────────────


class SentenceChunkedUpliftTTS(upliftai.TTS):
    """UpliftAI TTS that synthesizes one sentence at a time.

    UpliftAI's WebSocket accepts exactly one message — `synthesize`, carrying a
    COMPLETE text string. There is no incremental-text frame, so its
    `streaming=True` capability refers to streaming audio OUT, not text IN.
    The plugin's SynthesizeStream drains the whole word_stream (which only ends
    on the turn's flush sentinel) before sending anything, so TTS does not start
    until the LLM has finished the entire response.

    Measured on a long Urdu reply: 3.84s before the first audio byte, versus
    1.30s for the first sentence alone.

    Declaring non-streaming makes livekit-agents wrap this in a tts.StreamAdapter
    with a blingfire SentenceTokenizer (see voice/agent.py), which calls
    synthesize() per sentence as each sentence completes. Each call is a
    ChunkedStream reusing the same warm WebSocketClient, so the ~240ms TTFB and
    the persistent connection are both preserved — audio simply starts after
    sentence one instead of after the whole turn.

    blingfire splits on the Urdu full stop (U+06D4 "۔") and question mark
    (U+061F "؟") correctly, so this works for the Urdu path, not just English.
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        # Read-only via the `capabilities` property; the private attr is the
        # only way to flip it after construction.
        self._capabilities.streaming = False
        self._prewarm_task: asyncio.Task | None = None

    def prewarm(self) -> None:
        """Open the WebSocket during session setup instead of on the first turn.

        livekit-agents calls this on stt/llm/tts when an activity starts (see
        voice/agent_activity.py). The UpliftAI plugin doesn't implement it, so
        the socket was being dialled lazily inside the first synthesize() —
        measured 620-690ms of connect+auth charged to the first reply, plus up
        to 100ms of quantization from the plugin's `await asyncio.sleep(0.1)`
        readiness poll. Connecting here overlaps that with session setup.
        """

        async def _prewarm() -> None:
            try:
                if self._client is None:
                    self._client = _UpliftWebSocketClient(self._opts)
                await self._client.connect()
                logger.info("Prewarm: UpliftAI TTS socket ready")
            except Exception as e:
                # Non-fatal: the plugin still connects lazily on first use.
                logger.warning("Prewarm: UpliftAI TTS connect failed: %s", e)

        self._prewarm_task = asyncio.create_task(_prewarm())


# ── Embedding helper ─────────────────────────────────────────────


class _EmbeddingService:
    def __init__(self, model_name: str):
        from sentence_transformers import SentenceTransformer

        self.model = SentenceTransformer(model_name)

    def embed_query(self, query: str) -> list[float]:
        return self.model.encode([query], normalize_embeddings=True).tolist()[0]

    async def embed_query_async(self, query: str) -> list[float]:
        """Non-blocking embed: runs CPU-bound encode in a thread pool."""
        import asyncio
        return await asyncio.to_thread(self.embed_query, query)


# ── RAG Agent class ──────────────────────────────────────────────


class ChatbotAgent(Agent):
    """Agent with RAG context injection via llm_node override."""

    def __init__(
        self,
        *,
        instructions: str = "",
        embedding_service=None,
        qdrant_client=None,
        system_prompt_template: str | None = None,
        default_language: str = "en",
        langfuse=None,
        room_name: str = "",
        room=None,
        a2f_client=None,
        a2f_sample_rate: int = 0,
        a2f_playback_delay: float = 0.0,
        glossary: dict[str, str] | None = None,
    ) -> None:
        super().__init__(instructions=instructions)
        self._embedding = embedding_service
        self._qdrant = qdrant_client
        self._system_prompt_template = system_prompt_template
        self._default_language = default_language
        self._langfuse = langfuse
        self._room_name = room_name
        self._room = room
        self._a2f = a2f_client
        self._a2f_sample_rate = a2f_sample_rate
        self._a2f_playback_delay = a2f_playback_delay
        self._a2f_drain_tasks: list[asyncio.Task] = []
        # One lipsync timeline per agent turn: clips append at exact
        # audio-duration offsets; the frontend anchors it to the playback
        # start marker published from the agent_started_speaking event.
        self._turn_uid: str = ""
        self._turn_offset: float = 0.0
        self._turn_active: bool = False
        # Completion future of the turn's most recent clip: the next clip's
        # publishes gate on it so the timeline stays monotonic even if a
        # short clip's burst returns before a long one's.
        self._turn_prev_pub: asyncio.Future | None = None
        self._glossary = glossary or {}
        # Pre-started embedding tasks: keyed by transcript text.
        # Populated by prestart_embed() on the user_input_transcribed event.
        self._pending_embeds: dict[str, asyncio.Task] = {}

    def a2f_turn_ended(self) -> None:
        """Playback for the turn finished/interrupted — next sentence starts a new timeline."""
        self._turn_active = False
        # Frames for an ended turn are discarded client-side, but in-flight
        # clip drains still occupy NIM stream slots and the publish chain —
        # abort them all so the next turn starts on a free pipe.
        for task in self._a2f_drain_tasks:
            if not task.done():
                task.cancel()
        self._a2f_drain_tasks.clear()
        self._turn_prev_pub = None

    def prestart_embed(self, text: str) -> None:
        """Kick off embedding immediately when transcription is available.

        Called from the user_input_transcribed event handler — overlaps the
        CPU-bound embed with any overhead before llm_node is invoked (~50-200ms
        head start, potentially more with Deepgram streaming).
        """
        if not self._embedding or not text:
            return
        text = correct_stt_domain_terms(text)
        if text in self._pending_embeds:
            return
        # Cap cache size to avoid accumulating stale tasks
        if len(self._pending_embeds) >= 3:
            oldest_key = next(iter(self._pending_embeds))
            old_task = self._pending_embeds.pop(oldest_key)
            if not old_task.done():
                old_task.cancel()
        try:
            task = asyncio.get_event_loop().create_task(
                self._embedding.embed_query_async(text)
            )
            self._pending_embeds[text] = task
            logger.info("RAG: pre-started embedding task for transcript (%d chars)", len(text))
        except RuntimeError:
            pass  # No running event loop — llm_node will embed normally

    def _make_lipsync_publisher(
        self,
        uid: str,
        offset: float,
        after: asyncio.Future | None = None,
        clip_end: list | None = None,
    ):
        """Batch callback for one clip: re-times frames onto the turn timeline.

        `after` gates the first publish on the previous clip finishing, so
        the appended timeline stays time-sorted (the frontend's playback
        cursor assumes monotonic frames). `clip_end` is a one-item cell set
        at cut time to the clip's real audio length: the NIM appends ~1.5s
        of silence to every clip, and those rest-pose frames would overlap
        the next clip's range.
        """

        first_pub = [True]

        async def publish(names, frames) -> None:
            if after is not None:
                await after
            if clip_end is not None and clip_end[0] is not None:
                frames = [f for f in frames if f[0] <= clip_end[0] + 0.05]
            if frames and first_pub[0]:
                first_pub[0] = False
                logger.info(
                    "A2F-LAT first frames published (turn %s, offset %.2fs)", uid, offset
                )
            msg = {
                "uid": uid,
                "frames": [[round(f[0] + offset, 3), *f[1:]] for f in frames],
            }
            if names:
                msg["names"] = names
            await self._room.local_participant.send_text(
                json.dumps(msg, separators=(",", ":")), topic="lipsync.frames"
            )

        return publish

    async def tts_node(self, text, model_settings):
        """Tap TTS audio and stream Audio2Face blendshapes for lipsync.

        Audio frames pass through to the room (via the playback-delay gate
        below); each frame's PCM is also fed to Audio2Face-3D as a series of
        per-sentence CLIPS — the NIM's contract is clip-in/burst-out, so
        end_of_audio is sent at every synthesis gap and each sentence's
        frames come back while the next sentence is still synthesizing.
        Frames are published onto one turn-relative timeline the frontend
        anchors to the playback-start marker.

        A2F failures only cost blendshapes (frontend falls back to visemes).
        """
        logger.info(
            "A2F tts_node invoked (a2f=%s, room=%s, turn_active=%s)",
            self._a2f is not None, self._room is not None, self._turn_active,
        )
        if self._a2f is None or self._room is None:
            async for frame in Agent.default.tts_node(self, text, model_settings):
                yield frame
            return

        # ── Turn timeline bookkeeping ──
        if not self._turn_active:
            self._turn_uid = f"t{int(time.monotonic() * 1000)}"
            self._turn_offset = 0.0
            self._turn_active = True
        uid = self._turn_uid

        # ── One A2F clip per sentence ──
        # The NIM's documented contract is clip-in/burst-out: it emits NO
        # frames until end_of_audio (verified against the proto comment and
        # empirically with 1x-paced input). A single session per turn
        # therefore gates ALL frames on the full reply's synthesis. Instead,
        # a clip is cut at every synthesis gap — the TTS synthesizes
        # sentence by sentence, so audio arrival pauses between sentences —
        # and end_of_audio goes out immediately: sentence N's burst returns
        # while sentence N+1 is still synthesizing, keeping frames ahead of
        # the delay-gated playback from the first word.
        GAP_CUT_S = 0.35  # audio arrival pause that ends a clip
        MIN_CLIP_S = 0.5  # don't cut on intra-sentence delivery jitter
        MAX_CLIP_S = 12.0  # bound burst latency on run-on sentences
        # Time-to-first-frame is proportional to the FIRST clip's length
        # (cut + upload + inference + 90fps burst drain), so it stays small
        # enough that its frames beat the playback-delay gate even when the
        # TTS floods the whole reply in a few seconds.
        MAX_FIRST_CLIP_S = 3.0

        base_offset = self._turn_offset
        loop = asyncio.get_running_loop()
        # The NIM serves a fixed number of concurrent streams
        # (stream_number in its deployment config, currently 3). Flood
        # synthesis can cut a long reply into many clips within a second —
        # opened all at once they die with "No available stream". Two slots
        # (third left as slack for a lingering abort) and clips queue here
        # while their audio buffers.
        slots = asyncio.Semaphore(2)

        session = None
        open_task: asyncio.Task | None = None
        failed_opens = 0  # consecutive — 2 strikes disables A2F for the call
        buffered: list[bytes] = []
        sample_rate = 0
        total_samples = 0
        clip_start_samples = 0
        clip_end_marker: list | None = None
        clip_opened_at = 0.0
        last_audio_at = 0.0
        stream_done = False
        t0 = time.monotonic()

        def _finish_clip(s, dur: float, end_marker: list, started: float) -> None:
            """Send end_of_audio and drain the burst in the background."""
            end_marker[0] = dur
            done: asyncio.Future = loop.create_future()
            self._turn_prev_pub = done

            async def _drain():
                try:
                    total = await asyncio.wait_for(s.finish(), timeout=15.0)
                    logger.info(
                        "A2F: clip drained %d frames (%.2fs audio, %.2fs wall, turn %s)",
                        total, dur, time.monotonic() - started, uid,
                    )
                except asyncio.CancelledError:
                    try:
                        await s.abort()
                    except Exception:
                        pass
                    logger.info("A2F clip drain aborted (turn %s ended)", uid)
                except Exception as e:
                    logger.warning("A2F clip drain failed: %s", e)
                finally:
                    slots.release()
                    # Always release the publish chain — a stuck clip must
                    # cost its own frames, not every clip after it.
                    if not done.done():
                        done.set_result(None)

            self._a2f_drain_tasks.append(asyncio.create_task(_drain()))

        def _cut_clip(end_samples: int | None = None) -> None:
            # end_samples: clip end in cumulative TTS samples — defaults to
            # everything received, but a capped backlog flush cuts earlier.
            nonlocal session, clip_start_samples
            s, session = session, None
            end = total_samples if end_samples is None else end_samples
            dur = (end - clip_start_samples) / sample_rate
            clip_start_samples = end
            _finish_clip(s, dur, clip_end_marker, clip_opened_at)

        def _max_clip_s() -> float:
            first = base_offset == 0.0 and clip_start_samples == 0
            return MAX_FIRST_CLIP_S if first else MAX_CLIP_S

        async def _open_and_flush() -> None:
            nonlocal session, failed_opens, clip_start_samples
            nonlocal clip_end_marker, clip_opened_at, open_task
            # Wait for a NIM stream slot; audio keeps buffering meanwhile.
            # On success the slot is owned by the clip and released when its
            # drain completes (_finish_clip).
            await slots.acquire()
            offset = base_offset + clip_start_samples / sample_rate
            end_marker: list = [None]
            on_batch = self._make_lipsync_publisher(
                uid, offset, after=self._turn_prev_pub, clip_end=end_marker
            )
            s = None
            try:
                # Hard deadline: an unreachable NIM (VM stopped, tunnel down)
                # must cost visemes, never seconds — gRPC's own reconnect
                # backoff can otherwise stall opens for tens of seconds.
                s = await asyncio.wait_for(
                    self._a2f.open_stream(sample_rate=sample_rate, on_batch=on_batch),
                    timeout=4.0,
                )
                # Flush the backlog with pop() (frames may keep appending
                # while we await writes), but at most ONE clip's worth: a
                # slot wait during flood synthesis can accumulate the whole
                # rest of the reply, and fusing it into a single giant clip
                # blows the drain timeout and the burst-drain budget.
                cap = int(_max_clip_s() * sample_rate)
                flushed = 0
                while buffered and flushed < cap:
                    chunk = buffered.pop(0)
                    flushed += len(chunk) // 2  # 16-bit mono samples
                    await s.write(chunk)
                clip_end_marker = end_marker
                clip_opened_at = time.monotonic()
                session = s
                failed_opens = 0
                logger.info("A2F clip opened (turn %s, offset %.2fs)", uid, offset)
                if flushed >= cap:
                    # Clip filled straight from the backlog — cut at exactly
                    # what was flushed and chain the next clip for the rest.
                    # Registering the chain as open_task stops the main loop
                    # spawning a competing open for the same audio.
                    _cut_clip(clip_start_samples + flushed)
                    if buffered:
                        open_task = asyncio.create_task(_open_and_flush())
                        self._a2f_drain_tasks.append(open_task)
                elif stream_done:
                    # Synthesis ended while the open was in flight (short
                    # final clip) — nobody is left to cut it but us.
                    _cut_clip()
            except asyncio.CancelledError:
                slots.release()
                if s is not None and session is not s:
                    asyncio.create_task(_abort_quietly(s))
            except Exception as e:
                slots.release()
                failed_opens += 1
                buffered.clear()
                # Skip the lost audio on the timeline: the next clip's frames
                # must map to where ITS audio plays, not the failed clip's.
                clip_start_samples = total_samples
                logger.warning(
                    "A2F clip open failed (strike %d): %s — visemes bridge",
                    failed_opens, e,
                )

        async def _gap_watchdog() -> None:
            # Proactive cut: end_of_audio goes out GAP_CUT_S after the last
            # audio of a sentence, not when the next sentence's first frame
            # eventually shows up — the NIM processes sentence N during
            # sentence N+1's synthesis.
            while True:
                await asyncio.sleep(0.1)
                if session is None or not sample_rate:
                    continue
                dur = (total_samples - clip_start_samples) / sample_rate
                idle = time.monotonic() - last_audio_at
                if dur >= _max_clip_s() or (dur >= MIN_CLIP_S and idle >= GAP_CUT_S):
                    _cut_clip()

        watchdog = asyncio.create_task(_gap_watchdog())

        # ── Playback delay gate ──
        # Audio frames are HELD for a fixed window while A2F consumes them
        # immediately: blendshapes then permanently lead playback and the
        # mouth never runs dry mid-turn. The loop keeps consuming (and
        # feeding A2F) during the hold — only the yields are gated.
        delay = self._a2f_playback_delay if self._a2f is not None else 0.0
        release_at: float | None = None
        held: list = []

        async def _abort_quietly(s) -> None:
            try:
                await s.abort()
            except Exception:
                pass

        try:
            async for frame in Agent.default.tts_node(self, text, model_settings):
                # Opens run as background tasks — audio NEVER waits on them.
                if open_task is not None and open_task.done():
                    open_task = None
                sample_rate = frame.sample_rate
                total_samples += frame.samples_per_channel
                last_audio_at = time.monotonic()
                if failed_opens < 2:
                    if session is None:
                        buffered.append(bytes(frame.data))
                        if open_task is None:
                            open_task = asyncio.create_task(_open_and_flush())
                            self._a2f_drain_tasks.append(open_task)
                    else:
                        try:
                            await session.write(bytes(frame.data))
                        except Exception as e:
                            logger.warning("A2F clip write failed: %s", e)
                            failed_opens += 1
                            s, session = session, None
                            clip_start_samples = total_samples
                            slots.release()
                            asyncio.create_task(_abort_quietly(s))
                    # Flood synthesis outruns the 100ms watchdog by seconds —
                    # enforce the clip-size cap inline at frame arrival.
                    if session is not None and (
                        (total_samples - clip_start_samples) / sample_rate
                        >= _max_clip_s()
                    ):
                        _cut_clip()
                if delay <= 0:
                    yield frame
                else:
                    if release_at is None:
                        release_at = time.monotonic() + delay
                    held.append(frame)
                    if time.monotonic() >= release_at:
                        while held:
                            yield held.pop(0)
            # Synthesis finished before the gate opened (short replies):
            # wait out the remainder, then release everything.
            if held:
                remaining = (release_at or 0) - time.monotonic()
                if remaining > 0:
                    await asyncio.sleep(remaining)
                while held:
                    yield held.pop(0)
        finally:
            stream_done = True
            watchdog.cancel()

            # Advance the turn timeline by this call's EXACT audio length,
            # so a follow-up call's frames land where its audio actually plays.
            if sample_rate:
                self._turn_offset = base_offset + total_samples / sample_rate

            # Cut the final clip. If an open is still in flight (short final
            # sentence), _open_and_flush cuts on completion via stream_done.
            if session is not None:
                _cut_clip()
            logger.info(
                "A2F tts_node done: %.2fs audio in %.2fs (turn %s)",
                total_samples / sample_rate if sample_rate else 0.0,
                time.monotonic() - t0, uid,
            )

    async def llm_node(self, chat_ctx, tools, model_settings):
        """Override LLM node to inject RAG context before calling the LLM."""
        logger.info("llm_node called — %d items in chat context", len(chat_ctx.items))

        # ── 1. Extract last user message ─────────────────────────────────────
        user_text = None
        user_item = None
        for item in reversed(chat_ctx.items):
            if hasattr(item, "role") and item.role == "user":
                if hasattr(item, "content") and isinstance(item.content, str):
                    user_text = item.content
                    user_item = item
                    break
                # Handle list content (e.g. multimodal)
                if hasattr(item, "content") and isinstance(item.content, list):
                    for idx, part in enumerate(item.content):
                        if isinstance(part, str):
                            user_text = part
                            user_item = (item, idx)
                            break
                        if hasattr(part, "text"):
                            user_text = part.text
                            user_item = (item, idx, "text")
                            break
                    if user_text:
                        break

        # Fix known STT mishearings (e.g. "colocation" heard as "location")
        # before using the text for RAG retrieval or sending it to the LLM.
        if user_text:
            corrected_text = correct_stt_domain_terms(user_text)
            if corrected_text != user_text:
                logger.info("STT correction applied: %r -> %r", user_text, corrected_text)
                if isinstance(user_item, tuple):
                    if len(user_item) == 3:
                        item, idx, _ = user_item
                        item.content[idx].text = corrected_text
                    else:
                        item, idx = user_item
                        item.content[idx] = corrected_text
                elif user_item is not None:
                    user_item.content = corrected_text
                user_text = corrected_text

        language = detect_language(user_text) if user_text else self._default_language
        context_text = ""

        # ── 2. Open a LangFuse trace for this turn ───────────────────────────
        lf_trace = None
        lf_generation = None
        if self._langfuse and user_text:
            lf_trace = self._langfuse.start_span(name="voice_rag_turn")
            lf_trace.update_trace(
                input=user_text,
                session_id=self._room_name,
                metadata={"language": language, "room": self._room_name},
            )

        # ── 3. RAG retrieval ─────────────────────────────────────────────────
        if user_text and self._embedding and self._qdrant:
            logger.info("RAG: querying for user_text=%r", user_text[:100])

            lf_retrieval = None
            if lf_trace:
                lf_retrieval = lf_trace.start_span("qdrant_retrieval", input=user_text)

            try:
                # Use pre-started embedding task if available (overlapped with STT)
                _pending = self._pending_embeds.pop(user_text, None)
                if _pending is not None:
                    logger.info("RAG: awaiting pre-started embedding task (overlapped with STT)")
                    query_vector = await _pending
                else:
                    query_vector = await self._embedding.embed_query_async(user_text)
                logger.info(
                    "RAG: embedding ready, querying Qdrant collection=%s",
                    QDRANT_COLLECTION,
                )

                response = await self._qdrant.query_points(
                    collection_name=QDRANT_COLLECTION,
                    query=query_vector,
                    limit=TOP_K,
                )

                logger.info("RAG: got %d results from Qdrant", len(response.points))

                if not response.points:
                    logger.warning("RAG: no results found — collection may be empty")

                chunks = [r.payload["text"] for r in response.points]
                context_text = "\n\n".join(chunks)
                sources = list(
                    set(r.payload.get("source", "") for r in response.points)
                )
                scores = [r.score for r in response.points]
                logger.info(
                    "RAG: prepared %d chunks, sources=%s",
                    len(chunks),
                    sources,
                )

                if lf_retrieval:
                    lf_retrieval.update(output={
                        "chunk_count": len(chunks),
                        "sources": sources,
                        "scores": scores,
                    })

            except Exception as e:
                logger.error(
                    "RAG retrieval failed: %s (type=%s)",
                    e,
                    type(e).__name__,
                    exc_info=True,
                )
                if lf_retrieval:
                    lf_retrieval.update(metadata={"error": str(e)})
            finally:
                if lf_retrieval:
                    lf_retrieval.end()
        else:
            logger.warning(
                "RAG skipped: user_text=%s, embedding=%s, qdrant=%s",
                bool(user_text),
                bool(self._embedding),
                bool(self._qdrant),
            )

        # ── 3b. Force-inject glossary definitions for any abbreviation the ──
        # user asked about, regardless of whether semantic retrieval above
        # happened to surface a chunk that actually defines it. See glossary.py.
        if user_text and self._glossary:
            glossary_matches = find_glossary_matches(user_text, self._glossary)
            if glossary_matches:
                glossary_block = format_glossary_block(glossary_matches)
                context_text = (
                    f"{glossary_block}\n\n{context_text}" if context_text else glossary_block
                )
                logger.info("Glossary: injected definitions for %s", list(glossary_matches))

        # ── 4. Inject system prompt ──────────────────────────────────────────
        # Always inject so agent identity/persona remains stable even when
        # retrieval fails or context is empty.
        system_prompt = build_system_prompt(
            language, context_text, self._system_prompt_template
        )
        chat_ctx.items[:] = [
            item
            for item in chat_ctx.items
            if not (hasattr(item, "role") and item.role == "system")
        ]
        chat_ctx.items.insert(0, ChatMessage(role="system", content=[system_prompt]))
        logger.info("Injected system prompt for language=%s", language)

        # ── 5. LLM call — wrap stream to capture output for tracing ──────────
        if lf_trace:
            # Snapshot the messages that are about to be sent to the LLM
            lf_messages = []
            for item in chat_ctx.items:
                if not hasattr(item, "role"):
                    continue
                content = item.content
                if isinstance(content, list):
                    content = " ".join(
                        p if isinstance(p, str) else (p.text if hasattr(p, "text") else "")
                        for p in content
                    )
                lf_messages.append({"role": item.role, "content": content})

            lf_generation = lf_trace.start_generation(
                "llm_completion",
                model=LLM_MODEL,
                input=lf_messages,
                model_parameters={"temperature": 0.7, "max_tokens": 512},
            )

        base_stream = Agent.default.llm_node(self, chat_ctx, tools, model_settings)

        if not lf_trace:
            return base_stream

        # Wrap the async stream: yield every chunk unchanged, accumulate text,
        # then end the generation + trace once the stream is exhausted.
        lf = self._langfuse  # capture for use inside the nested generator

        async def _traced_stream():
            full_output = ""
            try:
                async for chunk in base_stream:
                    # ChatChunk format used by livekit-plugins-openai
                    if hasattr(chunk, "choices") and chunk.choices:
                        delta = chunk.choices[0].delta
                        if hasattr(delta, "content") and delta.content:
                            full_output += delta.content
                    elif isinstance(chunk, str):
                        full_output += chunk
                    yield chunk
            finally:
                if lf_generation:
                    lf_generation.update(output=full_output)
                    lf_generation.end()
                if lf_trace:
                    lf_trace.update(output=full_output)
                    lf_trace.end()
                if lf:
                    lf.flush()

        return _traced_stream()


# ── Server setup ─────────────────────────────────────────────────

server = AgentServer(
    # 1 idle worker — each worker loads ~4.5GB of models into memory.
    # The framework maintains 1 ready process so the agent can accept jobs
    # immediately. When it picks up a job, a replacement is spawned (~10s).
    num_idle_processes=1,
    # Prewarm loads STT+TTS+Embedding from disk in parallel (~15-20s once models
    # are cached on disk). On a fresh volume, first-time HuggingFace downloads
    # (esp. the embedding model) can take several minutes — a too-short timeout
    # here kills the subprocess mid-download and spawns a replacement that starts
    # the download over, so it never finishes. Run `python download_models.py`
    # once to populate the models volume ahead of time; this timeout is just a
    # backstop for genuinely slow first-time downloads.
    initialize_process_timeout=600.0,
    # Raise memory warning threshold (actual worker usage is ~4.5GB)
    job_memory_warn_mb=5000,
    # Hard limit per worker — prevents framework from spawning a 4th worker
    # when 3 already exist (3 × 5GB = 15GB = Docker limit).
    job_memory_limit_mb=5000,
)


def prewarm(proc):
    """Prewarm: eagerly load ALL models.

    Models are pre-downloaded into the Docker image at /app/models (HF_HOME),
    so loading from disk takes ~10-15s. This runs once per worker process.
    In `start` mode, the worker stays alive and reuses loaded models for
    all subsequent sessions (no per-session loading delay).
    """
    t0 = time.monotonic()
    logger.info("Prewarming: loading all models from disk...")

    # VAD is small (~2MB), loads in < 1 second
    '''
    activation_threshold — the main sensitivity knob. Lower (e.g. 0.3) = more sensitive, 
    picks up quieter speech but may trigger on noise. Higher (e.g. 0.7) = less sensitive, 
    requires clearer speech but reduces false positives.
    '''
    
    proc.userdata["vad"] = silero.VAD.load(activation_threshold=0.7)
    logger.info("VAD loaded in %.1fs", time.monotonic() - t0)

    # Load STT, TTS, and embedding in PARALLEL (they are independent)
    def _load_stt():
        t = time.monotonic()
        stt_inst = WhisperSTT(
            model_size=ASR_MODEL,
            device=ASR_DEVICE,
            compute_type=ASR_COMPUTE_TYPE,
        )
        stt_inst._ensure_model()
        logger.info(
            "STT (faster-whisper %s) loaded in %.1fs", ASR_MODEL, time.monotonic() - t
        )
        return stt_inst

    def _load_tts():
        t = time.monotonic()
        # Load Urdu (male), English (male), and English Female voices
        tts_urdu = KokoroTTS(
            voice=TTS_VOICE_URDU,
            speed=TTS_SPEED,
        )
        tts_english = KokoroTTS(
            voice=TTS_VOICE_ENGLISH,
            speed=TTS_SPEED,
        )
        tts_english_female = KokoroTTS(
            voice=TTS_VOICE_ENGLISH_FEMALE,
            speed=TTS_SPEED,
        )
        logger.info(
            "TTS (Kokoro Urdu %s + English %s + English Female %s) loaded in %.1fs",
            TTS_VOICE_URDU, TTS_VOICE_ENGLISH, TTS_VOICE_ENGLISH_FEMALE, time.monotonic() - t,
        )
        return {"urdu": tts_urdu, "english": tts_english, "english_female": tts_english_female}

    def _load_mms_tts():
        t = time.monotonic()
        mms_model, mms_tokenizer = load_mms_model()
        tts_inst = MMSTTS(model=mms_model, tokenizer=mms_tokenizer)
        logger.info("TTS (MMS Urdu) loaded in %.1fs", time.monotonic() - t)
        return tts_inst

    def _load_embedding():
        t = time.monotonic()
        svc = _EmbeddingService(EMBEDDING_MODEL)
        logger.info(
            "Embedding (%s) loaded in %.1fs", EMBEDDING_MODEL, time.monotonic() - t
        )
        return svc

    def _build_glossary():
        # Scan every chunk in the knowledge base ONCE for "ABBR (Full Form)"
        # patterns and cache the result — see glossary.py for why this is
        # needed (top-k semantic retrieval can easily miss the one chunk that
        # actually defines a frequently-mentioned abbreviation like "SOC").
        # Uses the SYNC QdrantClient (safe here — prewarm is a blocking
        # context, unlike the per-session async handler below).
        t = time.monotonic()
        try:
            from qdrant_client import QdrantClient

            client = QdrantClient(
                host=QDRANT_HOST,
                port=QDRANT_PORT,
                api_key=QDRANT_API_KEY or None,
                https=False,
            )
            all_text: list[str] = []
            offset = None
            while True:
                points, offset = client.scroll(
                    collection_name=QDRANT_COLLECTION,
                    limit=256,
                    with_payload=True,
                    with_vectors=False,
                    offset=offset,
                )
                for p in points:
                    text = (p.payload or {}).get("text")
                    if text:
                        all_text.append(text)
                if offset is None:
                    break
            glossary = extract_glossary("\n".join(all_text))
            logger.info(
                "Glossary built: %d terms from %d chunks in %.1fs",
                len(glossary), len(all_text), time.monotonic() - t,
            )
            return glossary
        except Exception as e:
            logger.warning("Glossary build failed (non-fatal): %s", e)
            return {}

    with ThreadPoolExecutor(max_workers=5) as pool:
        stt_future = pool.submit(_load_stt)
        tts_future = pool.submit(_load_tts)
        mms_future = pool.submit(_load_mms_tts)
        emb_future = pool.submit(_load_embedding)
        glossary_future = pool.submit(_build_glossary)

        proc.userdata["whisper_stt"] = stt_future.result()
        proc.userdata["kokoro_tts"] = tts_future.result()  # Dict with "urdu" and "english" keys
        proc.userdata["mms_tts"] = mms_future.result()
        proc.userdata["embedding"] = emb_future.result()
        proc.userdata["glossary"] = glossary_future.result()

    # Store Qdrant connection params (NOT the client itself).
    # AsyncQdrantClient uses an async HTTP session internally and CANNOT be
    # created in a sync function — the session gets closed immediately.
    # We create the client lazily in the async session handler instead.
    proc.userdata["qdrant_host"] = QDRANT_HOST
    proc.userdata["qdrant_port"] = QDRANT_PORT

    # Load system prompt templates for both agents
    # Urdu and English
    proc.userdata["system_prompt_template_urdu"] = _read_prompt_template(
        SYSTEM_PROMPT_PATH_URDU,
        language_label="Urdu",
    )

    proc.userdata["system_prompt_template_english"] = _read_prompt_template(
        SYSTEM_PROMPT_PATH_ENGLISH,
        language_label="English",
    )

    proc.userdata["system_prompt_template_english_female"] = _read_prompt_template(
        SYSTEM_PROMPT_PATH_ENGLISH_FEMALE,
        language_label="English Female",
    )

    proc.userdata["system_prompt_template_urdu_female"] = _read_prompt_template(
        SYSTEM_PROMPT_PATH_URDU_FEMALE,
        language_label="Urdu Female",
    )

    # For backward compatibility, set system_prompt_template to Urdu's
    proc.userdata["system_prompt_template"] = proc.userdata.get("system_prompt_template_urdu")

    logger.info(
        "Prewarm complete: ALL models loaded in %.1fs",
        time.monotonic() - t0,
    )


server.setup_fnc = prewarm


@server.rtc_session
async def chatbot_session(ctx):
    """Handle a single voice/chat session.

    All heavy models are already loaded during prewarm, so this handler
    starts the AgentSession immediately (no loading delay).
    """
    import asyncio

    vad = ctx.proc.userdata["vad"]
    whisper = ctx.proc.userdata["whisper_stt"]
    kokoro_tts_dict = ctx.proc.userdata["kokoro_tts"]  # Dict with "urdu" and "english" keys
    mms_tts = ctx.proc.userdata["mms_tts"]
    embedding = ctx.proc.userdata["embedding"]
    system_prompt_template_urdu = ctx.proc.userdata.get("system_prompt_template_urdu")
    system_prompt_template_english = ctx.proc.userdata.get("system_prompt_template_english")
    system_prompt_template_english_female = ctx.proc.userdata.get("system_prompt_template_english_female")
    system_prompt_template_urdu_female = ctx.proc.userdata.get("system_prompt_template_urdu_female")

    # Create AsyncQdrantClient here (async context) — can't be done in prewarm
    from qdrant_client import AsyncQdrantClient

    qdrant = AsyncQdrantClient(
        host=ctx.proc.userdata["qdrant_host"],
        port=ctx.proc.userdata["qdrant_port"],
        api_key=QDRANT_API_KEY or None,
        # Internal Docker network, no TLS termination in front of Qdrant.
        # qdrant-client defaults https=True whenever api_key is set, which
        # breaks the plaintext connection — must be explicit here.
        https=False,
        # Qdrant client v1.17+ with server v1.13 triggers a compatibility warning.
        # The API surface we use (query_points) is stable across these versions.
        check_compatibility=False,
    )

    # Use OpenAI-compatible LLM plugin (works with OpenRouter)
    llm = openai.LLM(
        model=LLM_MODEL,
        base_url=LLM_API_BASE,
        api_key=LLM_API_KEY
    )

    #use vLLM for lower-latency response streaming (optional)

    # llm = openai.LLM(
    #     model=os.getenv("VLLM_MODEL", "deepseek_v3"),
    #     client=AsyncOpenAI(
    #         base_url=os.getenv("VLLM_API_BASE"),
    #         api_key=os.getenv("VLLM_API_KEY"),
    #     ),
    #     temperature=0.5,
    # )

    # ── Connect to the room FIRST so room info (including metadata) is populated ──
    # ctx.room is not connected yet when the entrypoint is called — Room.metadata
    # is empty until we call ctx.connect().
    await ctx.connect()
    logger.info("Connected to room: name=%s", ctx.room.name)

    # ── Read ROOM metadata to determine TTS/STT/LLM providers ──
    # The backend pre-creates the room with metadata (via LiveKit RoomService)
    # before the user connects, so ctx.room.metadata is available after connect.
    tts_provider_name = "local"
    stt_provider_name = "local"
    speech_language = "auto"
    voice_gender = "male"
    llm_provider_name = "local"

    room_metadata = ctx.room.metadata
    if room_metadata:
        try:
            meta = json.loads(room_metadata)
            tts_provider_name = meta.get("tts_provider", "local")
            stt_provider_name = meta.get("stt_provider", "local")
            speech_language = meta.get("speech_language", "auto")
            voice_gender = meta.get("voice_gender", "male")
            llm_provider_name = meta.get("llm_provider", "local")
            logger.info("Read room metadata: %s", meta)
        except json.JSONDecodeError:
            logger.warning("Failed to parse room metadata: %r", room_metadata)
    else:
        logger.info("No room metadata — using default providers")

    # ── Initialize LLM based on provider selection ──
    # Preflight: vLLM often sits behind an SSH tunnel to a remote GPU box that
    # may not be up. Without this check, an unreachable endpoint left the agent
    # stuck "thinking" for the length of the request timeout — which also kept
    # the mic auto-muted (see auto-mute effect in LiveKitConversationContext)
    # and could trip the frontend's idle timeout. Fail fast and fall back
    # to OpenRouter instead.
    vllm_reachable = False
    if llm_provider_name == "local" and VLLM_API_BASE:
        try:
            parsed = httpx.URL(VLLM_API_BASE)
            port = parsed.port or (443 if parsed.scheme == "https" else 80)
            _, writer = await asyncio.wait_for(
                asyncio.open_connection(parsed.host, port), timeout=3.0
            )
            writer.close()
            vllm_reachable = True
        except Exception as e:
            logger.warning(
                "vLLM endpoint unreachable (%s) — falling back to OpenRouter: %s",
                VLLM_API_BASE, e,
            )

    if llm_provider_name == "local" and VLLM_API_BASE and vllm_reachable:
        # Qwen3.5 thinking mode produces <think>...</think> blocks that get
        # spoken aloud by TTS. Disable it by injecting chat_template_kwargs
        # into every request body via a custom httpx transport.
        # Streaming is already handled internally by livekit's openai plugin.
        class _NoThinkTransport(httpx.AsyncHTTPTransport):
            async def handle_async_request(self, req: httpx.Request) -> httpx.Response:
                if req.content:
                    try:
                        body = json.loads(req.content)
                        body["stream"] = True
                        body.setdefault("chat_template_kwargs", {"enable_thinking": False})
                        data = json.dumps(body).encode()
                        headers = dict(req.headers)
                        headers["content-length"] = str(len(data))
                        req = httpx.Request(
                            method=req.method, url=req.url,
                            headers=headers, content=data,
                            extensions=req.extensions,
                        )
                    except Exception:
                        pass
                return await super().handle_async_request(req)

        _vllm_client = AsyncOpenAI(
            base_url=VLLM_API_BASE,
            api_key=VLLM_API_KEY or "none",
            # Without an explicit timeout, an unreachable vLLM endpoint (e.g. a
            # dead SSH tunnel to the GPU box) hangs the request indefinitely —
            # the agent gets stuck "thinking", which keeps the mic auto-muted
            # and eventually trips the frontend's idle timeout. Fail fast instead.
            http_client=httpx.AsyncClient(
                transport=_NoThinkTransport(),
                timeout=httpx.Timeout(connect=5.0, read=30.0, write=10.0, pool=5.0),
            ),
        )
        llm = openai.LLM(
            model=VLLM_MODEL,
            client=_vllm_client,
            temperature=0.3,
            # 300 was cutting off descriptive answers mid-sentence, especially
            # in Urdu (non-Latin scripts tend to use more tokens per word).
            # 500 gives headroom for the 2-4 sentence "descriptive" case in the
            # system prompt's adaptive-length rule, without inviting runaway length.
            max_completion_tokens=500,
        )
        logger.info("LLM: vLLM/Qwen3.5 (%s, thinking disabled, streaming)", VLLM_API_BASE)
    else:
        if llm_provider_name == "local" and not VLLM_API_BASE:
            logger.warning(
                "vLLM requested but APP_VLLM_API_BASE not set — falling back to OpenRouter"
            )
        llm = openai.LLM(
            model=LLM_MODEL,
            base_url=LLM_API_BASE,
            api_key=LLM_API_KEY,
            temperature=0.3,
            # 300 was cutting off descriptive answers mid-sentence, especially
            # in Urdu (non-Latin scripts tend to use more tokens per word).
            # 500 gives headroom for the 2-4 sentence "descriptive" case in the
            # system prompt's adaptive-length rule, without inviting runaway length.
            max_completion_tokens=500,
        )
        logger.info("LLM: OpenRouter (%s)", LLM_API_BASE)

    # Convert speech_language to the value expected by STT providers.
    # "auto" means don't force a language (let STT auto-detect).
    # ElevenLabs Scribe expects ISO 639-3 codes ("eng", "urd"), while the
    # frontend sends ISO 639-1 ("en", "ur"). Map accordingly.
    _ISO639_1_TO_3 = {"en": "eng", "ur": "urd", "hi": "hin"}
    stt_language: str | None = (
        None if speech_language == "auto"
        else _ISO639_1_TO_3.get(speech_language, speech_language)
    )

    logger.info(
        "Provider selection: tts=%s, stt=%s, lang=%s",
        tts_provider_name, stt_provider_name, stt_language or "auto-detect",
    )

    # ── Select TTS & STT (parallel pre-flight for ElevenLabs) ──
    want_el_tts = tts_provider_name == "elevenlabs" and ELEVENLABS_API_KEY
    want_el_stt = stt_provider_name == "elevenlabs" and ELEVENLABS_API_KEY
    # Auto-use Deepgram when key is available and "local" STT is selected.
    # Deepgram streaming (~200ms) is 1-2s faster than local Whisper large-v3-turbo on CPU.
    want_deepgram_stt = bool(DEEPGRAM_API_KEY) and stt_provider_name in ("deepgram", "local")
    # Use Remote Whisper only when Deepgram is not taking priority
    want_remote_whisper = (
        stt_provider_name not in ("elevenlabs", "deepgram", "soniox")
        and not (stt_provider_name == "local" and DEEPGRAM_API_KEY)
        and REMOTE_WHISPER_URL
    )

    # Select agent and voice based on language
    # Urdu (ur) → Urdu agent (female voice, via UpliftAI — falls back to Kokoro if unavailable)
    # English (en) → English agent (female voice)
    is_urdu = speech_language == "ur"
    agent_name = "Urdu" if is_urdu else "English"

    # Select TTS instance based on language (+ voice gender for English)
    if speech_language == "ur":
        system_prompt_template = system_prompt_template_urdu_female or system_prompt_template_urdu
        if UPLIFT_API_KEY:
            try:
                tts_instance = SentenceChunkedUpliftTTS(
                    voice_id=UPLIFT_VOICE_ID,
                    api_key=UPLIFT_API_KEY,
                    base_url=UPLIFT_TTS_BASE_URL,
                )
                logger.info(
                    "Agent: Urdu (UpliftAI, per-sentence synthesis, Singapore region, "
                    "female voice, Sara persona)"
                )
            except Exception as e:
                # MMS-TTS (not Kokoro) is the fallback: Kokoro's "urdu" entry is
                # actually just an English voice under a different name, so it
                # can't produce real Urdu speech — MMS is the only other plugin
                # that actually synthesizes Urdu phonemes.
                logger.warning("UpliftAI TTS init failed: %s — falling back to MMS-TTS (male voice)", e)
                tts_instance = mms_tts
        else:
            logger.warning("APP_UPLIFT_API_KEY not set — Urdu falling back to MMS-TTS (male voice)")
            tts_instance = mms_tts
    else:  # English or auto
        if voice_gender == "female":
            tts_instance = kokoro_tts_dict.get("english_female", kokoro_tts_dict["english"])
            system_prompt_template = (
                system_prompt_template_english_female
                or system_prompt_template_english
                or system_prompt_template_urdu
            )
            logger.info("Agent: English (English, female voice, Sara persona)")
        else:
            tts_instance = kokoro_tts_dict.get("english", kokoro_tts_dict["urdu"])  # Fallback to Urdu if English not available
            system_prompt_template = system_prompt_template_english if system_prompt_template_english else system_prompt_template_urdu
            logger.info("Agent: English (English, male voice, Saad persona)")
    
    stt_instance = whisper
    
    # Select ElevenLabs voice ID based on language
    elevenlabs_voice_id_selected = ELEVENLABS_VOICE_ID_ENGLISH if not is_urdu else ELEVENLABS_VOICE_ID_URDU

    # ── Remote Whisper STT ──
    # When "local" or "remote_whisper" is selected, use Remote Whisper if available
    # (we're deprecating local Whisper, always prefer Remote Whisper)
    if want_remote_whisper and stt_provider_name != "elevenlabs":
        # Pass the user-selected language so Whisper transcribes in the correct
        # language instead of auto-detecting. None means auto-detect.
        remote_whisper_lang = speech_language if speech_language != "auto" else None
        try:
            stt_instance = RemoteWhisperSTT(
                url=REMOTE_WHISPER_URL,
                token=REMOTE_WHISPER_TOKEN,
                model=REMOTE_WHISPER_MODEL,
                language=remote_whisper_lang,
            )
            logger.info(
                "Using Remote Whisper STT (url=%s, model=%s, language=%s)",
                REMOTE_WHISPER_URL,
                REMOTE_WHISPER_MODEL,
                remote_whisper_lang or "auto-detect",
            )
        except Exception as e:
            logger.warning("Remote Whisper STT init failed: %s — falling back to local Whisper", e)
    elif stt_provider_name == "remote_whisper" and not REMOTE_WHISPER_URL:
        logger.warning("Remote Whisper STT requested but URL not set — falling back to local Whisper")
    elif stt_provider_name == "local" and not REMOTE_WHISPER_URL:
        logger.warning("Local STT provider selected and Remote Whisper not configured — using local Whisper as fallback")

    if want_el_tts or want_el_stt:
        # Single pre-flight check for ElevenLabs API (shared by TTS and STT)
        el_api_ok = False
        try:
            import aiohttp

            async with aiohttp.ClientSession() as _http:
                resp = await asyncio.wait_for(
                    _http.get(
                        "https://api.elevenlabs.io/v1/models",
                        headers={"xi-api-key": ELEVENLABS_API_KEY},
                    ),
                    timeout=5,
                )
                if resp.status != 200:
                    raise RuntimeError(f"ElevenLabs API returned HTTP {resp.status}")
            el_api_ok = True
        except Exception as e:
            logger.warning("ElevenLabs pre-flight failed: %s — using local fallbacks", e)

        if want_el_tts and el_api_ok:
            tts_instance = elevenlabs.TTS(
                voice_id=elevenlabs_voice_id_selected,
                model=ELEVENLABS_MODEL_ID,
                api_key=ELEVENLABS_API_KEY,
                encoding="pcm_24000",
            )
            agent_info = "English (English, female)" if not is_urdu else "Urdu (Urdu, male)"
            logger.info(
                "Using ElevenLabs TTS for %s (voice=%s, model=%s)",
                agent_info,
                elevenlabs_voice_id_selected,
                ELEVENLABS_MODEL_ID,
            )
        elif want_el_tts:
            logger.warning("ElevenLabs TTS requested but pre-flight failed — falling back to Kokoro")

        if want_el_stt and el_api_ok:
            stt_instance = elevenlabs.STT(
                api_key=ELEVENLABS_API_KEY,
                language_code=stt_language,
            )
            logger.info(
                "Using ElevenLabs STT (scribe, language=%s)",
                stt_language or "auto-detect",
            )
        elif want_el_stt:
            logger.warning("ElevenLabs STT requested but pre-flight failed — falling back to Whisper")
    else:
        if tts_provider_name == "elevenlabs" and not ELEVENLABS_API_KEY:
            logger.warning("ElevenLabs TTS requested but API key not set — falling back to Kokoro")
        if stt_provider_name == "elevenlabs" and not ELEVENLABS_API_KEY:
            logger.warning("ElevenLabs STT requested but API key not set — falling back to Whisper")

    # ── UpliftAI TTS (cloud, Urdu voices, streaming, Singapore region) ──
    if tts_provider_name == "uplift":
        if UPLIFT_API_KEY:
            try:
                tts_instance = SentenceChunkedUpliftTTS(
                    voice_id=UPLIFT_VOICE_ID,
                    api_key=UPLIFT_API_KEY,
                    base_url=UPLIFT_TTS_BASE_URL,
                )
                logger.info(
                    "Using UpliftAI TTS (voice=%s, region=%s, per-sentence synthesis)",
                    UPLIFT_VOICE_ID, UPLIFT_TTS_BASE_URL,
                )
            except Exception as e:
                logger.warning("UpliftAI TTS init failed: %s — falling back to Kokoro", e)
        else:
            logger.warning("UpliftAI TTS requested but APP_UPLIFT_API_KEY not set — falling back to Kokoro")

    # ── Deepgram STT (low-latency streaming) ──
    if want_deepgram_stt:
        # Deepgram Nova uses BCP-47 language codes: "en", "ur", "hi", etc.
        # stt_language is ISO 639-3 ("eng", "urd") — map back to short codes.
        _ISO639_3_TO_BCP47 = {"eng": "en", "urd": "ur", "hin": "hi"}
        dg_language = _ISO639_3_TO_BCP47.get(stt_language, stt_language) if stt_language else None
        stt_instance = deepgram.STT(
            api_key=DEEPGRAM_API_KEY,
            language=dg_language,
            model="nova-3",
            detect_language=dg_language is None,
        )
        logger.info(
            "Using Deepgram STT (nova-3, language=%s)",
            dg_language or "auto-detect",
        )
    elif stt_provider_name == "deepgram" and not DEEPGRAM_API_KEY:
        logger.warning("Deepgram STT requested but API key not set — falling back to Whisper")

    # ── Soniox STT (low-latency streaming, Urdu + English, JP region) ──
    if stt_provider_name == "soniox":
        if SONIOX_API_KEY:
            try:
                # Soniox's language codes are plain ISO 639-1 ("en"/"ur"), unlike
                # stt_language above (mapped to ISO 639-3 for ElevenLabs). Hints
                # bias the model toward the selected language, but language
                # identification stays on so it can still correct itself mid-stream.
                soniox_language_hints = (
                    None if speech_language == "auto" else [speech_language]
                )
                stt_instance = soniox.STT(
                    api_key=SONIOX_API_KEY,
                    params=soniox.STTOptions(
                        model="stt-rt-v4",
                        language_hints=soniox_language_hints,
                        enable_language_identification=True,
                    ),
                    # Only override the endpoint when configured: passing ""
                    # clobbers the plugin's default URL and the websocket
                    # connect fails later with no Whisper fallback.
                    **({"base_url": SONIOX_BASE_URL} if SONIOX_BASE_URL else {}),
                )
                logger.info(
                    "Using Soniox STT (region=%s, language=%s)",
                    SONIOX_BASE_URL or "plugin default (US)",
                    speech_language if speech_language != "auto" else "auto-detect",
                )
            except Exception as e:
                logger.warning("Soniox STT init failed: %s — falling back to Whisper", e)
        else:
            logger.warning("Soniox STT requested but APP_SONIOX_API_KEY not set — falling back to Whisper")

    # ── UpliftAI STT (Urdu only — the API currently only supports "ur") ──
    if stt_provider_name == "uplift":
        if speech_language != "ur":
            logger.warning(
                "UpliftAI STT only supports Urdu — falling back (speech_language=%s)",
                speech_language,
            )
        elif UPLIFT_API_KEY:
            try:
                # Pass vad= so UpliftSTT segments utterances itself, polls the
                # batch endpoint for partial captions during speech, and always
                # emits a final per utterance. UpliftAI has no streaming mode —
                # see uplift_stt.py for the measurements and what that implies.
                stt_instance = UpliftSTT(api_key=UPLIFT_API_KEY, vad=vad)
                logger.info("Using UpliftAI STT (Urdu, polled partials)")
            except Exception as e:
                logger.warning("UpliftAI STT init failed: %s — falling back", e)
        else:
            logger.warning("UpliftAI STT requested but APP_UPLIFT_API_KEY not set — falling back")

    # Create the agent session with selected providers
    session = AgentSession(
        vad=vad,
        stt=stt_instance,
        llm=llm,
        tts=tts_instance,
        tts_text_transforms=["filter_markdown", "filter_emoji", tts_text_transform, urdu_text_tts_transform],
        turn_detection="vad",
        allow_interruptions=True,
        min_endpointing_delay=0.2,
        preemptive_generation=True,
    )

    # ── Diagnostic event handlers ──
    @session.on("user_started_speaking")
    def _on_user_speech_start():
        logger.info("🎤 User started speaking")

    @session.on("user_stopped_speaking")
    def _on_user_speech_stop():
        logger.info("🎤 User stopped speaking")

    @session.on("agent_started_speaking")
    def _on_agent_speech_start():
        logger.info("🔊 Agent started speaking")

    @session.on("agent_stopped_speaking")
    def _on_agent_speech_stop():
        logger.info("🔊 Agent stopped speaking")

    @session.on("user_state_changed")
    def _on_user_state_changed(ev):
        logger.info("👤 User state changed: %s", ev)

    @session.on("user_input_transcribed")
    def _on_user_transcribed(ev):
        logger.info("📝 User input transcribed: %s", ev)

    @session.on("agent_speech_interrupted")
    def _on_speech_interrupted():
        logger.info("⚡ Agent speech interrupted by user — TTS cancelled")

    # ── Per-turn pipeline timing ──
    # EOUMetrics/LLMMetrics/TTSMetrics share a speech_id for one turn; STTMetrics
    # doesn't (it has request_id instead), so it's logged standalone as it lands.
    # Keyed by speech_id so concurrent/overlapping turns (e.g. barge-in) don't
    # cross-contaminate each other's numbers.
    _turn_metrics: dict[str, dict] = {}

    @session.on("metrics_collected")
    def _on_metrics_collected(ev):
        m = ev.metrics

        if isinstance(m, STTMetrics):
            logger.info(
                "⏱️  STT   | audio=%.2fs  processing=%.2fs",
                m.audio_duration, m.duration,
            )
            return

        if isinstance(m, VADMetrics):
            return  # too frequent (fires continuously) to be useful in a log

        speech_id = getattr(m, "speech_id", None)
        if speech_id is None:
            return
        turn = _turn_metrics.setdefault(speech_id, {})

        if isinstance(m, EOUMetrics):
            turn["eou_delay"] = m.end_of_utterance_delay
            turn["transcription_delay"] = m.transcription_delay
            logger.info(
                "⏱️  EOU   | end_of_utterance_delay=%.2fs  transcription_delay=%.2fs",
                m.end_of_utterance_delay, m.transcription_delay,
            )
        elif isinstance(m, LLMMetrics):
            turn["llm_ttft"] = m.ttft
            turn["llm_duration"] = m.duration
            logger.info(
                "⏱️  LLM   | ttft=%.2fs  total=%.2fs  tokens/s=%.1f",
                m.ttft, m.duration, m.tokens_per_second,
            )
        elif isinstance(m, TTSMetrics):
            turn["tts_ttfb"] = m.ttfb
            logger.info(
                "⏱️  TTS   | ttfb=%.2fs  synth=%.2fs  audio=%.2fs",
                m.ttfb, m.duration, m.audio_duration,
            )
            # TTS is the last stage of a turn — print the full breakdown now.
            # This total is the number that matters: silence after the user
            # stops talking until the agent's voice starts.
            #
            # eou and stt are CONCURRENT, not sequential. Per livekit's
            # EOUMetrics docstrings, end_of_utterance_delay and
            # transcription_delay are both measured "after the end of the
            # user's speech" — same origin, overlapping intervals. Summing
            # them double-counted the STT stage and inflated this number by
            # the transcription time (~0.22s with Soniox on Urdu, where STT
            # finishes well inside the VAD silence window). The turn is gated
            # by whichever finishes LAST, hence max().
            #
            # tts_ttfb is now the FIRST SENTENCE's ttfb: SentenceChunkedUpliftTTS
            # declares streaming=False, so livekit wraps it in a StreamAdapter
            # that calls synthesize() once per sentence. That fires TTSMetrics
            # per sentence; the first is the one the user actually waits for,
            # and popping the turn below keeps only that one.
            eou = turn.get("eou_delay")
            transcription = turn.get("transcription_delay")
            llm_ttft = turn.get("llm_ttft")
            tts_ttfb = turn.get("tts_ttfb")
            if None not in (eou, transcription, llm_ttft, tts_ttfb):
                end_of_turn = max(eou, transcription)
                total = end_of_turn + llm_ttft + tts_ttfb
                logger.info(
                    "⏱️  TOTAL | stop-talking → agent-voice ≈ %.2fs  "
                    "(end_of_turn=%.2fs [max(eou=%.2fs, stt=%.2fs)] "
                    "+ llm_ttft=%.2fs + tts_ttfb=%.2fs)",
                    total, end_of_turn, eou, transcription, llm_ttft, tts_ttfb,
                )
            _turn_metrics.pop(speech_id, None)

    # Create the agent with RAG capabilities
    initial_language = "ur" if speech_language == "ur" else "en"
    initial_instructions = build_system_prompt(
        initial_language,
        context="",
        template=system_prompt_template,
    )

    # ── Audio2Face blendshape lipsync (optional) ──
    a2f_client = None
    if A2F_URL and A2FClient is not None:
        a2f_client = A2FClient(
            target=A2F_URL, api_key=A2F_API_KEY, tls_ca_file=A2F_TLS_CA
        )
        # Dial the shared gRPC channel now — the IAP tunnel handshake (~2.5s)
        # then overlaps session setup instead of delaying the first lipsync.
        asyncio.create_task(a2f_client.warmup())
        logger.info(
            "A2F lipsync enabled (url=%s, delay=%.1fs)", A2F_URL, A2F_PLAYBACK_DELAY
        )
    elif A2F_URL:
        logger.warning("APP_A2F_URL set but A2F client unavailable (nvidia-ace not installed)")

    agent = ChatbotAgent(
        instructions=initial_instructions,
        embedding_service=embedding,
        qdrant_client=qdrant,
        system_prompt_template=system_prompt_template,
        default_language=initial_language,
        langfuse=_langfuse_client,
        room_name=ctx.room.name,
        room=ctx.room,
        a2f_client=a2f_client,
        a2f_sample_rate=int(getattr(tts_instance, "sample_rate", 0) or 0),
        a2f_playback_delay=A2F_PLAYBACK_DELAY,
        glossary=ctx.proc.userdata.get("glossary"),
    )

    # ── A2F turn lifecycle ──
    # The playback-start marker anchors the frontend's lipsync timeline to the
    # moment audio ACTUALLY starts playing (paced output), not synthesis time.
    # NOTE: agent_started/stopped_speaking no longer fire in livekit-agents
    # 1.6.x — agent_state_changed is the supported signal.
    if a2f_client is not None:

        @session.on("agent_state_changed")
        def _on_a2f_agent_state(ev):
            new_state = str(getattr(ev, "new_state", ""))
            old_state = str(getattr(ev, "old_state", ""))
            if new_state.endswith("speaking") and agent._turn_uid:
                logger.info("A2F: publishing start marker (turn %s)", agent._turn_uid)
                asyncio.create_task(
                    ctx.room.local_participant.send_text(
                        json.dumps(
                            {"uid": agent._turn_uid, "start": True},
                            separators=(",", ":"),
                        ),
                        topic="lipsync.frames",
                    )
                )
            elif old_state.endswith("speaking"):
                agent.a2f_turn_ended()

    # Pre-start RAG embedding as soon as transcription is final.
    # This overlaps the ~200-500ms CPU embed with the overhead before llm_node fires.
    @session.on("user_input_transcribed")
    def _on_embed_prestart(ev):
        if ev.is_final and ev.transcript:
            agent.prestart_embed(ev.transcript)

    # Log room state before starting session
    participants = ctx.room.remote_participants
    logger.info(
        "Room %s: %d remote participants before session.start()",
        ctx.room.name,
        len(participants),
    )
    for pid, p in participants.items():
        tracks = list(p.track_publications.values())
        logger.info(
            "  Participant %s (identity=%s): %d tracks (%s)",
            pid,
            p.identity,
            len(tracks),
            ", ".join(f"{t.source}:{t.mime_type}" for t in tracks),
        )

    await session.start(
        room=ctx.room,
        agent=agent,
        room_options=room_io.RoomOptions(
            # BVC (Background Voice Cancellation) is a LiveKit Cloud-only filter.
            # On self-hosted LiveKit it fails to load ("ensure you are connecting to
            # LiveKit Cloud", on_load error 4) and breaks the audio path feeding STT,
            # so Deepgram/Whisper never receive usable audio and nothing is transcribed
            # even though VAD still fires. Disabled for self-hosted; rely on the
            # browser's built-in noise suppression instead.
            audio_input=room_io.AudioInputOptions(
                noise_cancellation=None,
            ),
            audio_output=True,
            text_input=True,
            text_output=True,
            video_input=False,
        ),
    )

    logger.info("Agent session started for room: %s", ctx.room.name)

    # Keep session alive — log periodic health checks
    async def _health_monitor():
        for i in range(300):  # 5 minutes
            await asyncio.sleep(1)
            if i % 10 == 9:
                logger.info(
                    "Session health [%ds]: participants=%d",
                    i + 1,
                    len(ctx.room.remote_participants),
                )

    asyncio.create_task(_health_monitor())


if __name__ == "__main__":
    cli.run_app(server)
