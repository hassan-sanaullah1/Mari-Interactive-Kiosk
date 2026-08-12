/* MARI · Voice — client
 * One-tap voice loop:
 *   tap -> LISTEN (browser speech recognition, auto-stops on silence, orb reacts to mic)
 *       -> THINK  (transcript POSTed to /chat, MARI answers from the LLM)
 *       -> SPEAK  (reply spoken via SpeechSynthesis, orb pulses to the cadence)
 *       -> IDLE
 * No second tap: recognition endpoints itself when you stop talking. Tapping again at
 * any time cancels the current turn.
 */

const $ = (id) => document.getElementById(id);

const els = {
  body: document.body,
  orb: $("orb"),
  statusLabel: $("statusLabel"),
  statusCaption: $("statusCaption"),
  transcript: $("transcript"),
  micBtn: $("micBtn"),
  hint: $("hint"),
  toast: $("toast"),
  langToggle: $("langToggle"),
};

const COPY = {
  en: {
    idle:      ["Tap to start", "Then just talk — MARI keeps listening"],
    listening: ["Listening…", "Just speak — pause when you're done"],
    thinking:  ["Thinking…", "MARI is composing a reply"],
    speaking:  ["Speaking", "MARI is responding"],
    denied:    "Microphone access is needed to talk to MARI.",
    nospeech:  "Paused — tap to start again.",
    unsupported: "Voice input needs Chrome or Edge on this device.",
    hint:      "Tap once to begin. MARI keeps listening turn after turn — tap again to stop.",
    you: "You", mari: "MARI",
  },
  ur: {
    idle:      ["شروع کرنے کے لیے دبائیں", "پھر بس بولیں — ماری سنتا رہے گا"],
    listening: ["سن رہا ہے…", "بس بولیں — مکمل ہونے پر رکیں"],
    thinking:  ["سوچ رہا ہے…", "ماری جواب تیار کر رہا ہے"],
    speaking:  ["بول رہا ہے", "ماری جواب دے رہا ہے"],
    denied:    "ماری سے بات کرنے کے لیے مائیکروفون کی اجازت درکار ہے۔",
    nospeech:  "رک گیا — دوبارہ شروع کرنے کے لیے دبائیں۔",
    unsupported: "صوتی ان پٹ کے لیے Chrome یا Edge درکار ہے۔",
    hint:      "ایک بار دبائیں۔ ماری ہر بار سنتا رہے گا — روکنے کے لیے دوبارہ دبائیں۔",
    you: "آپ", mari: "ماری",
  },
};

const state = {
  mode: "idle",           // idle | listening | thinking | speaking
  lang: "en",
  level: 0,               // smoothed 0..1 amplitude driving the orb
  targetLevel: 0,
  ac: null,               // AudioContext (reused across turns)
  media: null,            // mic MediaStream
  source: null,           // MediaStreamSource
  processor: null,        // ScriptProcessorNode (capture + level metering)
  frames: [],             // captured Float32 chunks
  srcRate: 16000,         // actual capture sample rate
  vad: null,              // { started, silence, elapsed }
  audioEl: null,          // reply playback element
  cancelled: false,       // user tapped to abort this turn
  session: false,         // conversation is active (hands-free loop)
};

const TARGET_SR = 16000;
// voice-activity thresholds (RMS on the mic signal). Shorter silence = snappier turn end.
const VAD = { start: 0.025, stop: 0.015, silenceMs: 600, preSpeechMs: 8000, maxMs: 20000 };

/* ------------------------------------------------------------------ *
 * Orb renderer — a wobbling gradient blob on a hi-dpi canvas.
 * ------------------------------------------------------------------ */
