/**
 * Blendshape playback for Audio2Face lipsync.
 *
 * Ported from the working implementation
 * and adapted to how THIS app delivers speech.
 *
 * The original ran over a single continuous LiveKit audio track, so it anchored
 * one wall clock per turn (`performance.now()` at the agent's `{start:true}`
 * marker) and the backend pre-offset every sentence's frames onto that one
 * timeline. Here the browser instead plays one discrete `<audio>` element per
 * reply sentence, and the backend tags each sentence's audio with a clip id.
 * So each clip keeps its OWN timeline and is sampled against **that element's
 * `currentTime`** — the audio playhead itself is the clock:
 *
 *   - no wall-clock drift, and no per-sentence offsets to compound
 *   - pause/resume and a late-starting `<audio>` stay in sync for free
 *   - frames that arrive after playback began simply join mid-clip
 *
 * Everything downstream of `sample()` (gains, cursor interpolation, the tail
 * hold) is the original logic unchanged.
 *
 *   server → { type:"lipsync", uid, names, frames }   first batch of a clip
 *   server → { type:"lipsync", uid, frames }          continuation batches
 *
 * Module-level singleton: useVoiceSession feeds it, the avatar samples it.
 */

export interface BlendshapeClip {
  uid: string;
  names: string[];
  frames: number[][]; // [clipTimeSeconds, w0, w1, ...] sorted by time
  /** Per-index gain vector, recomputed when calibration changes. */
  gains: Float32Array;
}

/** Seconds into the clip's own audio. */
export type ClipClock = () => number;

const clips = new Map<string, BlendshapeClip>();
/** One pending waitForFrames() resolver per clip — see waitForFrames(). */
const waiters = new Map<string, () => void>();
let active: { uid: string; clock: ClipClock } | null = null;
let cursor = 0;
let weightsOut: Float32Array = new Float32Array(0);

/**
 * Hold after the last known frame before going idle. Short: batched frame
 * delivery can run behind playback, and a long hold reads as a frozen mouth
 * mid-word — better to decay to rest and pick the clip back up when the next
 * batch lands.
 */
const CLIP_TAIL_SECONDS = 0.35;

/** Clips never played (interrupted turn) would otherwise accumulate. */
const MAX_BUFFERED_CLIPS = 12;

// ── Tuning ────────────────────────────────────────────────────────────────
// Per-RIG calibration, not a property of A2F's output: A2F's ARKit weights
// read hot on this rig, so they are trimmed globally and jawOpen further still.
// See setRigCalibration() for how the avatar component installs its own.
const DEFAULT_GAIN = 0.55;
const DEFAULT_SHAPE_GAINS: Record<string, number> = { jawopen: 0.45 };

const params =
  typeof window !== "undefined"
    ? new URLSearchParams(window.location.search)
    : new URLSearchParams();

const killSwitch = params.get("a2f") === "off";
if (killSwitch) console.log("[A2F] disabled via ?a2f=off");

const gainOverride = (() => {
  const p = parseFloat(params.get("a2fGain") ?? "");
  if (Number.isFinite(p) && p > 0 && p <= 2) {
    console.log(`[A2F] weight gain override: ${p}`);
    return p;
  }
  return null;
})();

/**
 * Anchor fine-tune in seconds: positive shifts the animation EARLIER relative
 * to the audio (?a2fOffset=0.15 if the lips consistently trail the voice).
 */
const anchorOffset = (() => {
  const p = parseFloat(params.get("a2fOffset") ?? "");
  if (Number.isFinite(p) && Math.abs(p) <= 2) {
    if (p !== 0) console.log(`[A2F] anchor offset: ${p}s`);
    return p;
  }
  return 0;
})();

const shapeGainOverrides: Record<string, number> = (() => {
  const parsed: Record<string, number> = {};
  const raw = params.get("a2fShapes");
  if (raw) {
    for (const pair of raw.split(",")) {
      const [name, v] = pair.split(":");
      const f = parseFloat(v);
      if (name && Number.isFinite(f) && f >= 0 && f <= 2) parsed[name.toLowerCase()] = f;
    }
    console.log("[A2F] shape gain overrides:", parsed);
  }
  return parsed;
})();

