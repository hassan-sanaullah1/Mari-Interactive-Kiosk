"""TTS adapters — each implements :class:`server.providers.base.TTSProvider`.

  UpliftTTS        Urdu, and English while APP_EN_TTS=uplift — UpliftAI REST (mp3)
  KokoroLocalTTS   English — local Kokoro (GPU if available)
  KokoroRemoteTTS  English — remote OpenAI-compatible /v1/audio/speech

Shared by both entrypoints: server/app.py (FastAPI) and mari_s2s/handlers/*.py
(huggingface/speech-to-speech plugin handlers) — no more duplicated REST-call logic.
"""

from __future__ import annotations

import asyncio
import re

import httpx

from .. import config as C
from .base import TTSProvider

try:  # voice_config is optional — without it the Uplift-specific fixes just don't apply
    from voice_config import (
        normalise_for_uplift as _normalise_for_uplift,
        spoken_addresses as _spoken_addresses,
        spoken_names_and_ranks as _spoken_names_and_ranks,
        spoken_urls as _spoken_urls,
    )
except ImportError:  # pragma: no cover - only hit if the folder is removed
    def _normalise_for_uplift(text: str, lang: str = "ur") -> str:
        return text

    def _spoken_names_and_ranks(text: str, lang: str = "en") -> str:
        return text

    def _spoken_urls(text: str, lang: str = "en") -> str:
        return text

    def _spoken_addresses(text: str, lang: str = "en") -> str:
        return text


# The brand name has to be forced into words for Uplift's Urdu-first voices, both ways:
# in English text "Sky47" comes out as one mangled word ("SkySitalis"), and in Urdu text
# the digits are read as the Urdu number — "اسکائی ۴۷" is spoken "sentaalees", not "forty
# seven". Spelling it out fixes both, and "Sky Forty Seven" is pronounced identically in
# an Urdu sentence, so one replacement covers every reply.
_SKY = r"(?:Sky|\u0627\u0633\u06a9\u0627\u0626\u06cc|\u0633\u06a9\u0627\u0626\u06cc|\u0627\u0633\u06a9\u0627\u06cc|\u0633\u06a9\u0627\u06cc)"
_47 = r"(?:47|\u06f4\u06f7|\u0664\u0667)"  # ASCII, Urdu (۴۷) and Arabic-Indic (٤٧) digits

# "Mari" is spelled with ر (tapped r) in both scripts (Latin "Mari" and Urdu
# "ماری"), but the name is actually said with a retroflex flap — ڑ, as in
# "ماڑی" — not a tapped ر. Uplift's voice reads whatever script it is given
# literally, so both spellings are rewritten to ماڑی before synthesis, in either
# language.
_MARI = r"(?:Mari|ماری)"
# Mari Energies' own reports are full of initialisms and industry units that the voices
# either spell out wrongly or run together into a non-word, so they are written out too.
# ``\b``-anchored and applied to both languages, since an Urdu reply keeps these in Latin script.
_ACRONYMS = {
    "MPCL": "M P C L",
    "PSX": "P S X",
    "OGDCL": "O G D C L",
    "MMBOE": "million barrels of oil equivalent",
    "KBOEPD": "thousand barrels of oil equivalent per day",
    "MMSCFD": "million standard cubic feet per day",
    "MMSCF": "million standard cubic feet",
    "BBLs": "barrels",
    "BBL": "barrel",
    "REE": "rare earth elements",
    "TCF": "trillion cubic feet",
    "E&P": "exploration and production",
    "ESG": "E S G",
    "EPS": "earnings per share",
    # "HR&R" is run together into "H9R" by the voice; splitting the ampersand out is
    # enough to fix it. Other initialisms in the corpus (SECP, ICAP, SNGPL, HSE) were
    # tested the same way and left alone — letter-spacing them made the voice WORSE
    # ("S N G P L" is heard as "S and GPL"), so they keep whatever the engine does.
    "HR&R": "H R and R",
}

# The credit rating "A1" is a letter followed by a grade, not a quantity: the number
# spell-out below turns it into the non-word "Aone". Written apart, the voice says it
# correctly. "AAA" already reads fine on its own.
_RATING_RE = re.compile(r"\bA1\b")

_SAY_AS = (
    (re.compile(rf"(?<!\w){_SKY}\s*-?\s*{_47}(?!\w)", re.I), "Sky Forty Seven"),
    (re.compile(rf"(?<!\w){_MARI}(?!\w)"), "ماڑی"),
    # currency reads after the amount in both languages: "PKR 65 billion" -> "65 billion rupees"
    (re.compile(r"\b(?:PKR|Rs\.?)\s*([\d,.]+)\s*(billion|million|trillion|bn|mn)?\b", re.I),
     lambda m: f"{m.group(1)} {m.group(2) + ' ' if m.group(2) else ''}rupees"),
    (re.compile(r"\bUSD\s*([\d,.]+)\s*(billion|million|trillion)?\b", re.I),
     lambda m: f"{m.group(1)} {m.group(2) + ' ' if m.group(2) else ''}US dollars"),
    *((re.compile(rf"\b{re.escape(k)}\b"), v) for k, v in _ACRONYMS.items()),
)

