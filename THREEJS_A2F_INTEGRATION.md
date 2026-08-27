# Three.js + GLB + NVIDIA Audio2Face Integration — Technical Handoff

Scope: this document covers **only** the `girl11.glb` avatar pipeline (the Urdu avatar, rendered by `AvatarModelUrdu.tsx`). This repo has other avatar variants (`AvatarModelMale.tsx`, `AvatarModelFemale.tsx`) that use a mapping layer and a viseme fallback — those are **not** documented here because the model this doc targets uses neither. Where shared infrastructure (scene setup, transport, backend A2F client) is used by all avatars, it is documented as-is since `girl11.glb` depends on it too.

---

## 1. Overview

```
TTS audio (per sentence, from the LiveKit agent)
    ↓
agent/plugins/a2f_client.py  --gRPC-->  NVIDIA Audio2Face-3D NIM
    (audio in, 52 ARKit blendshape names + timestamped weight frames out)
    ↓
agent/main.py (tts_node) publishes LiveKit text-stream messages, topic "lipsync.frames"
    ↓
frontend LiveKitConversationContext.tsx registers a stream handler for that topic
    ↓
frontend/src/lib/blendshapePlayer.ts — buffers frames, anchors wall clock, interpolates
    ↓
frontend/src/lib/a2fMorphs.ts — applyA2FLipsync() writes directly into
    mesh.morphTargetInfluences on girl11.glb's SkinnedMeshes (no name-mapping layer:
    girl11.glb's morph target names already match ARKit blendshape names 1:1)
    ↓
frontend/src/components/avatar/AvatarModelUrdu.tsx — R3F component, calls
    applyA2FLipsync() every frame inside useFrame(), and separately drives
    body animation (breathing/listening/talking) via a hand-rolled 3-layer
    AnimationAction crossfade over one baked clip.
```

`girl11.glb` is unique among this repo's avatars in that it needs **no** ARKit→rig mapping table and has **no** viseme (audio-amplitude) fallback wired in — its component only accepts `url` / `conversationState` / `onReady` as props, not `currentViseme` / `isSpeaking`. This is a deliberate simplification specific to this rig, not a general pattern.

---

## 2. Files involved

```
File: frontend/src/components/avatar/AvatarModelUrdu.tsx
Purpose: R3F component — loads girl11.glb, drives body animation state machine,
         drives blink, calls into a2fMorphs.ts for facial lipsync each frame.
Key exports: default AvatarModelUrdu({ url, conversationState, onReady })
Depends on: three, @react-three/fiber, frontend/src/lib/a2fMorphs.ts,
            frontend/src/lib/blendshapePlayer.ts (indirectly, via setRigCalibration)
Depended on by: frontend/src/components/avatar/AvatarScene.tsx (routes to it when
                speechLanguage === "ur")

File: frontend/src/lib/a2fMorphs.ts
Purpose: applies sampled A2F blendshape weights onto a GLB's morph targets,
         with smoothing and anti-conflict clamping. Shared by all avatar
         components, but for girl11.glb it runs in "direct" mode (exact name
         match) rather than "mapped" mode.
Key exports: resolve(names, mesh), applyA2FLipsync(state, morphMeshes, delta)
Depends on: frontend/src/lib/blendshapePlayer.ts (sample())
Depended on by: AvatarModelUrdu.tsx (and the other AvatarModel*.tsx files)

File: frontend/src/lib/blendshapePlayer.ts
Purpose: module-level singleton. Receives raw "lipsync.frames" messages,
         buffers a turn's keyframe timeline, anchors a wall-clock start,
         applies calibration gain, and exposes sample() for per-frame
         interpolation.
Key exports: handleClipMessage(msg), sample(), setRigCalibration(cfg)
Depends on: nothing (pure timing/interpolation logic)
Depended on by: LiveKitConversationContext.tsx (feeds it), a2fMorphs.ts (reads it)

File: frontend/src/context/LiveKitConversationContext.tsx
Purpose: LiveKit room connection/lifecycle. Registers a text-stream handler
         on topic "lipsync.frames" that forwards parsed JSON into
         blendshapePlayer.handleClipMessage().
Key relevant code: room.registerTextStreamHandler("lipsync.frames", ...)
Depends on: livekit-client
Depended on by: frontend/src/app/page.tsx (provider), blendshapePlayer.ts (fed by it)

File: frontend/src/components/avatar/AvatarScene.tsx
Purpose: R3F <Canvas> scene (camera, lighting, background effects) and
         avatar routing. Routes to AvatarModelUrdu when speechLanguage === "ur".
Depends on: @react-three/fiber, @react-three/drei, AvatarModelUrdu.tsx
Depended on by: frontend/src/app/page.tsx

File: frontend/src/app/page.tsx
Purpose: top-level page. Selects avatar GLB path by language, passes it and
         conversation state down to AvatarScene.
Key relevant code: URDU_AVATAR_PATH = "/models/girl11.glb"

File: agent/plugins/a2f_client.py
Purpose: backend gRPC client to the NVIDIA Audio2Face-3D NIM. Streams 16kHz
         PCM audio in, receives timestamped ARKit blendshape frames out.
Key exports: A2FClient, A2FStreamSession
Depends on: vendored nvidia_ace proto package (agent/vendor/), grpc
Depended on by: agent/main.py

File: agent/main.py
Purpose: LiveKit agent entrypoint. Custom tts_node cuts one A2F "clip" per
         TTS sentence, feeds audio into A2FStreamSession, and publishes the
         returned frames to the frontend over LiveKit text streams
         (topic "lipsync.frames").
Key relevant code: _make_lipsync_publisher(), tts_node(), turn "start" marker publish
Depends on: agent/plugins/a2f_client.py, livekit-agents
```