/** Amplitude calibration for the rig currently on screen. */
export interface RigCalibration {
  /** Global multiplier on every A2F weight. */
  gain?: number;
  /** Extra per-shape trims, keyed by lowercased ARKit name, stacking on `gain`. */
  shapeGains?: Record<string, number>;
}

let rigGain = DEFAULT_GAIN;
let rigShapeGains: Record<string, number> = DEFAULT_SHAPE_GAINS;

const gain = () => gainOverride ?? rigGain;
const shapeGains = () => ({ ...rigShapeGains, ...shapeGainOverrides });

/**
 * Install the calibration for the rig being displayed, or null to restore the
 * shared defaults. The avatar component calls this on mount and resets on
 * unmount. A ?a2fGain / ?a2fShapes query override still wins, so live
 * hand-tuning is unaffected by whichever rig is loaded.
 */
export function setRigCalibration(cal: RigCalibration | null): void {
  rigGain = cal?.gain ?? DEFAULT_GAIN;
  rigShapeGains = cal?.shapeGains ?? DEFAULT_SHAPE_GAINS;
  for (const clip of clips.values()) clip.gains = gainsFor(clip.names);
}

/** Per-index gain vector for a clip's shape list. */
function gainsFor(names: string[]): Float32Array {
  const g = gain();
  const trims = shapeGains();
  return Float32Array.from(names.map((n) => g * (trims[n.toLowerCase()] ?? 1)));
}

// ── Console probe: window.__A2F.state — undefined means a stale bundle ─────
const stats = { messages: 0, framesReceived: 0, clips: 0, samples: 0 };
if (typeof window !== "undefined") {
  (window as unknown as Record<string, unknown>).__A2F = {
    get state() {
      const clip = active ? clips.get(active.uid) : null;
      return {
        ...stats,
        buffered: clips.size,
        activeUid: active?.uid ?? null,
        clipFrames: clip?.frames.length ?? 0,
        playbackT: active ? active.clock() : null,
        lastFrameT: clip?.frames.length ? clip.frames[clip.frames.length - 1][0] : null,
        gain: gain(),
        shapeGains: shapeGains(),
        killSwitch,
      };
    },
  };
}

/** Handle one {"type":"lipsync"} message — a clip's first or continuation batch. */
export function handleClipMessage(msg: {
  uid?: string;
  names?: string[];
  frames?: number[][];
}): void {
  if (killSwitch) return;
  stats.messages++;
  const uid = msg.uid ?? "";
  if (!uid || !Array.isArray(msg.frames)) return;

  let clip = clips.get(uid);
  if (!clip) {
    // First batch of a clip carries the 52 ARKit names; a continuation for a
    // clip we already dropped has none and is discarded.
    if (!Array.isArray(msg.names)) return;
    stats.clips++;
    clip = { uid, names: msg.names, frames: [], gains: gainsFor(msg.names) };
    clips.set(uid, clip);
    if (weightsOut.length !== msg.names.length) {
      weightsOut = new Float32Array(msg.names.length);
    }
    // Bound the buffer: a turn that ends before its clips play would leak.
    while (clips.size > MAX_BUFFERED_CLIPS) {
      const oldest = clips.keys().next().value as string | undefined;
      if (oldest === undefined || oldest === active?.uid) break;
      clips.delete(oldest);
    }
    console.log(`[A2F] clip ${uid} armed (${msg.names.length} shapes)`);
  }
  clip.frames.push(...msg.frames);
  stats.framesReceived += msg.frames.length;
  if (clip.frames.length > 0) waiters.get(uid)?.();
}

/** True once this clip has at least one keyframe to play. */
export function hasFrames(uid: string): boolean {
  const clip = clips.get(uid);
  return !!clip && clip.frames.length > 0;
}

