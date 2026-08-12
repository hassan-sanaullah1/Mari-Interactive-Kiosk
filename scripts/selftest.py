"""MARI · Voice — provider self-test.

Run this ON the host that can reach the endpoints (e.g. the ECS host / inside the
Docker network) to verify every stage of the pipeline end-to-end:

    python scripts/selftest.py

Checks (each independent, timed):
    LLM        vLLM Qwen chat completion
    Urdu       Uplift TTS  ->  Soniox STT   (round trip)
    English    Kokoro TTS  ->  Whisper STT  (round trip)

TTS→STT round trips prove both directions at once: we synthesize known text, then
transcribe the audio back and show what came out. Needs PyAV + numpy (already in
requirements.txt) to decode the returned mp3 to 16 kHz PCM.
"""

from __future__ import annotations

import asyncio
import io
import struct
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server import config as C          # noqa: E402
from server import providers as P       # noqa: E402
from server.app import run_llm          # noqa: E402

OK, BAD, WARN = "\033[92m✓\033[0m", "\033[91m✗\033[0m", "\033[93m!\033[0m"


def _mp3_to_wav16k(mp3: bytes) -> bytes:
    import av
    import numpy as np

    cont = av.open(io.BytesIO(mp3))
    rs = av.audio.resampler.AudioResampler(format="s16", layout="mono", rate=16000)
    chunks = []
    for fr in cont.decode(audio=0):
        for r in rs.resample(fr):
            chunks.append(r.to_ndarray().reshape(-1))
    cont.close()
    pcm = np.concatenate(chunks).astype(np.int16).tobytes() if chunks else b""
    hdr = (
        b"RIFF" + struct.pack("<I", 36 + len(pcm)) + b"WAVEfmt "
        + struct.pack("<IHHIIHH", 16, 1, 1, 16000, 32000, 2, 16)
        + b"data" + struct.pack("<I", len(pcm))
    )
    return hdr + pcm


async def _timed(coro):
    t = time.perf_counter()
    result = await coro
    return result, (time.perf_counter() - t) * 1000


async def test_llm():
    if not C.llm_ready():
        return WARN, "not configured (APP_VLLM_*)"
    try:
        reply, ms = await _timed(run_llm("Reply with exactly one word: pong.", "en"))
        return OK, f"{ms:6.0f} ms · {reply[:60]!r}"
    except Exception as exc:
        return BAD, f"{type(exc).__name__}: {exc}"


async def test_roundtrip(lang, text):
    tts_name = "uplift" if lang == "ur" else "kokoro"
    stt_name = "soniox" if lang == "ur" else "whisper"
    try:
        (mp3, _), t_tts = await _timed(P.tts(text, lang))
        if not mp3:
            return BAD, f"{tts_name} returned no audio"
        wav = _mp3_to_wav16k(mp3)
        said, t_stt = await _timed(P.stt(wav, lang))
        mark = OK if said.strip() else WARN
        return mark, f"{tts_name} {t_tts:5.0f}ms → {stt_name} {t_stt:5.0f}ms · heard: {said[:60]!r}"
    except Exception as exc:
        return BAD, f"{type(exc).__name__}: {exc}"


async def main():
    print("\nMARI · Voice — provider self-test")
    print("=" * 60)
    for k, v in C.status().items():
        print(f"  {k}: {v}")
    print("-" * 60)

    llm_mark, llm_msg = await test_llm()
    print(f"{llm_mark} LLM     (vLLM Qwen)      {llm_msg}")

    ur_mark, ur_msg = await test_roundtrip("ur", "اسلام علیکم، آج آپ کیسے ہیں؟")
    print(f"{ur_mark} Urdu    (Uplift↔Soniox)  {ur_msg}")

    en_mark, en_msg = await test_roundtrip("en", "Hello, this is a MARI voice self test.")
    print(f"{en_mark} English (Kokoro↔Whisper) {en_msg}")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    asyncio.run(main())
