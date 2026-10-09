/**
 * The lipsync clip buffer: what the server sends in, what the rig samples out.
 *
 * This is the contract `tests/fixtures/ws_golden.json` pins on the server side, tested
 * here from the browser's end. It is pure arithmetic over a clip's frames, so it needs
 * no WebGL — which is the point: a mistake in the interpolation shows up here in
 * milliseconds rather than as a mouth that looks slightly wrong on screen.
 */

import { beforeEach, describe, expect, it } from "vitest";

import {
  beginClip,
  endClip,
  handleClipMessage,
  hasFrames,
  sample,
  setRigCalibration,
  stop,
  waitForFrames,
} from "@/lib/blendshape-player";

const NAMES = ["JawOpen", "MouthClose", "MouthFunnel"];

/** A clip as the server sends it: names once, then batches of frames. */
function sendClip(uid: string, frames: number[][]): void {
  handleClipMessage({ uid, names: NAMES, frames: [] });
  handleClipMessage({ uid, frames });
}

describe("the clip buffer", () => {
  beforeEach(() => {
    stop();
    setRigCalibration(null);
  });

  it("holds no frames for a clip it has not been sent", () => {
    expect(hasFrames("never-sent")).toBe(false);
  });

  it("accepts the names-only message the server sends first", () => {
    handleClipMessage({ uid: "t1c1", names: NAMES, frames: [] });
    // Names but no frames yet: the clip exists, and is not playable.
    expect(hasFrames("t1c1")).toBe(false);
  });

  it("reports frames once a batch arrives", () => {
    sendClip("t1c1", [[0, 0.5, 0.1, 0.2]]);
    expect(hasFrames("t1c1")).toBe(true);
  });

  it("ignores a clip with no uid", () => {
    handleClipMessage({ names: NAMES, frames: [[0, 1, 1, 1]] });
    expect(sample()).toBeNull();
  });

  it("drops a clip whose names never arrived", () => {
    // The server only omits `names` when its A2F stream failed before the header.
    handleClipMessage({ uid: "orphan", frames: [[0, 0.5, 0.5, 0.5]] });
    expect(hasFrames("orphan")).toBe(false);
  });

  it("samples nothing until a clip is made active", () => {
    sendClip("t1c1", [[0, 1, 1, 1]]);
    expect(sample()).toBeNull();
  });

  it("samples the active clip against its own playback clock", () => {
    setRigCalibration({ gain: 1, shapeGains: {} });
    sendClip("t1c1", [
      [0, 0, 0, 0],
      [1, 1, 1, 1],
    ]);
    let now = 0;
    beginClip("t1c1", () => now);

    const atStart = sample();
    expect(atStart?.names).toEqual(NAMES);
    expect(atStart?.weights[0]).toBeCloseTo(0, 5);

    now = 1;
    expect(sample()?.weights[0]).toBeCloseTo(1, 5);
  });

  it("interpolates between frames rather than stepping", () => {
    setRigCalibration({ gain: 1, shapeGains: {} });
    sendClip("t1c1", [
      [0, 0, 0, 0],
      [1, 1, 1, 1],
    ]);
    let now = 0.25;
    beginClip("t1c1", () => now);
    expect(sample()?.weights[0]).toBeCloseTo(0.25, 2);

    now = 0.75;
    expect(sample()?.weights[0]).toBeCloseTo(0.75, 2);
  });

  it("holds the last frame through a short overrun, then releases", () => {
    // The audio element runs marginally past the last frame's timestamp, so the pose
    // is held for a tail; well past that, sampling stops and the rig returns to rest
    // rather than holding a stale mouth shape for the rest of the turn.
    setRigCalibration({ gain: 1, shapeGains: {} });
    sendClip("t1c1", [
      [0, 0, 0, 0],
      [0.5, 0.8, 0.8, 0.8],
    ]);
    let now = 0.6; // inside the tail
    beginClip("t1c1", () => now);
    expect(sample()?.weights[0]).toBeCloseTo(0.8, 5);

    now = 10; // far past it
    expect(sample()).toBeNull();
  });

  it("stops sampling once the clip ends", () => {
    sendClip("t1c1", [[0, 1, 1, 1]]);
    beginClip("t1c1", () => 0);
    expect(sample()).not.toBeNull();
    endClip("t1c1");
    expect(sample()).toBeNull();
  });

  it("forgets everything on stop, so an interrupted turn leaves no frames behind", () => {
    sendClip("t1c1", [[0, 1, 1, 1]]);
    beginClip("t1c1", () => 0);
    stop();
    expect(sample()).toBeNull();
    expect(hasFrames("t1c1")).toBe(false);
  });
});