---

## 3. Three.js / GLB setup (shared scene, used by girl11.glb too)

`AvatarScene.tsx` sets up the `<Canvas>`:

```ts
<Canvas
  camera={{ position: [0, 1.5, 2.5], fov: 28 }}
  gl={{ antialias: true, toneMapping: 4 /* ACESFilmicToneMapping */ }}
>
```

No explicit near/far — defaults to `near=0.1`, `far=1000` (R3F's `PerspectiveCamera` default).

Camera look-at and idle sway:

```ts
function CameraSetup() {
  const { camera } = useThree();
  useEffect(() => { camera.lookAt(0, 1.3, 0); }, [camera]);
  useFrame((state) => {
    const t = state.clock.elapsedTime;
    camera.position.x = Math.sin(t * 0.08) * 0.05;
    camera.lookAt(0, 1.3, 0);
  });
  return null;
}
```

Lighting/background: `<color background="#0a0a14">`, fog `["#0a0a14", 4, 10]`, a face-fill spotlight (`position=[0,2.2,1]`, `angle=0.18`, `penumbra=0.6`, `intensity=2.4`, `distance=1.6`, `decay=2`, `color="#fff2e0"`), an `Environment` with `Lightformer`s, and `ContactShadows` (`position=[0,-0.01,0]`, `opacity=0.5`, `scale=4`, `blur=2.5`). These are cosmetic and not required to reproduce lip-sync, but they are tuned around this camera framing.

**GLB placement for girl11.glb specifically** (`AvatarModelUrdu.tsx`):

```ts
const URDU_AVATAR_POSITION_X = 0.08;
const URDU_AVATAR_POSITION_Y = 0.09;
// per frame:
groupRef.current.position.x = URDU_AVATAR_POSITION_X;
groupRef.current.position.y = URDU_AVATAR_POSITION_Y + Math.sin(state.clock.elapsedTime * 0.8) * 0.003;
```

The Y offset exists because `girl11.glb` is ~1.68m tall versus the ~1.78m the camera framing (`position.y=1.5`, `lookAt` y=1.3) was originally tuned for — it's a manual compensation, not derived from the model's bounding box. If you swap in a differently-scaled model, this constant needs re-tuning by eye.

GLB loading itself uses the standard R3F/drei `useGLTF(url)` pattern (via `useLoader`/`useGLTF`, model traversal to collect `SkinnedMesh` nodes with morph targets). No unusual GLTFLoader configuration was found beyond standard drei usage.

---

## 4. GLB structure — girl11.glb

- Single glTF mesh named `"base"` with **12 primitives**: head, brows, eyes, upper teeth, lower teeth, tongue, eyelashes, skin, nails (and others). Because glTF primitives become separate three.js objects on import, this yields **12 `SkinnedMesh` instances**, and every one of them carries the full set of morph targets (not just the head/face primitives).
- **51 morph targets total** on the rig. A2F emits **52 ARKit blendshape names**; **50 of the 52 match by exact (case-insensitive) name** against `mesh.morphTargetDictionary`.
- Two ARKit shapes are **not** driven:
  - `tongueOut` — no corresponding morph target exists on this rig at all.
  - `cheekSquintRight` — the rig's morph target is misspelled as `heekSquintRight` (missing the leading `c`). This is a known rig typo, left unaliased on purpose (not fixed in code) per the working notes.
- Because names match directly, `a2fMorphs.ts`'s `resolve()` takes the **direct path** (case-insensitive exact match against `mesh.morphTargetDictionary`, applied at scale 1) for this rig — it never falls through to the `ARKIT_TO_METAHUMAN` mapping table used by the other avatar rigs in this repo. No A2F-coefficient-to-morph-target renaming/remapping exists for girl11.glb; the correspondence is name-identity.
- Bones vs. morph targets: the rig uses **both** — it's a `SkinnedMesh` (bone-skinned body) that additionally carries morph targets for the face. Body animation drives bones via a baked `AnimationClip`; facial lipsync drives morph targets directly, bypassing the animation system entirely (no `AnimationMixer` involvement for the face).
- Animation clip: a single baked clip named `"CINEMA_4D_Main"`, 801 frames at 30fps (~26.7s total), containing multiple hand-authored segments (breathing/listening/talking) concatenated in one timeline — see §5.

---

## 5. Character animation (girl11.glb)

Body animation comes from one clip, `"CINEMA_4D_Main"` (801 frames @ 30fps), sliced into named segments by frame range:

```ts
const FPS = 30;
const CLIP_NAME = "CINEMA_4D_Main";
const SEGMENTS: Record<BodyState, Segment> = {
  breathing: { intro: null,              after: null,        loop: [0/FPS, 240/FPS] },
  listening: { intro: [240/FPS, 300/FPS], after: "breathing", loop: [300/FPS, 392/FPS] },
  talking:   { intro: [392/FPS, 434/FPS], after: "listening", loop: [434/FPS, 716/FPS] },
};
const LOOP_XFADE_SECS = 0.35;
const SWITCH_XFADE_SECS = 0.55;
const TALK_EXIT_DEBOUNCE_MS = 250;
```

State selection from conversation state:

```ts
// bodyStateFor(conversationState):
// speaking  -> "talking"
// listening | thinking -> "listening"
// else -> "breathing"
```

There are exactly three body states, each with an optional one-shot `intro` segment played once before settling into its `loop` segment; `talking`'s `after` falls back to `listening` and `listening`'s falls back to `breathing` when a segment ends without a new state having been requested.

**This is not a plain `AnimationMixer.play()`/crossFadeTo() setup.** It's a hand-rolled 3-layer crossfade pool (`LAYER_COUNT = 3`):
- All 3 `AnimationAction`s from the single clip are created with `paused = true` and are **never allowed to auto-advance** — `action.time` and `action.weight` are written manually every `useFrame` tick.
- `beginSegment()` picks a free (or least-weighted) layer and fades it in while every other layer fades to 0, over `LOOP_XFADE_SECS` (loop-to-loop) or `SWITCH_XFADE_SECS` (state switch).
- `advanceLayer()` plays a layer's `intro` range once (if present) then clamps playback inside its `loop` range — no timeline wraparound; the crossfade pool itself covers the loop seam by starting a new layer before the old one finishes.
- Why 3 layers instead of the more typical 2: a comment in the code states that with only 2 layers, an interrupted crossfade (state changing again mid-fade) produces a visible pose "snap" — measured worst-case per-frame pose jump of 0.083 with 2 layers versus 0.0117 with 3 layers (natural clip motion peaks at ~0.0070 for reference). If you reproduce this pattern with a different rig, keep 3 layers if state changes can interrupt an in-progress crossfade.
- `TALK_EXIT_DEBOUNCE_MS = 250` — leaving the `talking` state requires 250ms of the trigger condition holding, to avoid state churn from brief `isSpeaking` flicker.

This state machine is triggered purely by `conversationState` (prop passed down from `page.tsx` / the LiveKit context), not by any Audio2Face signal — body animation and facial lipsync are fully independent per-frame writes.

Facial animation (morph targets) is **not** part of this clip and is **not** driven by `AnimationMixer` at all — see §6–§9.

**Blink** is separate, procedural, and independent of both the body clip and A2F (A2F's own eye-blink channels are near-silent during normal speech so are not relied on):

```ts
blink.nextBlink -= delta;
if (blink.nextBlink <= 0) {
  blink.blinkProgress = 1;
  blink.nextBlink = 2 + Math.random() * 4;   // next blink in 2-6s
}
if (blink.blinkProgress > 0) blink.blinkProgress = Math.max(0, blink.blinkProgress - delta * 8);
const blinkValue = blink.blinkProgress > 0.5
  ? (1 - blink.blinkProgress) * 2
  : blink.blinkProgress * 2;
```

Blink target indices are resolved with a fallback chain: `dict["eyeBlinkLeft"] ?? dict["eyeBlink_L"] ?? dict["Eye_Blink_L"]` (and the `Right` equivalents) — on girl11.glb this resolves via the first (ARKit-native) name.

---

## 6. Audio2Face integration (backend)

**Protocol**: gRPC (not WebSocket/HTTP/REST). Client implementation: `agent/plugins/a2f_client.py`. This talks to an **NVIDIA Audio2Face-3D NIM** container (`nvcr.io/nim/nvidia/audio2face-3d`), run as a local Docker service.

**Connection**: `APP_A2F_URL` env var, one of:
- `host:port` or `grpc://host:port` — plaintext.
- `grpcs://host[:port]` — TLS, defaults to port 443, paired with `APP_A2F_API_KEY` sent as `authorization: Bearer <key>` gRPC metadata, and optional `APP_A2F_TLS_CA` for a custom CA file.

Channel options:
```python
options = [
  ("grpc.keepalive_time_ms", 30000),
  ("grpc.keepalive_timeout_ms", 10000),
  ("grpc.keepalive_permit_without_calls", 1),
]
```

`A2FClient` holds one **shared, persistent channel** for the agent's lifetime (`warmup()` dials it eagerly at session start with a 15s timeout). Each utterance opens a new `A2FStreamSession` (a `ProcessAudioStream` gRPC call) on that shared channel via `open_stream(sample_rate, on_batch)`. On any failure the channel is closed and nulled so the *next* call re-dials fresh rather than reusing a poisoned connection — a single utterance's failure doesn't kill the whole session.

**Request contract is "clip-in / burst-out"**: the NIM does not stream frames back continuously as audio arrives — it buffers the whole audio clip and returns blendshape frames as a burst once (or as) it finishes processing. This single fact drives most of the latency-management code in both `a2f_client.py` and `main.py` (see §7 and §10).

**Sent per utterance**: 16-bit PCM audio at 16kHz, chunked (see §7), followed by an `end_of_audio` marker.

**Received per utterance**:
1. One `animation_data_stream_header` message containing `header.skel_animation_header.blend_shapes` — the ordered list of **52 ARKit blendshape names** this stream will emit weights for. On receipt, the client immediately flushes an empty-frames batch carrying just these names to the frontend (this "arms" the frontend clip before real weight data arrives).
2. A series of `animation_data` messages, each containing a timestamped weight frame: `[round(max(t, 0), 3), *(round(v, 3) for v in bs.values)]`.
3. A `status` message; `status.code == 3` is treated as an error and raises `RuntimeError`.

Batching to the frontend: the client does not forward every single NIM frame in its own message — it batches:
```python
_BATCH_FRAMES = 3          # subsequent batches: ~100ms of frames at NIM's 30fps output
_FIRST_BATCH_FRAMES = 1    # first real frame ships alone, for lowest time-to-first-frame
```

**Session lifecycle**:
- `finish()` — flushes the outbound queue, sends `AudioStream(end_of_audio=...)`, awaits the read task to drain, returns total frame count. The gRPC channel itself stays open for the next utterance (only the stream call ends).
- `abort()` — cancels the priming/writer/read tasks and cancels the gRPC stream call; used on user interruption. Channel stays alive.

**Error/reconnection handling**: `open_stream()` failures close+null the shared channel so subsequent calls redial; a 4.0s hard timeout wraps `open_stream()` in `main.py` (so an unreachable NIM costs the frontend a missed lipsync clip, not a multi-second UI stall) and a 15.0s timeout wraps `session.finish()`.

---

## 7. Audio pipeline into Audio2Face

```
TTS engine output (agent's existing TTS plugin — ElevenLabs/other, produces PCM at
its own native sample rate)
    ↓
agent/main.py tts_node() intercepts the synthesized audio frames as they arrive
    ↓
_resample_to_16k(): linear-interpolation resample (numpy.interp) from TTS's native
    rate to A2F_SAMPLE_RATE = 16000 Hz, int16 PCM. Explicitly documented as "adequate
    for lipsync" — not a proper sinc/polyphase resampler; do not assume broadcast-
    quality resampling if reproducing this.
    ↓
A2FStreamSession.write(): audio bytes go onto an internal asyncio queue
    ↓
_paced_writer(): drains the queue and ships ~1 second chunks per gRPC write message
    (_WRITE_CHUNK_SAMPLES = A2F_SAMPLE_RATE, i.e. 16000 samples = 1s @ 16kHz).
    Explicit rationale in the code: writing once per ~10ms TTS frame instead
    (one gRPC message per tiny frame) drowned the event loop and made
    time-to-first-frame scale with reply length; coalescing into ~1s chunks
    cut the number of writes by roughly 100x. The NIM also rejects buffers
    longer than ~10s per write, which is why chunks are capped at 1s (not
    sent as one giant blob).
    ↓
Silence priming (start_priming / _prime_loop): BEFORE real audio is available,
    100ms chunks of 16-bit silence (b"\x00\x00" * (16000 // 10)) are sent every
    100ms. Rationale: the NIM needs roughly 2-3 seconds of audio context before
    producing its first frame on a freshly opened stream, so priming keeps the
    stream "warm" and avoids a cold-start latency spike when real audio starts.
    The cumulative silence duration is tracked and later subtracted from every
    returned frame timestamp, and any frame with t < -0.05 (pure silence-era
    noise) is dropped — so the timeline the frontend sees is speech-relative,
    not stream-relative.
    ↓
gRPC ProcessAudioStream → NVIDIA Audio2Face-3D NIM
```

**Sync with what the user hears**: the raw TTS audio is played to the user via the normal LiveKit audio track (unrelated to this pipeline) while, in parallel, the same audio is resampled and streamed into A2F. `APP_A2F_PLAYBACK_DELAY` (default `0.0`) can hold TTS playback by a fixed window per turn so A2F has a head start — see §10 for how this interacts with clip cutting and frame timing.

---

## 8. Audio2Face facial data (what comes back)

- **Format**: 52 named ARKit blendshape channels, each frame a `[timestamp, weight_0, weight_1, ..., weight_51]` array (rounded to 3 decimal places on both the timestamp and each weight in `a2f_client.py`).
- **Frame rate**: NIM outputs at 30fps; the client batches every 3 frames (~100ms) into one message to the frontend after the first frame (sent alone for lowest latency).
- **Naming/indexing**: names arrive once via the stream header (`skel_animation_header.blend_shapes`) and are reused positionally for every subsequent frame array in that clip — index `i+1` in a frame array corresponds to `names[i]`.
- **Normalization**: values are used as-is (0..1-ish ARKit weight range) with no server-side scaling; clamping and gain happen client-side (§9, §11).
- **Timing**: timestamps are turn/clip-relative, adjusted by `main.py`'s `_make_lipsync_publisher` with a per-clip `offset` (cumulative duration of prior sentences in the same turn) before being sent to the frontend, so the frontend only needs one wall-clock anchor per turn (the `{start: true}` marker), not per sentence.
- **Preprocessing before it leaves the backend**: silence-priming offset subtraction and negative-timestamp frame dropping (§7); per-clip trailing-silence trim in `_make_lipsync_publisher` (frames beyond `clip_end + 0.05s` are dropped, since the NIM appends ~1.5s of trailing silence frames after real speech ends).

---

## 9. Audio2Face → GLB morph-target application (girl11.glb specifically)

Because girl11.glb's 51 morph target names already match A2F's ARKit blendshape names (case-insensitively, for 50 of 52), **there is no coefficient remapping table in play for this model** — `a2fMorphs.ts`'s `resolve()` takes its direct-match branch:

```ts
// resolve(): for each ARKit name, case-insensitive exact match against
// mesh.morphTargetDictionary -> drive that single morph index at scale 1.
// (Only falls back to the ARKIT_TO_METAHUMAN table, used by other avatars
// in this repo, when no direct match exists — girl11.glb's rig doesn't
// need this fallback except for the 2 unmatched names noted in §4.)
```

Per-mesh resolution is logged: `` `[A2F] resolved ${names.length} blendshapes → ${mesh.name}: ${direct} direct + ${mapped} mapped` `` — for girl11.glb expect `direct` ≈ 50, `mapped` = 0 (across all 12 SkinnedMesh primitives that share the morph target set).

**Application, every frame** (`applyA2FLipsync(state, morphMeshes, delta)`, called from `AvatarModelUrdu.tsx`'s `useFrame` at render priority `-1`, i.e. before default-priority callbacks):

1. Pull the current interpolated weights from `blendshapePlayer.sample()` (see §10 for interpolation details).
2. Apply calibration gain (see below) per-name.
3. Accumulate weights per resolved morph index (`accum[idx]`), since multiple ARKit names could in principle target the same index.
4. Apply anti-conflict downscaling (jaw-open vs. lip-closure, lip-round vs. lip-spread) — see constants below. Note: these constraint sets key on lowercase *coarse-viseme* target names (`mouth_open`, `bb`, `o`, `oo`, etc.), which are the vocabulary used by the *other* avatars' mapped rigs. girl11.glb's morph names are ARKit names (`jawOpen`, `mouthClose`, etc.), so **these anti-conflict constraints do not engage for this model** — worth knowing if lip/jaw interpenetration needs tuning here, since fixing it means adjusting the calibration gains below or adding new ARKit-keyed constraint entries, not adjusting the existing ones.
5. Smooth toward the target value (per-morph follow filter, see §11) and clamp to `[0, 1]`, scaled by `state.mix` (crossfade weight against the viseme fallback — always `1.0` in practice for this model since it has no viseme fallback wired in).
6. Write into `mesh.morphTargetInfluences[idx]` on each of the 12 `SkinnedMesh` primitives directly — no intermediate object, no `AnimationMixer` track.

**Calibration for girl11.glb**, set once on mount via `setRigCalibration()`:

```ts
const A2F_GAIN = 0.55;
const A2F_SHAPE_GAINS: Record<string, number> = { jawopen: 0.3 };
// effective jawOpen multiplier = 0.55 * 0.3 = 0.165
useEffect(() => {
  setRigCalibration({ gain: A2F_GAIN, shapeGains: A2F_SHAPE_GAINS });
  return () => setRigCalibration(null);
}, []);
```

These are empirically tuned, not derived from a formula. Per the repo's working notes (`improve-lip-sync.md`), earlier attempts at higher jaw gain were rejected by human review as "exaggerated" / "still opening too much" before settling on `0.3`. If you reproduce this pipeline against a different rig, expect to re-tune `jawopen`'s shape gain by eye — start near this range rather than at 1.0.

Runtime overrides via URL query string (`blendshapePlayer.ts`), useful for live tuning without redeploying:
```
?a2f=off                                   disable A2F entirely
?a2fGain=0.5                               global weight multiplier, 0 < g <= 2
?a2fShapes=jawopen:0.2,mouthpucker:0.8     per-shape multiplier overrides
?a2fOffset=0.15                            shift facial animation earlier/later vs audio, |offset| <= 2s
```

---

## 10. Lip-sync timing

- **Clock anchor**: the agent publishes `{ uid, start: true }` on `lipsync.frames` when it enters the speaking state for a turn. `blendshapePlayer.ts` records `t0Ms = performance.now()` at that moment. All subsequent frame timestamps for that turn are relative to this single anchor — one anchor covers the whole (possibly multi-sentence) reply, so per-sentence network jitter doesn't compound.
- **Clip cutting**: the backend does not wait for the whole reply's TTS to finish before talking to A2F. `main.py`'s `tts_node` cuts one A2F "clip" per detected TTS sentence (gap-based sentence boundary detection):
  ```python
  GAP_CUT_S = 0.35        # pause in audio arrival that ends a clip
  MIN_CLIP_S = 0.5        # minimum clip length, avoids cutting on jitter
  MAX_CLIP_S = 12.0       # hard cap for very long run-on sentences
  MAX_FIRST_CLIP_S = 3.0  # first clip capped tighter so its round-trip beats the playback-delay gate
  slots = asyncio.Semaphore(2)  # NIM serves ~3 concurrent streams; 2 used, 1 held as headroom
  ```
  Because the NIM is clip-in/burst-out (§6), cutting per-sentence lets sentence N's frames burst back to the frontend while sentence N+1 is still being synthesized/streamed to A2F, rather than waiting for the entire reply.
- **Per-clip offset**: each clip's frame timestamps are shifted by the cumulative audio duration of prior sentences in the turn (`_make_lipsync_publisher`'s `offset` param) before publishing, so they land correctly on the single turn-relative timeline the frontend anchors once.
- **Ordering guarantee**: `_make_lipsync_publisher`'s `publish()` awaits an `after` future (the previous clip's completion) before sending its own first batch — this keeps clips arriving at the frontend in speech order even if A2F processes them out of order or at different speeds.
- **Playback delay gate**: `APP_A2F_PLAYBACK_DELAY` (env var, default `0.0`) optionally holds actual TTS audio playback by a fixed window at the start of a turn, giving A2F a head start so its first blendshape batch is more likely to have already arrived by the time audio starts. At `0.0`, audio starts immediately and A2F frames mix in over roughly 200ms as they arrive — visually this is covered by falling back to whatever facial pose was already active (idle/neutral) until then, since girl11.glb has no viseme fallback to fill the gap.
- **Consumption on the frontend**: `applyA2FLipsync()` runs inside `useFrame` (i.e. driven by `requestAnimationFrame` via R3F's render loop), calling `blendshapePlayer.sample()` every frame. `sample()` computes `t = (performance.now() - t0Ms) / 1000 + anchorOffset` and finds the straddling keyframe pair via an amortized-O(1) advancing cursor (not a full search each frame), then linearly interpolates between them:
  ```ts
  while (cursor < frames.length - 1 && frames[cursor + 1][0] <= t) cursor++;
  const a = frames[cursor], b = frames[Math.min(cursor + 1, frames.length - 1)];
  const alpha = span > 0 ? clamp((t - a[0]) / span, 0, 1) : 0;
  weight = va + (vb - va) * alpha;
  ```
  Past the last frame, playback holds for `CLIP_TAIL_SECONDS = 0.35` before `sample()` starts returning `null` (facial weights then decay to neutral — see §11).
- **Trailing silence trim**: the NIM appends ~1.5s of near-neutral frames after real speech in each clip; `_make_lipsync_publisher` trims frames beyond `clip_end + 0.05s` before publishing, so the frontend doesn't hold a stale "mouth barely moving" pose for an extra 1.5s per sentence.

---

## 11. Smoothing / interpolation

Two independent smoothing stages, both in `a2fMorphs.ts`:

1. **Keyframe interpolation** (in `blendshapePlayer.sample()`, §10) — plain linear interpolation between the two straddling frames of the received timeline. This is *not* per-frame render smoothing; it's resampling the ~10fps-batched, 30fps-source A2F data up to render frame rate.

2. **Render-rate follow filter** (in `applyA2FLipsync`) — an exponential approach toward the sampled target, applied per morph target every render frame:
   ```ts
   const baseAlpha = delta * 20;                       // ~50ms time constant
   const alpha = Math.min(1, baseAlpha * responseMul[targetName]);
   influences[idx] += (target - influences[idx]) * alpha;
   ```
   `responseMul` comes from `RESPONSE_CAP_BY_TARGET` (a per-morph-name response cap — keyed on coarse-viseme names used by the *other* avatars' mapped rigs, so for girl11.glb this multiplier is effectively always the implicit default since none of its ARKit-named morphs match those keys).

3. **Decay when no frames cover the clock** (clip ended, or gap in data): morph influences lerp toward 0 rather than snapping:
   ```ts
   influences[idx] = THREE.MathUtils.lerp(influences[idx], 0, delta * 10);
   ```

4. **A2F↔fallback blend ramp**: `state.mix += (target - state.mix) * Math.min(1, delta * 8)` (~125ms time constant) — this exists to crossfade against the viseme fallback used by other avatars; for girl11.glb `state.mix` effectively just ramps to/from `1` as A2F data becomes available/unavailable, since there's no competing viseme signal to blend against.

5. **Clamping**: final per-morph value is `Math.min(Math.max(accum[idx], 0), 1) * state.mix` — clamped to `[0,1]` before being written to `morphTargetInfluences`.

There is **no smoothing applied on the backend** — the frame data sent to the frontend is A2F's raw output (rounded to 3 decimals), aside from the timestamp offset/trim adjustments in §7/§10. All temporal smoothing happens client-side.

---

## 12. Frontend ↔ backend communication (avatar/lipsync-relevant only)

```
Browser (Next.js/React, runs in-browser)
    ↓ LiveKit room connection (WebRTC, via livekit-client)
LiveKit server / SFU
    ↑↓
Agent process (Python, runs on backend host — agent/main.py, a LiveKit agent worker)
    ↓ gRPC
NVIDIA Audio2Face-3D NIM (Docker container, local/co-located service)
```

- **Transport for blendshape frames**: not a raw WebSocket and not LiveKit's binary data-channel API — it's LiveKit's **text stream** primitive: agent side calls `room.local_participant.send_text(json_string, topic="lipsync.frames")`; frontend calls `room.registerTextStreamHandler("lipsync.frames", handler)`, where `handler` receives a `reader` and calls `reader.readAll()` to get the reassembled text. LiveKit's SDK handles chunking/reassembly automatically — application code just sees complete JSON strings in, complete JSON strings out.
- **Message shapes** (JSON, `separators=(",", ":")` on the Python side for compactness):
  ```json
  { "uid": "<turn-id>", "start": true }
  { "uid": "<turn-id>", "names": ["eyeBlinkLeft", "jawOpen", ...52 names], "frames": [[0.0, 0.0, 0.12, ...], ...] }
  { "uid": "<turn-id>", "frames": [[0.331, 0.0, 0.18, ...], ...] }
  ```
  First batch of a clip includes `names`; continuation batches for the same clip omit it and are appended to the existing name-indexed timeline.
- **What's browser-side vs. backend-side**: everything in §2's frontend files (Three.js rendering, morph application, keyframe interpolation, calibration) runs in the browser. Everything in §2's backend files (gRPC to A2F, audio resampling/chunking, clip cutting, silence priming) runs in the Python agent process. The only network hop relevant to this pipeline that crosses that boundary is the LiveKit text-stream message above — there is no separate REST/WebSocket endpoint specifically for lipsync data.

---

## 13. Dependencies

**Frontend** (`frontend/package.json`, relevant subset):
```json
"@react-three/drei": "^10.7.7",
"@react-three/fiber": "^9.5.0",
"three": "^0.183.1",
"livekit-client": "^2.17.2",
"@livekit/components-react": "^2.9.20",
"react": "19.2.3",
"react-dom": "19.2.3"
```
- `three` / `@react-three/fiber` / `@react-three/drei` — scene setup, GLB loading (`useGLTF`), render loop (`useFrame`).
- `livekit-client` / `@livekit/components-react` — WebRTC room connection and the text-stream API used to receive `lipsync.frames`.
- (`wawa-lipsync` is a dependency used by *other* avatars' viseme fallback — not required for girl11.glb, which has no viseme fallback wired in.)

**Backend** (Python agent):
- `livekit-agents` — agent framework, `tts_node` override point, `room.local_participant.send_text`.
- `grpc` (Python gRPC) — transport to the A2F NIM.
- A vendored `nvidia_ace` proto package (under `agent/vendor/`) — generates the A2F gRPC service stubs/messages (`AudioStream`, `animation_data_stream_header`, etc.). Import is guarded (`try/except ImportError`) so a missing wheel degrades gracefully to no-A2F rather than crashing the agent.
- `numpy` — used for linear-interpolation resampling to 16kHz.

**Non-NPM / external requirements**:
- **NVIDIA Audio2Face-3D NIM** — a Docker container (`nvcr.io/nim/nvidia/audio2face-3d`) that must be running and reachable from the agent process. Requires an NVIDIA GPU.
- **GPU VRAM budget is a real constraint**: the model alone was observed resident at ~4.65GB on a 6GB laptop GPU (RTX 4050) in this deployment — OOM on the NIM container silently kills lip-sync (frames simply stop arriving) and presents to a developer as if it were a frontend bug. If reproducing this locally, verify GPU headroom before debugging the frontend.
- **LiveKit server** — required regardless of A2F, for the WebRTC session and text-stream transport.
- Docker/Compose for running the NIM (this repo has `deploy/a2f/docker-compose.local.yml` for local A2F).

---

## 14. Configuration

Environment variables (names only):

**Audio2Face (agent side, `agent/main.py` / `agent/plugins/a2f_client.py`):**
```
APP_A2F_URL              # grpc://host:port, grpcs://host[:port], or host:port
APP_A2F_API_KEY          # bearer token, only used with grpcs://
APP_A2F_TLS_CA           # optional custom CA file path, only used with grpcs://
APP_A2F_PLAYBACK_DELAY   # seconds; default 0.0 — see §10
```

**A2F NIM's own deploy config** (`deploy/a2f/.env.example` — distinct from the `APP_A2F_*` vars above, which configure the *agent's client*, not the NIM itself):
```
NGC_API_KEY
A2F_DOMAIN
A2F_API_KEY
```

**LiveKit (required for the whole pipeline, not A2F-specific):**
```
LIVEKIT_URL
LIVEKIT_API_KEY
LIVEKIT_API_SECRET
APP_LIVEKIT_URL
APP_LIVEKIT_PUBLIC_URL
NEXT_PUBLIC_LIVEKIT_URL
LIVEKIT_NODE_IP          # must be the host's real LAN IP or WebRTC media never connects
```

**Model path** (frontend, hardcoded in `page.tsx`, not an env var):
```
URDU_AVATAR_PATH = "/models/girl11.glb"
```

**Runtime debug/tuning overrides** (URL query string, no env var, browser-only — see §9):
```
?a2f=off
?a2fGain=<float>
?a2fShapes=<name>:<mult>,<name>:<mult>,...
?a2fOffset=<seconds>
```

---

## 15. Important implementation details / gotchas

1. **The NIM is clip-in/burst-out, not a continuous stream.** Do not design a new integration assuming frames trickle back continuously as audio is sent — the client must send enough audio (or `end_of_audio`) before meaningful frames return. This is why the backend does per-sentence clip cutting and silence priming rather than one clip per whole reply.
2. **Silence priming is required to avoid cold-start latency.** Without ~100ms silence chunks sent every 100ms before real audio, the first genuine A2F response can take 2-3s. If you drop this when reproducing, expect a visible startup delay on the very first utterance of a session.
3. **Batch gRPC writes.** Sending one gRPC write per small TTS audio frame (~10ms) measurably degrades time-to-first-frame as reply length grows — coalesce into ~1s chunks. The NIM also rejects buffers over ~10s per write, so don't over-coalesce either.
4. **girl11.glb needs no coefficient mapping — but verify morph target names match before assuming this generalizes.** This rig's 1:1 name correspondence with ARKit blendshapes is what makes its integration this simple. A different GLB (even a similarly "ARKit-compatible" one) may need the mapping-table approach used by this repo's other avatar components (`arkitToMetahuman.ts` + `a2fMorphs.ts`'s mapped-path) if names don't match exactly.
5. **`morphTargetDictionary` lookups must be case-insensitive** — the resolve step here explicitly does case-insensitive matching, since ARKit naming conventions and GLB export tooling aren't always consistent about casing.
6. **girl11.glb has two known unresolvable morph names**: `tongueOut` (no matching morph exists) and `cheekSquintRight` (rig has a typo, `heekSquintRight`). Don't spend time debugging why these two channels don't animate — it's a known, accepted rig limitation, not a mapping bug.
7. **The anti-conflict constraint system in `a2fMorphs.ts` (jaw-open vs. lip-closure, lip-round vs. lip-spread) does not engage for girl11.glb**, because it keys on coarse-viseme target names (`mouth_open`, `bb`, `o`, etc.) that don't exist on this ARKit-named rig. If jaw/lip interpenetration artifacts appear on this model, the fix is different from the fix used on the repo's other avatars — likely a calibration gain adjustment (§9), not a constraint-threshold tweak.
8. **All facial writes happen outside `AnimationMixer`.** Morph target influences are written directly to `mesh.morphTargetInfluences[idx]` every frame from `useFrame`; only body/bone animation goes through an `AnimationMixer`-adjacent hand-rolled action pool. Don't expect to find or need a "facial AnimationClip."
9. **Body animation actions are manually driven, not auto-playing.** All `AnimationAction`s for the body clip have `paused = true` permanently; `action.time`/`action.weight` are written by hand every frame by the 3-layer crossfade pool. If you copy this pattern, remember calling `.play()` alone does nothing here — the state machine owns time advancement.
10. **One wall-clock anchor per turn, not per sentence.** The `{start: true}` marker anchors `t0Ms` once; all per-sentence clip frame timestamps are pre-offset by cumulative prior-sentence duration on the backend before publishing. Re-anchoring per sentence would reintroduce jitter compounding across a multi-sentence reply — don't do that if reproducing this.
11. **Ordering across sentence clips is enforced with an awaited `after` future**, not by network arrival order — the NIM/network could otherwise deliver clip 2's frames before clip 1's.
12. **Calibration gains are empirical, tuned by ear/eye, not computed.** `jawopen` shape gain of `0.3` (effective `0.165` after the global `0.55` gain) came from rejecting higher values as visually "exaggerated." Treat any existing calibration constants as a starting point requiring re-verification against your specific rig, not a portable formula.
13. **GPU VRAM exhaustion on the NIM fails silently from the frontend's perspective** — lipsync just stops working with no frontend-visible error. Check NIM container health/logs before debugging client code if lipsync degrades unexpectedly.
14. **Client component requirement**: the R3F `<Canvas>` and everything under `AvatarScene.tsx`/`AvatarModelUrdu.tsx` requires `"use client"` — these use browser-only APIs (`WebGLRenderer`, `requestAnimationFrame`, `performance.now()`) and cannot run server-side in Next.js.
15. **`useFrame` render priority matters**: `AvatarModelUrdu.tsx` registers its per-frame morph-application callback at priority `-1` so it runs before default-priority callbacks in the same frame — if you add other `useFrame` consumers that read `morphTargetInfluences`, be aware of this ordering.

---

## 16. Reproduction guide for another Next.js chatbot

Sequence, adapted to this repo's actual architecture (assuming the target repo also uses R3F, and the target avatar's morph target names are (or can be made to be) ARKit-compatible, matching this doc's girl11.glb case — if not, you'll additionally need the mapping-table approach from this repo's other avatars, not covered here):

1. **Scene**: create a `"use client"` R3F component with a `<Canvas>` — copy camera position/fov/lookAt values from §3 as a starting point, adjust to your model's proportions.
2. **GLB loading**: use `useGLTF(url)` (drei) to load your `.glb`; traverse for `SkinnedMesh` nodes to collect morph-target-bearing meshes (there may be more than one primitive/mesh, as with girl11.glb's 12 primitives — don't assume a single mesh).
3. **Inspect morph target names**: dump `mesh.morphTargetDictionary` for each mesh and diff against the 52 ARKit blendshape names A2F emits. If most match directly (case-insensitive), you can skip the mapping table entirely, as this doc's model does. If not, you need the `ARKIT_TO_METAHUMAN`-style table pattern from this repo's other avatars (not detailed here — see `frontend/src/lib/arkitToMetahuman.ts` if you need that path).
4. **Backend A2F client**: port `agent/plugins/a2f_client.py`'s approach — gRPC client to the A2F NIM, with silence priming, paced ~1s write chunking, and per-request batching of returned frames. This logic is architecture-agnostic (doesn't depend on LiveKit) and can likely be copied close to verbatim into a different backend, as long as you keep the `nvidia_ace` vendored proto package or regenerate equivalent stubs.
5. **Transport frames to frontend**: the specific mechanism (LiveKit text streams) is tied to this repo using LiveKit for its voice pipeline. If your target repo uses plain WebSockets instead, replace `room.local_participant.send_text(...)` / `room.registerTextStreamHandler(...)` with a WebSocket send/`onmessage` pair carrying the same JSON message shapes from §12 — the rest of the pipeline (blendshapePlayer, a2fMorphs) doesn't care about the transport, only the message shape.
6. **Frontend buffering/timing**: port `blendshapePlayer.ts` close to verbatim — it has no framework dependencies beyond `performance.now()`. Keep the single-anchor-per-turn design (§10) if your backend also cuts multiple clips per reply.
7. **Frontend morph application**: port `a2fMorphs.ts`'s direct-match `resolve()` path and the `applyA2FLipsync()` smoothing/clamping logic (§9, §11). Skip the mapping-table fallback and the coarse-viseme anti-conflict constants if your rig, like girl11.glb, doesn't need them (verify by checking whether your target names match the constraint sets' vocabulary at all).
8. **Wire into `useFrame`**: call `applyA2FLipsync()` every frame from your avatar component, before/independent of any body animation update.
9. **Body animation** (optional, separate concern): if you want a similar breathing/listening/talking system, port the segment-range + N-layer crossfade-pool pattern from §5, adapted to your own clip's frame ranges — this part is entirely independent of A2F and can be built/tested separately.
10. **Calibration**: expect to re-tune gain constants (§9) by eye against your specific model — don't assume the `0.55` / `jawopen: 0.3` values transfer.
11. **Env config**: replicate `APP_A2F_URL` / `APP_A2F_API_KEY` / `APP_A2F_TLS_CA` / `APP_A2F_PLAYBACK_DELAY` (§14), plus your own NIM deployment (Docker, GPU-backed).
12. **Verify GPU headroom** for the NIM before assuming any frontend bug when lipsync doesn't appear.

**Can be copied largely as-is**: `blendshapePlayer.ts`, `a2f_client.py`'s gRPC session logic, the message JSON shapes.
**Needs adaptation**: the transport layer (LiveKit-specific → your framework's realtime channel), camera/placement constants (model-specific), calibration gains (model-specific), whether a mapping table is needed at all (depends on your GLB's morph target names).
