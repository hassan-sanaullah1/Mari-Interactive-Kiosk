/**
 * The studio — the per-theme light rig in components/avatar/tuning.ts.
 *
 * The profiles snapshot (test/fixtures/avatar-profiles.json) cannot see any of
 * this: it serializes what models.ts spreads, and a studio is a property of the
 * ROOM rather than of a presenter, so it is shared rather than per-rig. These
 * assertions are what stands in for that snapshot.
 *
 * The first one is the load-bearing one. The light theme's rig was rebuilt to
 * match the lobby backdrop on the explicit condition that the dark theme does
 * not move, and a deep-equal against a literal is the only way to say that
 * which stays true as the light studio is tuned.
 */
import { describe, expect, it } from "vitest";
import { STUDIO } from "@/components/avatar/tuning";

const AVATAR_STATES = ["idle", "listening", "thinking", "speaking"] as const;
const LIGHT_NAMES = ["key", "fill", "top", "rim", "kick", "face"] as const;

describe("the dark studio", () => {
  it("is exactly the rig that was authored against the dark backdrop", () => {
    expect(STUDIO.dark).toEqual({
      ambientColor: "#ffffff",
      colors: {
        key: "#ffe4c9",
        fill: "#c9d6ff",
        rim: "#4fd8e8",
        kick: "#3fd39a",
        top: "#e8daf5",
        face: "#fff2e0",
      },
      placement: {
        key: { position: [2, 3, 2], intensity: 1.4 },
        fill: { position: [-2, 2, -1], intensity: 0.4 },
        top: { position: [0, 3, 1.5], angle: 0.4, penumbra: 1, intensity: 0.9, decay: 2 },
        rim: { position: [-2.2, 2.2, -1.8], angle: 0.7, penumbra: 0.9, intensity: 1.4, decay: 2 },
        kick: { position: [2.4, 2.0, -1.6], angle: 0.7, penumbra: 0.9, intensity: 0.8, decay: 2 },
        face: {
          position: [0, 2.2, 1],
          angle: 0.18,
          penumbra: 0.6,
          intensity: 1.6,
          distance: 1.6,
          decay: 2,
        },
      },
      states: {
        idle: { key: 1.4, fill: 0.4, rim: 2, kick: 5, top: 0.9 },
        listening: { key: 1.8, fill: 0.5, rim: 2, kick: 5, top: 1.1 },
        thinking: { key: 1.2, fill: 0.5, rim: 2, kick: 5, top: 0.8 },
        speaking: { key: 1.8, fill: 0.5, rim: 2, kick: 5, top: 1.2 },
      },
      environment: {
        resolution: 256,
        lightformers: [
          { intensity: 2, position: [0, 2, 3], scale: [4, 1, 1], color: "#ffe0cc" },
          { intensity: 1, position: [-3, 1, -1], scale: [3, 2, 1], color: "#c9d6ff" },
          { intensity: 0.5, position: [3, 0, -2], scale: [2, 3, 1], color: "#ffd6e0" },
        ],
      },
      shadow: {
        intensity: 0.55,
        mapSize: 2048,
        bias: -0.0002,
        normalBias: 0.01,
        extent: 1,
        targetY: 1.1,
      },
    });
  });
});

describe("the two studios describe the same room", () => {
  it.each(["colors", "placement", "states"] as const)(
    "declares the same %s in both themes",
    (part) => {
      expect(Object.keys(STUDIO.light[part]).sort()).toEqual(Object.keys(STUDIO.dark[part]).sort());
    },
  );

  it.each(["dark", "light"] as const)("%s lights every conversation state", (theme) => {
    expect(Object.keys(STUDIO[theme].states).sort()).toEqual([...AVATAR_STATES].sort());
  });

  // The frame loop lerps position, angle, penumbra and distance between the
  // studios but not decay, so a studio that disagreed about decay would snap.
  it.each(["dark", "light"] as const)("gives every %s spotlight decay 2", (theme) => {
    for (const name of LIGHT_NAMES) {
      const placement = STUDIO[theme].placement[name];
      if (placement.angle !== undefined) expect(placement.decay).toBe(2);
    }
  });
});

describe("the light studio matches the lobby backdrop", () => {
  // bg-mobile-light.png is a daylit marble lobby. The cyan rim and green kick
  // belong to the dark theme's coloured backdrop and appear nowhere in that
  // plate; the Mari LEDs in it are part of the artwork, not of her lighting.
  it("casts no cyan or green light on her", () => {
    for (const name of LIGHT_NAMES) {
      const hex = STUDIO.light.colors[name];
      const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16));
      expect({ name, greenDominant: g > r && g > b }).toEqual({ name, greenDominant: false });
    }
  });

  // Her feet sit far below the bottom of the frame, so there is no contact
  // shadow and no ground plane. The floor bounce is the only thing standing in
  // for the marble, and the rim is the only thing separating her shadow side
  // from the dark meeting room behind it.
  // Below the head so it still opens up the jaw, but nowhere near low enough to
  // be a footlight — it sat at -1.2 once and lit her nostrils from underneath.
  it("bounces off the floor without becoming a footlight", () => {
    const y = STUDIO.light.placement.kick.position[1];
    expect(y).toBeGreaterThan(0);
    expect(y).toBeLessThan(1);
  });

  it("puts the key camera-left and the rim camera-right, as the plate is lit", () => {
    expect(STUDIO.light.placement.key.position[0]).toBeLessThan(0);
    expect(STUDIO.light.placement.rim.position[0]).toBeGreaterThan(0);
    expect(STUDIO.light.placement.rim.position[2]).toBeLessThan(0);
  });
});
