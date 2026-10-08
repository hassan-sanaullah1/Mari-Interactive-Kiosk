"""Collects the /ws endpoint's observable behaviour for its golden snapshot.

What golden_harness.py does not reach: it calls ``run_reply`` directly, so the socket
endpoint itself — message dispatch, the STT seam, Soniox partials, error frames, the
typed-turn branch, disconnect — has no guard, and A2F is switched off there so no
``lipsync`` frame or ``tts.clip`` id is ever checked.

This drives the real app through ``TestClient.websocket_connect`` with the providers
faked at their outermost seams, and installs a fake A2F client whose frames are
deterministic. Everything the socket receives, in order, is recorded.

Regenerate ONLY on a deliberate behaviour change:  python -m tests.ws_harness --write
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "ws_golden.json"

# Small and unrealistic on purpose: this snapshot pins the lipsync plumbing — clip
# numbering, names sent once, batch sizes, tail trim — not the NIM's weights, and a
# real 52-name 30fps burst would bury that in a megabyte of floats.
FAKE_SHAPES = ["JawOpen", "MouthClose", "MouthFunnel", "MouthSmileLeft"]
FAKE_FPS = 10.0
# Mirrors the real reader: the first frame ships alone so lips engage immediately.
FAKE_FIRST_BATCH = 1
FAKE_BATCH = 3
# Frames past the audio the NIM was given, to exercise _Publisher's tail trim.
FAKE_TAIL_FRAMES = 3

SAMPLE_RATE = 16000


def api():
    """The only place this harness names internal modules."""
    from server import app as app_module
    from server import avatar, providers, rag
    from server import config as settings

    return {
        "app": app_module.app,
        "app_module": app_module,
        "avatar": avatar,
        "config": settings,
        "providers": providers,
        "rag": rag,
    }


# ── fakes ───────────────────────────────────────────────────────────


def fake_wav(text: str) -> bytes:
    """A decodable WAV whose length follows the sentence, so clips differ.

    golden_harness returns ``b"ID3fake"``, which PyAV cannot decode — fine there,
    where A2F is off, but here the decode path has to run for frames to exist.
    """
    from server.providers.stt import pcm16_to_wav

    samples = max(1, min(len(text), 40)) * 800  # 50 ms per character, capped
    return pcm16_to_wav(b"\x01\x00" * samples, SAMPLE_RATE)


class FakeA2FSession:
    """One clip. Emits frames the way the real reader batches them."""

    def __init__(self, on_batch) -> None:
        self._on_batch = on_batch
        self._pcm_bytes = 0
        self.primed = False
        self.aborted = False
        self.frames_total = 0

    def start_priming(self) -> None:
        self.primed = True

    async def write(self, pcm16: bytes) -> None:
        self._pcm_bytes += len(pcm16)

    async def finish(self) -> int:
        secs = self._pcm_bytes / 2 / SAMPLE_RATE
        total = int(secs * FAKE_FPS) + FAKE_TAIL_FRAMES
        frames = [
            [round(i / FAKE_FPS, 3)]
            + [round(((i + k) % 7) / 10, 3) for k in range(len(FAKE_SHAPES))]
            for i in range(total)
        ]
        # The NIM announces the shape names in its header, before any frame.
        await self._on_batch(list(FAKE_SHAPES), [])
        limit = FAKE_FIRST_BATCH
        while frames:
            batch, frames = frames[:limit], frames[limit:]
            await self._on_batch(None, batch)
            self.frames_total += len(batch)
            limit = FAKE_BATCH
        return self.frames_total

    async def abort(self) -> None:
        self.aborted = True


class FakeA2FClient:
    def __init__(self) -> None:
        self.opens: list[dict] = []

    async def open_stream(self, sample_rate, on_batch, face_params=None, bs_multipliers=None):
        # Recorded so the per-persona A2F tuning that reaches the NIM is pinned too.
        self.opens.append(
            {
                "sample_rate": sample_rate,
                "face_params": face_params,
                "bs_multipliers": bs_multipliers,
            }
        )
        return FakeA2FSession(on_batch)


class FakeSonioxStream:
    """Stands in for the Urdu realtime websocket: scripted partials, one final."""

    transcript = ""
    partials: tuple[str, ...] = ()
    fail_on_start = False

    def __init__(self, lang="ur", on_partial=None, **kw) -> None:
        self.lang = lang
        self.on_partial = on_partial
        self.sent_frames = 0
        self.closed = False

    async def start(self) -> None:
        if FakeSonioxStream.fail_on_start:
            raise RuntimeError("soniox unreachable")

    async def send(self, pcm: bytes) -> None:
        self.sent_frames += 1
        # Live captions arrive while the visitor is still speaking.
        if self.on_partial is not None and self.sent_frames <= len(FakeSonioxStream.partials):
            await self.on_partial(FakeSonioxStream.partials[self.sent_frames - 1])

    async def finish(self) -> str:
        return FakeSonioxStream.transcript

    async def close(self) -> None:
        self.closed = True


class Recorder:
    """Reads every frame the socket sends until it closes."""

    def __init__(self, ws) -> None:
        self.ws = ws
        self.frames: list = []

    def drain(self) -> list:
        from starlette.testclient import WebSocketDisconnect

        while True:
            try:
                message = self.ws.receive()
            except WebSocketDisconnect:
                break
            if message["type"] == "websocket.close":
                break
            if (text := message.get("text")) is not None:
                self.frames.append(json.loads(text))
            elif (data := message.get("bytes")) is not None:
                # Audio is recorded by length: the bytes are the fake WAV's.
                self.frames.append({"bytes": len(data)})
        return self.frames


# ── configuration ───────────────────────────────────────────────────


def configure(a, setattr_, *, a2f: bool) -> dict:
    """Fake every outside edge. Returns the handles a scenario needs."""
    import httpx

    from tests.golden_harness import FakeNet

    settings = a["config"]
    net = FakeNet()
    setattr_(httpx, "AsyncClient", net.client_class())
    for key, value in {
        "LLM_BASE": "http://llm.test/v1", "LLM_KEY": "k", "LLM_MODEL": "qwen3.5",
        "LLM_PROVIDER": "vllm", "FORCE_DEMO": False, "UPLIFT_KEY": "u",
        "EN_TTS": "uplift", "UR_TTS": "uplift", "SONIOX_KEY": "soniox-test-key",
        "UPLIFT_VOICE": "v_8eelc901v6", "UPLIFT_VOICE_EN": "v_8eelc901v6",
        "UPLIFT_VOICE_MALE": "v_8eelc901v6",
    }.items():
        setattr_(settings, key, value)

    # TTS: a decodable WAV instead of the real provider.
    from server.agent import speech
    from server.providers import tts as tts_module

    tts_fail_for: set[str] = set()

    async def fake_speak(text: str, lang: str, avatar_id: str = "female"):
        if text in tts_fail_for:
            raise RuntimeError("tts refused")
        return fake_wav(text), "audio/wav"

    setattr_(speech, "speak", fake_speak)
    setattr_(tts_module, "_tts_cache", {})

    # STT: the buffered English path.
    stt_result = {"transcript": "", "error": ""}

    async def fake_stt(wav: bytes, lang: str) -> str:
        if stt_result["error"]:
            raise RuntimeError(stt_result["error"])
        return stt_result["transcript"]

    setattr_(a["providers"], "stt", fake_stt)
    setattr_(a["app_module"].providers, "stt", fake_stt)
    setattr_(a["app_module"].providers, "SonioxStream", FakeSonioxStream)

    # Retrieval off: the turn takes the documented degraded path, as in golden_harness.
    rag = a["rag"]
    setattr_(rag, "_retriever", None)
    setattr_(rag, "_status", {"enabled": False, "state": "not started"})
    setattr_(a["app_module"].rag, "prestart", lambda *args, **kw: None)

    # Startup must not reach the network or load models.
    async def noop(*args, **kw):
        return None

    setattr_(a["app_module"].providers, "warm", noop)
    setattr_(a["app_module"].avatar, "warm", noop)
    setattr_(a["app_module"].rag, "startup", noop)
    setattr_(a["app_module"].rag, "shutdown", noop)

    a2f_client = FakeA2FClient() if a2f else None
    setattr_(a["avatar"], "_client", a2f_client)
    setattr_(a["avatar"], "_resolved", True)
    setattr_(a["config"], "A2F_URL", "fake:52000" if a2f else "")

    return {"net": net, "stt": stt_result, "a2f": a2f_client, "tts_fail_for": tts_fail_for}


# ── scenarios ───────────────────────────────────────────────────────

REPLY_EN = "Hello! I'm Maryam of Mari Energies. Our net profit was PKR 65.14bn."
REPLY_UR = "وعلیکم السلام، میں مریم ہوں۔ ہم نے 1954 میں Mari Gas Field دریافت کیا۔"

HISTORY = [
    {"role": "user", "text": "Tell me about the verticals"},
    {"role": "assistant", "text": "Mari Services, Mari Minerals, Sky47 and GEM Energy."},
]

PCM_FRAME = b"\x00\x10" * 1365  # one browser frame: ~2.7 KB of 16 kHz PCM16


def _turn_seq_reset(a, setattr_) -> None:
    """Clip ids embed a process-wide counter, so pin it per scenario."""
    from server.agent import turn as turn_module

    setattr_(turn_module, "_turn_seq", 0)


def run_scenarios(a, setattr_) -> dict:
    from starlette.testclient import TestClient

    out: dict = {}

    def scenario(label: str, *, a2f: bool, drive) -> None:
        handles = configure(a, setattr_, a2f=a2f)
        _turn_seq_reset(a, setattr_)
        with TestClient(a["app"]) as client, client.websocket_connect("/ws") as ws:
            recorder = Recorder(ws)
            drive(ws, handles)
            frames = recorder.drain()
        record: dict = {"socket": frames}
        if handles["a2f"] is not None:
            record["a2f_opens"] = handles["a2f"].opens
        out[label] = record

    # ── a spoken English turn: start, PCM, end ──
    def spoken_en(ws, handles):
        handles["net"].llm_reply = REPLY_EN
        handles["stt"]["transcript"] = "What is Mari's net profit?"
        ws.send_json({"type": "start", "lang": "en", "avatar": "female", "history": []})
        for _ in range(3):
            ws.send_bytes(PCM_FRAME)
        ws.send_json({"type": "end", "spoke": True})

    scenario("spoken/en/female", a2f=False, drive=spoken_en)
    scenario("spoken/en/female/a2f", a2f=True, drive=spoken_en)

    # ── a spoken Urdu turn: PCM is relayed to Soniox, partials come back ──
    def spoken_ur(ws, handles):
        handles["net"].llm_reply = REPLY_UR
        FakeSonioxStream.transcript = "ماری انرجیز کا منافع کتنا ہے؟"
        FakeSonioxStream.partials = ("ماری", "ماری انرجیز", "ماری انرجیز کا منافع")
        ws.send_json({"type": "start", "lang": "ur", "avatar": "male", "history": HISTORY})
        for _ in range(3):
            ws.send_bytes(PCM_FRAME)
        ws.send_json({"type": "end", "spoke": True})

    scenario("spoken/ur/male", a2f=False, drive=spoken_ur)
    scenario("spoken/ur/male/a2f", a2f=True, drive=spoken_ur)
    FakeSonioxStream.partials = ()

    # ── a typed turn: no transcript echo, no STT ──
    def typed(ws, handles):
        handles["net"].llm_reply = REPLY_EN
        ws.send_json(
            {
                "type": "text",
                "text": "Please introduce yourself",
                "lang": "en",
                "avatar": "female",
                "history": HISTORY,
            }
        )

    scenario("typed/en/female", a2f=False, drive=typed)
    scenario("typed/en/female/a2f", a2f=True, drive=typed)

    # ── empty transcript: the browser VAD's verdict decides ──
    def empty(spoke: bool):
        def drive(ws, handles):
            handles["net"].llm_reply = REPLY_EN
            handles["stt"]["transcript"] = ""
            ws.send_json({"type": "start", "lang": "en", "avatar": "female", "history": []})
            ws.send_bytes(PCM_FRAME)
            ws.send_json({"type": "end", "spoke": spoke})

        return drive

    scenario("empty/spoke", a2f=False, drive=empty(True))
    scenario("empty/silent", a2f=False, drive=empty(False))

    # ── a bare {"end"}, as an older browser sends ──
    def legacy_end(ws, handles):
        handles["net"].llm_reply = REPLY_EN
        handles["stt"]["transcript"] = ""
        ws.send_json({"type": "start", "lang": "en"})
        ws.send_bytes(PCM_FRAME)
        ws.send_json({"type": "end"})

    scenario("legacy/bare_end", a2f=False, drive=legacy_end)

    # ── STT failure closes the turn with an error frame ──
    def stt_fails(ws, handles):
        handles["stt"]["error"] = "whisper unreachable"
        ws.send_json({"type": "start", "lang": "en", "avatar": "female", "history": []})
        ws.send_bytes(PCM_FRAME)
        ws.send_json({"type": "end", "spoke": True})

    scenario("error/stt", a2f=False, drive=stt_fails)

    # ── Soniox refusing to open is reported, not swallowed ──
    def soniox_fails(ws, handles):
        FakeSonioxStream.fail_on_start = True
        try:
            ws.send_json({"type": "start", "lang": "ur", "avatar": "female", "history": []})
        finally:
            FakeSonioxStream.fail_on_start = False

    scenario("error/soniox_open", a2f=False, drive=soniox_fails)

    # ── the LLM stream breaking mid-reply ──
    for mode in ("error_frame", "midstream_fail", "connect_fail"):
        def llm_broken(ws, handles, mode=mode):
            handles["net"].llm_reply = REPLY_EN
            handles["net"].llm_mode = mode
            handles["stt"]["transcript"] = "What is Mari's net profit?"
            ws.send_json({"type": "start", "lang": "en", "avatar": "female", "history": []})
            ws.send_bytes(PCM_FRAME)
            ws.send_json({"type": "end", "spoke": True})

        scenario(f"error/llm_{mode}", a2f=False, drive=llm_broken)

    # ── one sentence's TTS failing: a warn frame, the turn goes on ──
    def tts_fails(ws, handles):
        handles["net"].llm_reply = REPLY_EN
        handles["stt"]["transcript"] = "What is Mari's net profit?"
        # The first sentence only; the rest must still be spoken.
        handles["tts_fail_for"].add("Hello!")
        ws.send_json({"type": "start", "lang": "en", "avatar": "female", "history": []})
        ws.send_bytes(PCM_FRAME)
        ws.send_json({"type": "end", "spoke": True})

    scenario("error/tts_one_sentence", a2f=True, drive=tts_fails)

    # ── the visitor walks away: the socket closes before {"end"} ──
    def disconnect(ws, handles):
        handles["net"].llm_reply = REPLY_EN
        ws.send_json({"type": "start", "lang": "en", "avatar": "female", "history": []})
        ws.send_bytes(PCM_FRAME)
        ws.close()

    scenario("disconnect/before_end", a2f=False, drive=disconnect)

    # ── an unknown avatar id falls back rather than reaching TTS ──
    def unknown_avatar(ws, handles):
        handles["net"].llm_reply = REPLY_EN
        handles["stt"]["transcript"] = "hello"
        ws.send_json({"type": "start", "lang": "en", "avatar": "robot", "history": []})
        ws.send_bytes(PCM_FRAME)
        ws.send_json({"type": "end", "spoke": True})

    scenario("fallback/unknown_avatar", a2f=False, drive=unknown_avatar)

    # ── an unknown language id likewise ──
    def unknown_lang(ws, handles):
        handles["net"].llm_reply = REPLY_EN
        handles["stt"]["transcript"] = "hello"
        ws.send_json({"type": "start", "lang": "fr", "avatar": "female", "history": []})
        ws.send_bytes(PCM_FRAME)
        ws.send_json({"type": "end", "spoke": True})

    scenario("fallback/unknown_lang", a2f=False, drive=unknown_lang)

    return out


def collect(setattr_) -> dict:
    sys.path.insert(0, str(ROOT))
    return {"scenarios": run_scenarios(api(), setattr_)}


if __name__ == "__main__":
    if "--write" not in sys.argv:
        sys.exit("refusing to overwrite the ws fixture without --write")

    def plain_setattr(obj, name, value):
        setattr(obj, name, value)

    data = collect(plain_setattr)
    FIXTURE.parent.mkdir(parents=True, exist_ok=True)
    FIXTURE.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"wrote {FIXTURE} ({FIXTURE.stat().st_size // 1024} KB)")