const orb = (() => {
  const cv = els.orb;
  const ctx = cv.getContext("2d");
  let W = 0, H = 0, R = 0, cx = 0, cy = 0, dpr = 1;
  let t = 0;

  const palettes = {
    idle:      ["#6d5cff", "#00d4ff", "#8f6dff"],
    listening: ["#00d4ff", "#38ffb3", "#6d5cff"],
    thinking:  ["#b06dff", "#6d5cff", "#ff5c9d"],
    speaking:  ["#38ffb3", "#00d4ff", "#6d5cff"],
  };

  function resize() {
    dpr = Math.min(window.devicePixelRatio || 1, 2);
    const size = cv.clientWidth;
    W = cv.width = size * dpr;
    H = cv.height = size * dpr;
    R = (W / 2) * 0.62;
    cx = W / 2; cy = H / 2;
  }

  function blobPath(radius, level, seed) {
    ctx.beginPath();
    const pts = 96;
    for (let i = 0; i <= pts; i++) {
      const a = (i / pts) * Math.PI * 2;
      // layered sines give an organic, non-repeating wobble
      const wob =
        Math.sin(a * 3 + t * 1.1 + seed) * 0.045 +
        Math.sin(a * 5 - t * 0.8 + seed) * 0.03 +
        Math.sin(a * 2 + t * 0.5) * 0.02;
      const r = radius * (1 + wob * (0.5 + level * 2.2) + level * 0.14);
      const x = cx + Math.cos(a) * r;
      const y = cy + Math.sin(a) * r;
      i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
    }
    ctx.closePath();
  }

  function frame() {
    t += 0.016;
    // ease displayed level toward target
    state.level += (state.targetLevel - state.level) * 0.12;
    const lv = state.level;
    const pal = palettes[state.mode] || palettes.idle;

    ctx.clearRect(0, 0, W, H);

    const pulse = 1 + Math.sin(t * 2) * 0.015 + lv * 0.12;
    const baseR = R * pulse;

    // outer soft aura
    const aura = ctx.createRadialGradient(cx, cy, baseR * 0.4, cx, cy, baseR * 1.7);
    aura.addColorStop(0, hexA(pal[0], 0.35 + lv * 0.3));
    aura.addColorStop(1, hexA(pal[0], 0));
    blobPath(baseR * 1.35, lv * 0.6, 10);
    ctx.fillStyle = aura;
    ctx.fill();

    // main body gradient (angled so it feels like it has a light source)
    const g = ctx.createLinearGradient(cx - baseR, cy - baseR, cx + baseR, cy + baseR);
    g.addColorStop(0, pal[0]);
    g.addColorStop(0.5, pal[1]);
    g.addColorStop(1, pal[2]);
    blobPath(baseR, lv, 0);
    ctx.fillStyle = g;
    ctx.shadowColor = hexA(pal[1], 0.6);
    ctx.shadowBlur = 40 * dpr + lv * 40;
    ctx.fill();
    ctx.shadowBlur = 0;

    // inner counter-rotating highlight ring
    blobPath(baseR * (0.62 - lv * 0.05), lv * 0.8, 3.2);
    ctx.fillStyle = hexA("#ffffff", 0.10 + lv * 0.18);
    ctx.fill();

    // glossy top highlight
    const hl = ctx.createRadialGradient(cx, cy - baseR * 0.4, 0, cx, cy - baseR * 0.4, baseR * 0.9);
    hl.addColorStop(0, hexA("#ffffff", 0.30));
    hl.addColorStop(1, hexA("#ffffff", 0));
    blobPath(baseR * 0.96, lv, 0);
    ctx.fillStyle = hl;
    ctx.fill();

    state.raf = requestAnimationFrame(frame);
  }

  function hexA(hex, a) {
    const n = parseInt(hex.slice(1), 16);
    return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${a})`;
  }

  window.addEventListener("resize", resize);
  resize();
  frame();
  return { resize };
})();

/* ------------------------------------------------------------------ *
 * State machine + UI
 * ------------------------------------------------------------------ */
function setMode(mode) {
  state.mode = mode;
  els.body.dataset.state = mode;
  const c = COPY[state.lang][mode];
  els.statusLabel.textContent = c[0];
  els.statusCaption.textContent = c[1];
  if (mode === "idle") state.targetLevel = 0;
}

function showTranscript(who, text, lang) {
  els.transcript.className = "transcript show" + (lang === "ur" ? " ur" : "");
  els.transcript.innerHTML = `<span class="who">${who}</span>${escapeHtml(text)}`;
}

function toast(msg) {
  els.toast.textContent = msg;
  els.toast.classList.add("show");
  clearTimeout(toast._t);
  toast._t = setTimeout(() => els.toast.classList.remove("show"), 3200);
}

function escapeHtml(s) {
  return s.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}

/* ------------------------------------------------------------------ *
 * One tap: capture mic (auto-stop on silence) -> /voice -> speak reply
 * The browser records 16 kHz mono audio and detects when you stop talking;
 * the server does STT (Soniox/Whisper) -> LLM (vLLM Qwen) -> TTS (Uplift/Kokoro).
 * ------------------------------------------------------------------ */
function wsURL() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  return `${proto}://${location.host}/ws`;
}

/* ------------------------------------------------------------------ *
 * One tap → open WS, stream 16 kHz PCM frames live while you speak (so STT runs
 * in real time), auto-stop on silence, then stream the reply sentence-by-sentence.
 * ------------------------------------------------------------------ */
async function startTurn() {
  try {
    state.media = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true, channelCount: 1 },
    });
  } catch {
    toast(COPY[state.lang].denied);
    return;
  }

  state.ac = state.ac || new (window.AudioContext || window.webkitAudioContext)();
  if (state.ac.state === "suspended") await state.ac.resume();
  state.srcRate = state.ac.sampleRate;
  state.cancelled = false;
  state._endPending = false;
  state.vad = { started: false, silence: 0, elapsed: 0 };
  state.queue = createAudioQueue();

  // ---- open the streaming socket + wire the reply handling ----
  const ws = new WebSocket(wsURL());
  ws.binaryType = "arraybuffer";
  state.ws = ws;
  const pending = [];          // frames captured before the socket is open
  let wsOpen = false;

  ws.onopen = () => {
    wsOpen = true;
    try { ws.send(JSON.stringify({ type: "start", lang: state.lang })); } catch {}
    for (const b of pending) { try { ws.send(b); } catch {} }
    pending.length = 0;
    if (state._endPending) { try { ws.send(JSON.stringify({ type: "end" })); } catch {} state._endPending = false; }
  };

  let pendingMime = "audio/mpeg", replyText = "", spokenAny = false, done = false;
  ws.onmessage = (ev) => {
    if (state.cancelled) return;
    if (typeof ev.data !== "string") { spokenAny = true; state.queue.push(ev.data, pendingMime); return; }
    const m = JSON.parse(ev.data);
    if (m.type === "partial" || m.type === "stt") {
      if (m.text) showTranscript(COPY[state.lang].you, m.text, state.lang);
    } else if (m.type === "reply") {
      replyText = (replyText + " " + m.text).trim();
      showTranscript(COPY[state.lang].mari, replyText, state.lang);
    } else if (m.type === "tts") {
      pendingMime = m.mime || pendingMime;
    } else if (m.type === "done") {
      done = true;
      state.queue.finish();
      if (!state.queue.busy()) {
        if (spokenAny) endOfTurn();
        else if (replyText) speakText(replyText);     // server TTS off -> browser voice
        else endOfTurn();                             // nothing heard -> listen again
      }
    } else if (m.type === "error") {
      toast(COPY[state.lang].nospeech);
      setMode("idle");
      try { ws.close(); } catch {}
    }
    // {warn}: a single sentence's TTS hiccuped — ignore, keep going
  };

  ws.onclose = () => {
    if (state.cancelled) return;
    if (!done && replyText && !state.queue.busy() && !spokenAny) speakText(replyText);
    else if (!done && !replyText && state.mode === "thinking") endOfTurn();
  };

  // ---- mic graph: meter for the orb, VAD for endpointing, stream each frame ----
  state.source = state.ac.createMediaStreamSource(state.media);
  const proc = state.ac.createScriptProcessor(4096, 1, 1);
  state.processor = proc;
  const frameMs = (proc.bufferSize / state.srcRate) * 1000;

  proc.onaudioprocess = (e) => {
    if (state.mode !== "listening") return;
    const input = e.inputBuffer.getChannelData(0);

    let sum = 0;
    for (let i = 0; i < input.length; i++) sum += input[i] * input[i];
    const rms = Math.sqrt(sum / input.length);
    state.targetLevel = Math.min(1, rms * 3.6);

    const buf = frameToPCM16(input, state.srcRate);
    if (wsOpen && ws.readyState === 1) { try { ws.send(buf); } catch {} }
    else pending.push(buf);

    const v = state.vad;
    v.elapsed += frameMs;
    if (rms > VAD.start) { v.started = true; v.silence = 0; }
    else if (v.started && rms < VAD.stop) { v.silence += frameMs; }

    if (v.started && v.silence >= VAD.silenceMs) return finishTurn();   // natural end
    if (v.started && v.elapsed >= VAD.maxMs) return finishTurn();       // hard cap
    if (!v.started && v.elapsed >= VAD.preSpeechMs) {                   // silence -> end session
      stopSession();
      toast(COPY[state.lang].nospeech);
    }
  };

  const mute = state.ac.createGain();     // keep the node alive without echoing the mic
  mute.gain.value = 0;
  state.source.connect(proc);
  proc.connect(mute);
  mute.connect(state.ac.destination);

  setMode("listening");
}