/**
 * Resolve when `uid` has frames, or after `timeoutMs` — whichever comes first.
 *
 * This is the playback gate (§10's APP_A2F_PLAYBACK_DELAY, made adaptive). The
 * NIM is clip-in/burst-out, so a clip's first frames land a few hundred ms
 * after its audio is ready — measured ~540ms here for the first sentence of a
 * turn. Starting that audio immediately means the opening syllables play with
 * the mouth at rest, which reads as broken lipsync. Holding playback until the
 * frames exist costs a delay nobody notices and starts the mouth on the first
 * syllable instead.
 *
 * Adaptive rather than a fixed delay: later sentences are already synthesized
 * and A2F'd while the previous one plays, so they resolve immediately and pay
 * nothing. The timeout is the backstop — if A2F is down the audio still plays,
 * just without lipsync.
 */
export function waitForFrames(uid: string, timeoutMs: number): Promise<void> {
  if (killSwitch || hasFrames(uid)) return Promise.resolve();
  return new Promise((resolve) => {
    const done = () => {
      clearTimeout(timer);
      waiters.delete(uid);
      resolve();
    };
    const timer = setTimeout(done, timeoutMs);
    waiters.set(uid, done);
  });
}

/**
 * The `<audio>` element for `uid` started playing — sample this clip against
 * its own playhead from now on. Safe to call before any frames have arrived.
 */
export function beginClip(uid: string, clock: ClipClock): void {
  if (killSwitch) return;
  active = { uid, clock };
  cursor = 0;
  const clip = clips.get(uid);
  if (clip && weightsOut.length !== clip.names.length) {
    weightsOut = new Float32Array(clip.names.length);
  }
}

/** That element finished (or errored) — release the clip. */
export function endClip(uid: string): void {
  waiters.get(uid)?.();
  clips.delete(uid);
  if (active?.uid === uid) {
    active = null;
    cursor = 0;
  }
}

/** Turn ended or was interrupted — clear everything so the face returns to rest. */
export function stop(): void {
  for (const done of waiters.values()) done(); // never leave playback gated
  waiters.clear();
  clips.clear();
  active = null;
  cursor = 0;
}

/** True when ?a2f=off — callers skip A2F application entirely. */
export function isDisabled(): boolean {
  return killSwitch;
}

/** True while a clip is mounted for playback, even before its frames arrive. */
export function isArmed(): boolean {
  return active !== null;
}

/**
 * Sample the active clip at the audio's current position. Returns null when
 * idle / no frames yet / past the tail — the caller decays morphs to rest.
 */
export function sample(): { names: string[]; weights: Float32Array } | null {
  if (killSwitch || !active) return null;
  const clip = clips.get(active.uid);
  if (!clip || clip.frames.length === 0) return null;

  const t = active.clock() + anchorOffset;
  if (!Number.isFinite(t)) return null;
  const frames = clip.frames;
  const last = frames[frames.length - 1];
  if (t > last[0] + CLIP_TAIL_SECONDS) return null;
  stats.samples++;

  // Advance the cursor to the frame pair straddling t (amortized O(1);
  // resets if the playhead ever jumps backwards, e.g. on a replay).
  while (cursor < frames.length - 1 && frames[cursor + 1][0] <= t) cursor++;
  if (cursor > 0 && frames[cursor][0] > t) cursor = 0;

  const a = frames[cursor];
  const b = frames[Math.min(cursor + 1, frames.length - 1)];
  const span = b[0] - a[0];
  const alpha = span > 0 ? Math.min(Math.max((t - a[0]) / span, 0), 1) : 0;

  for (let i = 0; i < clip.names.length; i++) {
    const va = a[i + 1] ?? 0;
    const vb = b[i + 1] ?? 0;
    weightsOut[i] = (va + (vb - va) * alpha) * clip.gains[i];
  }
  return { names: clip.names, weights: weightsOut };
}