describe("rig calibration", () => {
  beforeEach(() => {
    stop();
    setRigCalibration(null);
  });

  it("scales every shape by the global gain", () => {
    setRigCalibration({ gain: 0.5, shapeGains: {} });
    sendClip("t1c1", [[0, 1, 1, 1]]);
    beginClip("t1c1", () => 0);
    const weights = sample()?.weights;
    expect(weights?.[0]).toBeCloseTo(0.5, 5);
    expect(weights?.[1]).toBeCloseTo(0.5, 5);
  });

  it("applies a per-shape trim on top of the global gain", () => {
    // This is how the jaw is held back: the NIM's JawOpen reads hot on these rigs.
    setRigCalibration({ gain: 1, shapeGains: { jawopen: 0.25 } });
    sendClip("t1c1", [[0, 1, 1, 1]]);
    beginClip("t1c1", () => 0);
    const weights = sample()?.weights;
    expect(weights?.[0]).toBeCloseTo(0.25, 5); // JawOpen, trimmed
    expect(weights?.[1]).toBeCloseTo(1, 5); // MouthClose, untouched
  });

  it("matches the NIM's PascalCase names against lowercase trim keys", () => {
    // The NIM sends "JawOpen"; the trim table is keyed lowercase and the lookup
    // lowercases the incoming name. A trim key with any capital letter silently
    // never matches, which is worth knowing before adding one.
    setRigCalibration({ gain: 1, shapeGains: { jawopen: 0.5 } });
    sendClip("t1c1", [[0, 1, 1, 1]]);
    beginClip("t1c1", () => 0);
    expect(sample()?.weights[0]).toBeCloseTo(0.5, 5);

    setRigCalibration({ gain: 1, shapeGains: { JawOpen: 0.5 } });
    sendClip("t2c1", [[0, 1, 1, 1]]);
    beginClip("t2c1", () => 0);
    expect(sample()?.weights[0]).toBeCloseTo(1, 5);
  });

  it("applies the shipped default calibration when a rig installs none", () => {
    // Both rigs install their own (0.9 / jawOpen 0.375), so these defaults only apply
    // before the avatar mounts. Pinned because they are easy to mistake for "no gain".
    sendClip("t1c1", [[0, 1, 1, 1]]);
    beginClip("t1c1", () => 0);
    const weights = sample()?.weights;
    expect(weights?.[0]).toBeCloseTo(0.55 * 0.45, 5); // JawOpen: global x trim
    expect(weights?.[1]).toBeCloseTo(0.55, 5); // MouthClose: global only
  });
});

describe("waitForFrames", () => {
  beforeEach(() => {
    stop();
    setRigCalibration(null);
  });

  it("resolves at once when the frames are already buffered", async () => {
    sendClip("t1c1", [[0, 1, 1, 1]]);
    await expect(waitForFrames("t1c1", 50)).resolves.toBeUndefined();
  });

  it("resolves when the frames arrive during the wait", async () => {
    handleClipMessage({ uid: "t1c1", names: NAMES, frames: [] });
    const waiting = waitForFrames("t1c1", 500);
    handleClipMessage({ uid: "t1c1", frames: [[0, 1, 1, 1]] });
    await expect(waiting).resolves.toBeUndefined();
  });

  it("gives up on the timeout rather than holding the audio back", async () => {
    // A2F being down must cost the mouth, not the voice.
    const started = Date.now();
    await expect(waitForFrames("never-arrives", 60)).resolves.toBeUndefined();
    expect(Date.now() - started).toBeGreaterThanOrEqual(50);
  });
});