function teardownMic() {
  try { state.processor && (state.processor.onaudioprocess = null, state.processor.disconnect()); } catch {}
  try { state.source && state.source.disconnect(); } catch {}
  try { state.media && state.media.getTracks().forEach((t) => t.stop()); } catch {}
  state.processor = state.source = state.media = null;
}

function finishTurn() {
  teardownMic();
  setMode("thinking");
  if (state.ws && state.ws.readyState === 1) { try { state.ws.send(JSON.stringify({ type: "end" })); } catch {} }
  else state._endPending = true;     // socket not open yet — send end as soon as it is
}

function cancelTurn() {
  state.cancelled = true;
  teardownMic();
  try { state.ws && state.ws.close(); } catch {}
  try { state.queue && state.queue.stop(); } catch {}
  try { state.audioEl && state.audioEl.pause(); } catch {}
  try { speechSynthesis && speechSynthesis.cancel(); } catch {}
  synthEnvelope(false);
  setMode("idle");
}

/* After a reply finishes: in a live conversation, immediately listen again;
   otherwise fall back to idle. */
function endOfTurn() {
  if (state.session && !state.cancelled) startTurn();
  else setMode("idle");
}

function startSession() {
  state.session = true;
  els.body.dataset.session = "1";
  startTurn();
}

