"use client";

/**
 * useVoiceSession — React binding for the EXISTING speech-to-speech pipeline.
 *
 * This is a port of web/app.js onto React state; the wire protocol is unchanged and
 * the FastAPI side (server/app.py `ws()`) was not modified:
 *
 *   client → {"type":"start","lang"}  ·  <raw 16 kHz mono PCM16 frames>  ·  {"type":"end","spoke"}
 *   server → {"partial"|"stt", text} · per sentence {"reply",text} {"tts",mime,clip} <audio bytes>
 *          → {"done", spoken}   (or {"error"|"warn", message})
 *
 * The browser does capture + VAD endpointing; the server does STT → LLM → TTS.
 *
 * A typed message from the chat composer takes the same road with the capture half
 * cut off — {"type":"text",text,lang} instead of frames + {"end"} — so it comes back
 * as spoken, lip-synced audio rather than silent text.
 *
 * Audio2Face lipsync rides along on the same socket, additively: each sentence's
 * {"tts"} header now carries a `clip` id, and {"type":"lipsync",uid,names?,frames}
 * messages deliver that clip's ARKit blendshape keyframes. The audio path is
 * unchanged — the <audio> element that plays a sentence simply also becomes the
 * clock its lipsync clip is sampled against (see lib/blendshapePlayer.ts).
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { wsUrl } from "@/lib/endpoints";
import {
  beginClip,
  endClip,
  handleClipMessage,
  stop as stopLipsync,
  waitForFrames,
} from "@/lib/blendshapePlayer";
import type { Lang } from "@/lib/i18n";
import { DEFAULT_AVATAR, type AvatarId } from "@/components/avatar/models";

export type Mode = "idle" | "listening" | "thinking" | "speaking" | "paused";

export type Message = {
  id: string;
  role: "user" | "assistant";
  text: string;
};

const TARGET_SR = 16000;
/**
 * How long a sentence's audio waits for its Audio2Face frames before playing
 * anyway. Only the first sentence of a reply normally waits at all — see
 * waitForFrames() in lib/blendshapePlayer.ts.
 */
const CLIP_FRAME_WAIT_MS = 700;
/**
 * RMS thresholds for endpointing. silenceMs was 600 — short enough that an
 * ordinary mid-sentence breath or thinking pause ended the turn early
 * ("half sentence" cutoffs); 1200ms gives a real pause room without making
 * genuine end-of-turn silence feel laggy.
 *
 * `start` is how loud the room has to get before the turn counts as speech, and
 * it is the one number here that can lose a turn outright: below it the VAD never
 * starts, so preSpeechMs eventually closes the turn with no audio and the visitor
 * is never heard at all. A kiosk is used at arm's length, in a room with other
 * people in it, by someone who may not lean in — 0.045 was deaf to a normal
 * speaking voice at that distance, and turns were dying on the pre-speech timeout
 * rather than on anything the visitor did. Erring low is the safe direction: a
 * false start costs a moment of silence at the head of the clip, which STT
 * discards, while a missed start costs the whole turn.
 *
 * `stop` sits below `start` deliberately (hysteresis) — once speech is running,
 * it takes a quieter room to end it than it took to begin it, so the level
 * drifting around one threshold cannot chop a sentence in half.
 */
/**
 * `startMs` is how long the level has to stay above `start` before the turn counts as
 * speech. A single frame over the threshold used to be enough, which is why tapping the
 * mic in a room that is merely NOT SILENT — a fan, a projector, other visitors, the
 * kiosk's own hum — marked the turn as spoken, sent no speech to STT, and got the
 * "sorry, I didn't catch that" apology back. One 4096-sample frame is ~85ms at 48kHz,
 * so 250ms is roughly three consecutive frames: far too long for a door click or a
 * chair scrape to fake, and still shorter than the first syllable of a real word.
 *
 * `noiseMargin` is the other half of that fix. A fixed threshold cannot be right for
 * both a silent office and a busy hall, so the first `calibrateMs` of every turn are
 * used to measure the room instead of being tested against a constant: the effective
 * start threshold becomes whichever is higher, `start` or the measured floor times this
 * margin. Speech is several times louder than the noise it sits on, so a voice clears
 * it comfortably while the noise itself never does.
 */