# Uplift's voice is Urdu-first and reads bare digits in Urdu — "65" becomes "پینسٹھ" even
# in an otherwise English sentence, which is wrong in the kiosk's English mode. The voice
# takes its cue from the script, so the digits are written out as English words before an
# English reply is sent. Urdu replies keep their digits: there the Urdu reading is correct.
_ONES = ("zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine",
         "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen",
         "seventeen", "eighteen", "nineteen")
_TENS = ("", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety")
_SCALES = ((1_000_000_000, "billion"), (1_000_000, "million"), (1_000, "thousand"))


def _say_int(n: int) -> str:
    if n < 20:
        return _ONES[n]
    if n < 100:
        return _TENS[n // 10] + (f" {_ONES[n % 10]}" if n % 10 else "")
    if n < 1000:
        return f"{_ONES[n // 100]} hundred" + (f" and {_say_int(n % 100)}" if n % 100 else "")
    for value, name in _SCALES:
        if n >= value:
            head = f"{_say_int(n // value)} {name}"
            return head + (f" {_say_int(n % value)}" if n % value else "")
    return str(n)


def _say_number(match: re.Match[str]) -> str:
    whole, frac = match.group(1).replace(",", ""), match.group(2)
    try:
        said = _say_int(int(whole))
    except (ValueError, IndexError):
        return match.group(0)
    if frac:
        # "54.25" is read "fifty four point two five", digit by digit after the point
        said += " point " + " ".join(_ONES[int(d)] for d in frac)
    return said


# Digit runs that are identifiers rather than quantities — phone numbers, postcodes,
# well names — are read digit by digit; saying "one hundred and eleven" for a dialling
# code is worse than not touching it. Anything attached to a hyphen or another digit
# group is treated as an identifier and left for the voice to read as characters.
_PHONE = re.compile(r"(?:\+?\d[\d\s-]{6,}\d)")
_DIGITS = {str(i): w for i, w in enumerate(_ONES[:10])}


def _say_digits(match: re.Match[str]) -> str:
    return " ".join(_DIGITS.get(ch, ch) for ch in match.group(0) if ch.isdigit() or ch == "+")


# Years read naturally ("nineteen fifty four"), not as a count ("one thousand nine...").
# Round centuries are excluded: "2000" is "two thousand", not "twenty hundred".
_YEAR = re.compile(r"(?<![\d.])(1[89]|20)(\d{2})\b(?!\.\d)")
# A number not glued to a hyphen or decimal point on either side is a real quantity.
_NUMBER = re.compile(r"(?<![\d.])(\d[\d,]*)(?:\.(\d+))?\b(?!\.\d)")


def _say_year(match: re.Match[str]) -> str:
    century, rest = int(match.group(1)), int(match.group(2))
    if rest == 0:
        # 1900 / 2000 are said as counts, not as "nineteen hundred"-style year pairs
        return _say_int(century * 100)
    return f"{_say_int(century)} {'oh ' + _ONES[rest] if rest < 10 else _say_int(rest)}"


def _spell_numbers(text: str) -> str:
    text = _PHONE.sub(_say_digits, text)
    text = _YEAR.sub(_say_year, text)
    return _NUMBER.sub(_say_number, text)


def _spoken(text: str, lang: str = "en") -> str:
    """Rewrite a reply the way it should be *said* rather than read."""
    # Domains come FIRST: "sky47.com.pk" has to be seen whole, before the Sky47 rule in
    # _SAY_AS rewrites its label and leaves the dots behind unsaid.
    text = _spoken_urls(text, lang)
    for pattern, replacement in _SAY_AS:
        text = pattern.sub(replacement, text)
    # Names, ranks and honours, in BOTH languages: the Urdu-first voice mangles
    # Latin-script Pakistani names ("Anwar Ali Hyder" → "and were early hired") and
    # abbreviated ranks ("Lt. Gen." → "Leftenant"). Runs before the number spell-out
    # so a rank's own digits, if any, are still handled below.
    text = _spoken_names_and_ranks(text, lang)
    # Addresses, contact lines, chemical formulae and symbol-bearing abbreviations.
    # Must precede the number spell-out below: a postcode, an Islamabad sector and the
    # "2" in CO2 are identifiers, and that pass would turn them into quantities
    # ("forty four thousand", "G-ten/four", "COtwo").
    text = _spoken_addresses(text, lang)
    text = _RATING_RE.sub("A one", text)
    if lang != "ur":
        text = _spell_numbers(text)
    # Urdu-only fixes for what the Uplift voice gets wrong on its own — Roman numerals,
    # word/word slashes and bare URLs. Runs last so it sees the fully rewritten text.
    # See voice_config/urdu_normalise.py for why it is this short.
    return _normalise_for_uplift(text, lang)


class UpliftTTS(TTSProvider):
    """UpliftAI REST synthesis. Handles Urdu and English with the same voice."""

    def __init__(
        self,
        api_key: str = "",
        base: str = "",
        path: str = "",
        voice: str = "",
        output_format: str = "",
        speed: float = 1.0,
        lang: str = "ur",
    ):
        self.api_key = api_key or C.UPLIFT_KEY
        self.base = (base or C.UPLIFT_BASE).rstrip("/")
        self.path = path or C.UPLIFT_PATH
        self.voice = voice or C.UPLIFT_VOICE
        self.output_format = output_format or C.UPLIFT_FORMAT
        self.speed = speed
        self.lang = lang

    async def synthesize(self, text: str) -> tuple[bytes, str]:
        text = (text or "").strip()
        if not text:
            return b"", "audio/mpeg"
        path = self.path if self.path.startswith("/") else f"/{self.path}"
        url = f"{self.base}{path}"
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        payload = {
            "voiceId": self.voice,
            "text": _spoken(text, self.lang),
            "speed": self.speed,
            "outputFormat": self.output_format,
        }
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.post(url, json=payload, headers=headers)
            r.raise_for_status()
            mime = r.headers.get("content-type", "audio/mpeg").split(";")[0]
            return r.content, mime or "audio/mpeg"


class KokoroLocalTTS(TTSProvider):
    """In-process Kokoro pipeline (GPU if available)."""

    _pipe = None  # class-level cache: one pipeline instance per process

    def __init__(self, voice: str = ""):
        self.voice = voice or C.VOICE_EN

    def _get_pipe(self):
        if KokoroLocalTTS._pipe is None:
            from kokoro import KPipeline

            KokoroLocalTTS._pipe = KPipeline(lang_code="a")  # 'a' = American English
        return KokoroLocalTTS._pipe

    def warm(self) -> None:
        self._get_pipe()

    async def synthesize(self, text: str) -> tuple[bytes, str]:
        import io

        import numpy as np
        import soundfile as sf

        text = (text or "").strip()
        if not text:
            return b"", "audio/wav"
        pipe = self._get_pipe()

        def run() -> tuple[bytes, str]:
            parts = []
            for _, _, audio in pipe(text, voice=self.voice):
                if hasattr(audio, "detach"):
                    audio = audio.detach().cpu().numpy()
                parts.append(np.asarray(audio, dtype=np.float32).reshape(-1))
            if not parts:
                return b"", "audio/wav"
            buf = io.BytesIO()
            sf.write(buf, np.concatenate(parts), 24000, format="WAV", subtype="PCM_16")
            return buf.getvalue(), "audio/wav"

        return await asyncio.to_thread(run)


class KokoroRemoteTTS(TTSProvider):
    def __init__(self, base: str = "", path: str = "", token: str = "", model: str = "", voice: str = "", fmt: str = ""):
        self.base = (base or C.KOKORO_BASE).rstrip("/")
        self.path = path or C.KOKORO_PATH
        self.token = token or C.KOKORO_TOKEN
        self.model = model or C.KOKORO_MODEL
        self.voice = voice or C.VOICE_EN
        self.fmt = fmt or C.KOKORO_FORMAT

    async def synthesize(self, text: str) -> tuple[bytes, str]:
        text = (text or "").strip()
        if not text:
            return b"", "audio/mpeg"
        url = f"{self.base}{self.path}"
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        payload = {"model": self.model, "input": text, "voice": self.voice, "response_format": self.fmt}
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.post(url, json=payload, headers=headers)
            r.raise_for_status()
            mime = r.headers.get("content-type", "audio/mpeg").split(";")[0]
            return r.content, mime or "audio/mpeg"


# ─────────────────────────── selection + dispatch ────────────────────
_tts_cache: dict[str, TTSProvider] = {}


def get_tts_provider(lang: str) -> TTSProvider:
    """Return the configured TTS adapter for a language (cached — local-model
    adapters keep their loaded pipeline across calls)."""
    key = f"{lang}:{C.EN_TTS if lang != 'ur' else 'uplift'}"
    if key not in _tts_cache:
        if lang == "ur":
            _tts_cache[key] = UpliftTTS()
        elif C.EN_TTS == "uplift":
            # No Kokoro deployment right now — English goes out through Uplift too.
            _tts_cache[key] = UpliftTTS(voice=C.UPLIFT_VOICE_EN, lang="en")
        else:
            _tts_cache[key] = KokoroLocalTTS() if C.EN_TTS == "local" else KokoroRemoteTTS()
    return _tts_cache[key]


async def tts(text: str, lang: str) -> tuple[bytes, str]:
    return await get_tts_provider(lang).synthesize(text)