function stopSession() {
  state.session = false;
  delete els.body.dataset.session;
  cancelTurn();
}

/* Downsample one Float32 frame to 16 kHz and pack as little-endian PCM s16. */
function frameToPCM16(f, srcRate) {
  let s = f;
  if (srcRate !== TARGET_SR) {
    const n = Math.max(1, Math.round((f.length * TARGET_SR) / srcRate));
    s = new Float32Array(n);
    const ratio = (f.length - 1) / (n - 1 || 1);
    for (let i = 0; i < n; i++) {
      const x = i * ratio, i0 = Math.floor(x), i1 = Math.min(i0 + 1, f.length - 1);
      s[i] = f[i0] + (f[i1] - f[i0]) * (x - i0);
    }
  }
  const out = new Int16Array(s.length);
  for (let i = 0; i < s.length; i++) {
    const v = Math.max(-1, Math.min(1, s[i]));
    out[i] = v < 0 ? v * 0x8000 : v * 0x7fff;
  }
  return out.buffer;
}

/* Sequential playback of streamed audio sentences; orb reacts to whatever's playing. */
function createAudioQueue() {
  const urls = [];
  let playing = false, finished = false;

  function push(arrayBuffer, mime) {
    urls.push(URL.createObjectURL(new Blob([arrayBuffer], { type: mime })));
    if (!playing) playNext();
  }
  function playNext() {
    if (state.cancelled) return;
    const url = urls.shift();
    if (!url) { playing = false; if (finished) endOfTurn(); return; }
    playing = true;
    setMode("speaking");
    const el = new Audio(url);
    state.audioEl = el;
    attachOrbAnalyser(el);
    const next = () => { URL.revokeObjectURL(url); playNext(); };
    el.onended = next;
    el.onerror = next;
    el.play().catch(next);
  }
  return {
    push,
    finish() { finished = true; },
    busy() { return playing || urls.length > 0; },
    stop() { finished = true; urls.splice(0).forEach(URL.revokeObjectURL); playing = false; },
  };
}