const VAD = {
  start: 0.02,
  stop: 0.012,
  // 1200 cut people off mid-sentence: it is the length of pause tolerated, and an
  // ordinary one for breath or thought reaches ~1.2s. The cost is symmetric — this is
  // also how long after a real end-of-turn the kiosk waits before answering — so it
  // buys ~250ms more thinking room for ~250ms more latency, which is the right trade
  // at a kiosk where being cut off means repeating the whole question.
  silenceMs: 1500,
  preSpeechMs: 8000,
  maxMs: 20000,
  startMs: 250,
  calibrateMs: 300,
  noiseMargin: 2.2,
  // Frames louder than this are speech, not room tone, and are excluded from the noise
  // estimate. Set well above any plausible room and below a normal speaking voice.
  noiseCeiling: 0.06,
  // Hard cap on the calibrated start threshold. However loud the room measures, a
  // normal speaking voice has to be able to cross it — an uncrossable threshold is a
  // deaf kiosk, which is a far worse failure than an occasional false start.
  startCeiling: 0.055,
};

/** Downsample one Float32 frame to 16 kHz and pack as little-endian PCM s16. */
function frameToPCM16(f: Float32Array, srcRate: number): ArrayBuffer {
  let s = f;
  if (srcRate !== TARGET_SR) {
    const n = Math.max(1, Math.round((f.length * TARGET_SR) / srcRate));
    s = new Float32Array(n);
    const ratio = (f.length - 1) / (n - 1 || 1);
    for (let i = 0; i < n; i++) {
      const x = i * ratio;
      const i0 = Math.floor(x);
      const i1 = Math.min(i0 + 1, f.length - 1);
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

/** One turn's worth of reply audio, played sentence by sentence as it streams in. */
type ReplyQueue = {
  push: (b: ArrayBuffer, mime: string, clip: string | null) => void;
  finish: () => void;
  busy: () => boolean;
  stop: () => void;
  resume: () => void;
};

let uid = 0;
const nextId = () => `m${++uid}`;

export function useVoiceSession(lang: Lang, avatar: AvatarId = DEFAULT_AVATAR) {
  const [mode, setMode] = useState<Mode>("idle");
  const [active, setActive] = useState(false);
  const [messages, setMessages] = useState<Message[]>([]);
  const [partial, setPartial] = useState("");
  const [error, setError] = useState<string | null>(null);

  /** Smoothed mic/output amplitude 0..1, read by the mic button's rAF loop. */
  const levelRef = useRef(0);

  // ---- mutable audio-graph state (never drives rendering directly) ----
  const langRef = useRef(lang);
  /**
   * Which presenter is on screen, mirrored out of state for the same reason as
   * `lang`: the socket callbacks close over their turn, and this has to be the
   * value at the moment the turn is SENT. It rides along on {start}/{text} and
   * picks the reply voice server-side (see providers.get_tts_provider).
   */
  const avatarRef = useRef(avatar);
  const acRef = useRef<AudioContext | null>(null);
  const mediaRef = useRef<MediaStream | null>(null);
  const sourceRef = useRef<MediaStreamAudioSourceNode | null>(null);
  const procRef = useRef<ScriptProcessorNode | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const audioElRef = useRef<HTMLAudioElement | null>(null);
  const activeRef = useRef(false);
  const pausedRef = useRef(false);
  const cancelledRef = useRef(false);
  const endPendingRef = useRef(false);
  /** Whether the turn whose {"end"} is deferred had speech in it. */
  const endSpokeRef = useRef(false);
  const assistantIdRef = useRef<string | null>(null);
  /** Media elements can only be routed through an AnalyserNode once. */
  const analysedRef = useRef(new WeakSet<HTMLAudioElement>());
  /**
   * The conversation so far, mirrored out of React state so the socket callbacks
   * (which close over their turn) always read the current transcript. This is the
   * whole of MARI's memory: it lives in the tab, is sent up with each turn, and is
   * gone on reload — a kiosk greets the next visitor with a clean slate.
   */
  const historyRef = useRef<Message[]>([]);

  useEffect(() => {
    historyRef.current = messages;
  }, [messages]);

  useEffect(() => {
    langRef.current = lang;
  }, [lang]);

  useEffect(() => {
    avatarRef.current = avatar;
  }, [avatar]);

  /** Prior turns, in the shape the server's _history_messages() expects. */
  const historyPayload = useCallback(
    () => historyRef.current.map(({ role, text }) => ({ role, text })),
    [],
  );

  /** Queue of streamed reply sentences, played back-to-back. */
  const queueRef = useRef<ReplyQueue | null>(null);

  /** The one AudioContext, created (and un-suspended) on a user gesture. */
  const ensureAudioContext = useCallback(async () => {
    const AC =
      window.AudioContext ||
      (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
    acRef.current = acRef.current ?? new AC();
    const ac = acRef.current;
    if (ac.state === "suspended") await ac.resume();
    return ac;
  }, []);

  const teardownMic = useCallback(() => {
    try {
      if (procRef.current) {
        procRef.current.onaudioprocess = null;
        procRef.current.disconnect();
      }
    } catch {}
    try {
      sourceRef.current?.disconnect();
    } catch {}
    try {
      mediaRef.current?.getTracks().forEach((t) => t.stop());
    } catch {}
    procRef.current = null;
    sourceRef.current = null;
    mediaRef.current = null;
    levelRef.current = 0;
  }, []);

  const startTurnRef = useRef<() => void>(() => {});

  /** A reply finished: keep the hands-free loop going, or fall back to idle. */
  const endOfTurn = useCallback(() => {
    setPartial("");
    assistantIdRef.current = null;
    if (activeRef.current && !pausedRef.current && !cancelledRef.current) startTurnRef.current();
    else setMode(activeRef.current ? "paused" : "idle");
  }, []);

  const attachAnalyser = useCallback((el: HTMLAudioElement) => {
    const ac = acRef.current;
    if (!ac || analysedRef.current.has(el)) return;
    try {
      const src = ac.createMediaElementSource(el);
      analysedRef.current.add(el);
      const an = ac.createAnalyser();
      an.fftSize = 512;
      src.connect(an);
      an.connect(ac.destination);
      const buf = new Uint8Array(an.frequencyBinCount);
      const tick = () => {
        if (el.paused || el.ended) {
          levelRef.current = 0;
          return;
        }
        an.getByteTimeDomainData(buf);
        let sum = 0;
        for (let i = 0; i < buf.length; i++) {
          const v = (buf[i] - 128) / 128;
          sum += v * v;
        }
        levelRef.current = Math.min(1, Math.sqrt(sum / buf.length) * 3.6);
        requestAnimationFrame(tick);
      };
      tick();
    } catch {
      /* analyser unavailable — the button just won't react to the waveform */
    }
  }, []);

  const createQueue = useCallback(() => {
    /** One entry per reply sentence: its audio, and the A2F clip that matches it. */
    const items: { url: string; clip: string | null }[] = [];
    let playing = false;
    let finished = false;
    let stopped = false;

    const playNext = () => {
      if (cancelledRef.current) return;
      if (pausedRef.current) {
        playing = false;
        return;
      }
      const item = items.shift();
      if (!item) {
        playing = false;
        if (finished) endOfTurn();
        return;
      }
      playing = true;
      setMode("speaking");
      const el = new Audio(item.url);
      audioElRef.current = el;
      attachAnalyser(el);
      const next = () => {
        if (item.clip) endClip(item.clip);
        URL.revokeObjectURL(item.url);
        audioElRef.current = null;
        playNext();
      };
      el.onended = next;
      el.onerror = next;

      const start = () => {
        if (cancelledRef.current) return;
        // The element's own playhead is the lipsync clock, so the mouth follows
        // the audio the user is actually hearing — including when playback
        // starts late, or is paused and resumed mid-sentence.
        if (item.clip) beginClip(item.clip, () => el.currentTime);
        // If the turn was paused while we waited, leave it cued: togglePause's
        // resume path plays it, and the clock is already attached.
        if (!pausedRef.current) el.play().catch(next);
      };

      // Give this sentence's blendshapes a moment to land, so the mouth is
      // already moving on the first syllable rather than a beat behind it.
      if (item.clip) void waitForFrames(item.clip, CLIP_FRAME_WAIT_MS).then(start);
      else start();
    };

    const queue: ReplyQueue = {
      push(b: ArrayBuffer, mime: string, clip: string | null) {
        if (stopped) return;
        items.push({ url: URL.createObjectURL(new Blob([b], { type: mime })), clip });
        if (!playing) playNext();
      },
      finish() {
        if (stopped) return;
        finished = true;
        if (!playing && !items.length) endOfTurn();
      },
      busy: () => playing || items.length > 0,
      stop() {
        stopped = true;
        finished = true;
        items.splice(0).forEach((i) => URL.revokeObjectURL(i.url));
        playing = false;
        stopLipsync();
      },
      resume() {
        if (!stopped && !playing) playNext();
      },
    };
    return queue;
  }, [attachAnalyser, endOfTurn]);

  /**
   * Wire a socket's reply side: transcript/text events, and the per-sentence
   * audio + Audio2Face clips that the queue plays. Shared by both kinds of turn —
   * a spoken one (mic → STT) and a typed one — so a message from the chat
   * composer is spoken and lip-synced exactly like a spoken question.
   */
  const bindReplyStream = useCallback((ws: WebSocket, queue: ReplyQueue) => {
    let pendingMime = "audio/mpeg";
    /** Clip id from the pending {"tts"} header, applied to the next audio blob. */
    let pendingClip: string | null = null;
    let done = false;

    ws.onmessage = (ev: MessageEvent) => {
      if (cancelledRef.current) return;

      if (typeof ev.data !== "string") {
        queue.push(ev.data as ArrayBuffer, pendingMime, pendingClip);
        pendingClip = null; // one clip id per audio blob
        return;
      }

      let m: Record<string, unknown>;
      try {
        m = JSON.parse(ev.data);
      } catch {
        return;
      }

      if (m.type === "lipsync") {
        // Audio2Face frames for one sentence — buffered until its audio plays.
        handleClipMessage(m as Parameters<typeof handleClipMessage>[0]);
        return;
      }

      if (m.type === "partial") {
        if (typeof m.text === "string") setPartial(m.text);
      } else if (m.type === "stt") {
        const text = typeof m.text === "string" ? m.text.trim() : "";
        setPartial("");
        if (text) setMessages((prev) => [...prev, { id: nextId(), role: "user", text }]);
      } else if (m.type === "reply") {
        const text = typeof m.text === "string" ? m.text : "";
        if (!text) return;
        setMessages((prev) => {
          const id = assistantIdRef.current;
          if (id) {
            return prev.map((msg) =>
              msg.id === id ? { ...msg, text: `${msg.text} ${text}`.trim() } : msg,
            );
          }
          const fresh = nextId();
          assistantIdRef.current = fresh;
          return [...prev, { id: fresh, role: "assistant", text }];
        });
      } else if (m.type === "tts") {
        if (typeof m.mime === "string") pendingMime = m.mime;
        pendingClip = typeof m.clip === "string" ? m.clip : null;
      } else if (m.type === "done") {
        done = true;
        // finish() owns the hand-off: it ends the turn now if nothing is queued,
        // otherwise the queue ends it once the last sentence has played out.
        queue.finish();
      } else if (m.type === "error") {
        setError("no-speech");
        setMode(activeRef.current ? "paused" : "idle");
        try {
          ws.close();
        } catch {}
      }
      // {"warn"}: one sentence's TTS hiccuped — keep going, same as before
    };

    ws.onclose = () => {
      if (cancelledRef.current || done) return;
      // Server hung up without {done} — close the turn out the same way, so a
      // half-delivered reply still finishes playing instead of stalling the loop.
      queue.finish();
    };
  }, []);

  /**
   * End the capture and ask the server to answer.
   *
   * `spoke` is whether the VAD ever heard speech in this turn. It has to travel
   * with the {"end"}, because the two ways a turn can end look identical from the
   * server side — both arrive as an empty transcript — but mean opposite things:
   * a turn the visitor spoke into whose transcript was lost deserves "sorry, I
   * didn't catch that", while the hands-free loop simply timing out on an empty
   * room must stay silent. Without this flag the kiosk answered its own silence
   * and then re-opened the mic, which timed out again — talking to nobody, on a
   * loop, every 8 seconds.
   */
  const finishTurn = useCallback((spoke: boolean) => {
    teardownMic();
    setMode("thinking");
    endSpokeRef.current = spoke;
    const ws = wsRef.current;
    if (ws && ws.readyState === WebSocket.OPEN) {
      try {
        ws.send(JSON.stringify({ type: "end", spoke }));
      } catch {}
    } else {
      endPendingRef.current = true; // socket not open yet — send as soon as it is
    }
  }, [teardownMic]);

  const startTurn = useCallback(async () => {
    setError(null);
    try {
      mediaRef.current = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, channelCount: 1 },
      });
    } catch {
      setError("mic-denied");
      activeRef.current = false;
      setActive(false);
      setMode("idle");
      return;
    }

    const ac = await ensureAudioContext();

    cancelledRef.current = false;
    endPendingRef.current = false;
    // A new turn always starts a new reply bubble, exactly as sendText does.
    // Without this the turn inherits whatever assistantIdRef was left holding,
    // and bindReplyStream's {"reply"} branch appends this turn's sentences onto
    // the PREVIOUS answer instead of creating one below the new question — so
    // the spoken reply looks missing while a typed one (which clears the ref
    // itself) looks fine. endOfTurn clears it too, but only on the path where
    // the reply audio plays to the end; an interrupted, paused or stopped queue
    // never gets there.
    assistantIdRef.current = null;
    // `loud` accumulates consecutive time above the threshold (reset by any quiet
    // frame), so only SUSTAINED sound starts the turn. `noise` is the running floor
    // measured during the first calibrateMs; `frames` counts what went into it.
    const vad = { started: false, silence: 0, elapsed: 0, loud: 0, noise: 0, frames: 0 };
    const queue = createQueue();
    queueRef.current = queue;

    // ---- socket ----
    const ws = new WebSocket(wsUrl());
    ws.binaryType = "arraybuffer";
    wsRef.current = ws;
    const pending: ArrayBuffer[] = [];
    let wsOpen = false;

    ws.onopen = () => {
      wsOpen = true;
      try {
        ws.send(
          JSON.stringify({
            type: "start",
            lang: langRef.current,
            avatar: avatarRef.current,
            history: historyPayload(),
          }),
        );
      } catch {}
      for (const b of pending) {
        try {
          ws.send(b);
        } catch {}
      }
      pending.length = 0;
      if (endPendingRef.current) {
        try {
          ws.send(JSON.stringify({ type: "end", spoke: endSpokeRef.current }));
        } catch {}
        endPendingRef.current = false;
      }
    };

    bindReplyStream(ws, queue);

    // ---- mic graph: level meter + VAD endpointing + live PCM upload ----
    const srcRate = ac.sampleRate;
    const source = ac.createMediaStreamSource(mediaRef.current);
    sourceRef.current = source;
    const proc = ac.createScriptProcessor(4096, 1, 1);
    procRef.current = proc;
    const frameMs = (proc.bufferSize / srcRate) * 1000;

    proc.onaudioprocess = (e) => {
      const input = e.inputBuffer.getChannelData(0);
      let sum = 0;
      for (let i = 0; i < input.length; i++) sum += input[i] * input[i];
      const rms = Math.sqrt(sum / input.length);
      levelRef.current = Math.min(1, rms * 3.6);

      const buf = frameToPCM16(input, srcRate);
      if (wsOpen && ws.readyState === WebSocket.OPEN) {
        try {
          ws.send(buf);
        } catch {}
      } else {
        pending.push(buf);
      }

      vad.elapsed += frameMs;

      // Measure the room before judging it. These opening frames are still uploaded —
      // only the speech DECISION waits, so nothing the visitor says is lost.
      //
      // Only QUIET frames feed the estimate. A visitor who starts talking the instant
      // the mic opens would otherwise have their own voice averaged in as "the room",
      // and the threshold derived from it lands above their speech: the VAD then never
      // starts, and the turn dies on the pre-speech timeout having heard every word.
      // Anything above `noiseCeiling` is a voice, not a room, so it is not sampled.
      if (vad.elapsed <= VAD.calibrateMs && rms < VAD.noiseCeiling) {
        vad.noise += rms;
        vad.frames += 1;
      }
      const floor = vad.frames > 0 ? vad.noise / vad.frames : 0;
      // Never let calibration RAISE the bar beyond what a voice clears comfortably:
      // the measured floor only lifts the threshold in a genuinely noisy room, and even
      // then not past `startCeiling`.
      const startAt = Math.min(
        VAD.startCeiling,
        Math.max(VAD.start, floor * VAD.noiseMargin),
      );
      // End-of-turn threshold. Must stay BELOW startAt (hysteresis): once speech is
      // running it takes a quieter room to end it than it took to begin. Deriving this
      // from the floor directly — rather than from the already-margined startAt — is
      // what keeps an ordinary between-words dip from reading as silence and cutting
      // the visitor off mid-sentence.
      const stopAt = Math.min(startAt * 0.6, Math.max(VAD.stop, floor * 1.1));

      if (rms > startAt) {
        // Sustained, not instantaneous: a lone loud frame is a noise, not a word.
        vad.loud += frameMs;
        if (vad.loud >= VAD.startMs) {
          vad.started = true;
          vad.silence = 0;
        }
      } else {
        vad.loud = 0;
        if (vad.started && rms < stopAt) {
          vad.silence += frameMs;
        }
      }

      if (vad.started && (vad.silence >= VAD.silenceMs || vad.elapsed >= VAD.maxMs)) {
        proc.onaudioprocess = null;
        finishTurn(true); // they spoke — a lost transcript is worth apologising for
      } else if (!vad.started && vad.elapsed >= VAD.preSpeechMs) {
        proc.onaudioprocess = null;
        finishTurn(false); // nobody spoke — close the turn out in silence
      }
    };

    const mute = ac.createGain(); // keeps the node pulling without echoing the mic
    mute.gain.value = 0;
    source.connect(proc);
    proc.connect(mute);
    mute.connect(ac.destination);

    setMode("listening");
  }, [bindReplyStream, createQueue, endOfTurn, ensureAudioContext, finishTurn, historyPayload]);

  startTurnRef.current = () => void startTurn();

  /** Hard stop: abandon the turn and the session. */
  const stop = useCallback(() => {
    cancelledRef.current = true;
    activeRef.current = false;
    pausedRef.current = false;
    setActive(false);
    teardownMic();
    try {
      wsRef.current?.close();
    } catch {}
    queueRef.current?.stop();
    stopLipsync();
    try {
      audioElRef.current?.pause();
    } catch {}
    audioElRef.current = null;
    assistantIdRef.current = null;
    setPartial("");
    setMode("idle");
  }, [teardownMic]);

  /** End the turn and wipe the transcript — the dock's ✕ in every state. */
  const endAndClear = useCallback(() => {
    stop();
    // Wiping the transcript wipes the memory with it — the ✕ is how a visitor
    // hands the kiosk to the next person.
    historyRef.current = [];
    setMessages([]);
    setPartial("");
    setError(null);
  }, [stop]);

  const start = useCallback(() => {
    activeRef.current = true;
    pausedRef.current = false;
    setActive(true);
    void startTurn();
  }, [startTurn]);

  const toggle = useCallback(() => {
    if (activeRef.current) stop();
    else start();
  }, [start, stop]);

  /** Hold the conversation: pause playback, or drop the mic mid-listen. */
  const togglePause = useCallback(() => {
    if (!activeRef.current) return;
    if (pausedRef.current) {
      pausedRef.current = false;
      const el = audioElRef.current;
      if (el && el.paused && !el.ended) {
        void el.play();
        setMode("speaking");
      } else if (queueRef.current?.busy()) {
        queueRef.current.resume();
      } else {
        void startTurn();
      }
    } else {
      pausedRef.current = true;
      try {
        audioElRef.current?.pause();
      } catch {}
      teardownMic();
      try {
        if (wsRef.current?.readyState === WebSocket.OPEN && mode === "listening") wsRef.current.close();
      } catch {}
      levelRef.current = 0;
      setMode("paused");
    }
  }, [mode, startTurn, teardownMic]);

  /**
   * Typed message → the SAME streaming turn the mic drives, minus the capture:
   * {"type":"text"} on the socket runs LLM → TTS → Audio2Face server-side, so a
   * question from the chat composer is spoken aloud and lip-synced just like a
   * spoken one. (POST /chat stays as the text-only endpoint it always was.)
   */
  const sendText = useCallback(
    async (text: string) => {
      const body = text.trim();
      if (!body) return;

      // Snapshot before the local echo below, so the typed message goes up once —
      // as the turn's question, not also as the last line of its own history.
      const history = historyPayload();

      setError(null);
      // The user typed it, so it goes up immediately — the server does not echo
      // a typed turn's transcript back (see run_reply's echo_transcript).
      setMessages((prev) => [...prev, { id: nextId(), role: "user", text: body }]);
      setPartial("");
      assistantIdRef.current = null;

      // A typed turn interrupts whatever is playing, the way a new question should.
      queueRef.current?.stop();
      try {
        audioElRef.current?.pause();
      } catch {}
      audioElRef.current = null;
      teardownMic();
      try {
        wsRef.current?.close();
      } catch {}

      // Typing is an instruction to go, so it also lifts a hold.
      cancelledRef.current = false;
      pausedRef.current = false;
      setMode("thinking");

      // Sending is a user gesture — the right moment to unlock audio playback,
      // so the reply can start speaking without a click of its own.
      try {
        await ensureAudioContext();
      } catch {
        /* no analyser — the reply still plays, the level meter just stays flat */
      }

      const queue = createQueue();
      queueRef.current = queue;
      const ws = new WebSocket(wsUrl());
      ws.binaryType = "arraybuffer";
      wsRef.current = ws;
      bindReplyStream(ws, queue);
      ws.onopen = () => {
        try {
          ws.send(
            JSON.stringify({
              type: "text",
              text: body,
              lang: langRef.current,
              avatar: avatarRef.current,
              history,
            }),
          );
        } catch {
          setError("chat-failed");
        }
      };
      ws.onerror = () => setError("chat-failed");
    },
    [bindReplyStream, createQueue, ensureAudioContext, historyPayload, teardownMic],
  );

  useEffect(() => () => stop(), [stop]);

  return {
    mode,
    active,
    paused: mode === "paused",
    messages,
    partial,
    error,
    levelRef,
    start,
    stop,
    endAndClear,
    toggle,
    togglePause,
    sendText,
    clearError: () => setError(null),
  };
}