function attachOrbAnalyser(el) {
  try {
    const src = state.ac.createMediaElementSource(el);
    const an = state.ac.createAnalyser();
    an.fftSize = 512;
    src.connect(an);
    an.connect(state.ac.destination);
    const buf = new Uint8Array(an.frequencyBinCount);
    const tick = () => {
      if (state.mode !== "speaking") return;
      an.getByteTimeDomainData(buf);
      let sum = 0;
      for (let i = 0; i < buf.length; i++) { const v = (buf[i] - 128) / 128; sum += v * v; }
      state.targetLevel = Math.min(1, Math.sqrt(sum / buf.length) * 3.6);
      requestAnimationFrame(tick);
    };
    tick();
  } catch {
    synthEnvelope(true);   // analyser unavailable — synthetic envelope
  }
}

/* ---- fallback speaking: browser TTS with a synthesized level envelope ---- */
function speakText(text) {
  setMode("speaking");
  showTranscript(COPY[state.lang].mari, text, state.lang);
  synthEnvelope(true);
  if ("speechSynthesis" in window) {
    const u = new SpeechSynthesisUtterance(text);
    u.lang = state.lang === "ur" ? "ur-PK" : "en-US";
    u.rate = 1;
    u.onend = () => { synthEnvelope(false); if (state.mode === "speaking") endOfTurn(); };
    u.onerror = () => { synthEnvelope(false); if (state.mode === "speaking") endOfTurn(); };
    speechSynthesis.cancel();
    speechSynthesis.speak(u);
  } else {
    setTimeout(() => { synthEnvelope(false); endOfTurn(); }, 2600);
  }
}

// pseudo speech-cadence level when we have no real waveform to analyse
function synthEnvelope(on) {
  if (!on) { synthEnvelope._on = false; state.targetLevel = 0; return; }
  synthEnvelope._on = true;
  const step = () => {
    if (!synthEnvelope._on) return;
    state.targetLevel = 0.18 + Math.random() * 0.55;
    setTimeout(step, 90 + Math.random() * 120);
  };
  step();
}

/* ------------------------------------------------------------------ *
 * Events
 * ------------------------------------------------------------------ */
// Tap once to start a hands-free conversation; tap again anytime to end it.
els.micBtn.addEventListener("click", () => {
  if (!state.session) startSession();
  else stopSession();
});

els.langToggle.addEventListener("click", (e) => {
  const btn = e.target.closest(".lang-btn");
  if (!btn) return;
  state.lang = btn.dataset.lang;
  [...els.langToggle.children].forEach((b) => b.classList.toggle("is-active", b === btn));
  document.documentElement.lang = state.lang;
  els.hint.textContent = COPY[state.lang].hint;
  setMode(state.mode);   // refresh copy
});

// init
setMode("idle");
els.hint.textContent = COPY.en.hint;
