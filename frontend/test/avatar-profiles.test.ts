/**
 * The presenters are supposed to differ only in data. These tests are what makes that
 * a fact rather than an intention.
 *
 * `test/fixtures/avatar-profiles.json` already pins every resolved *value*, so a
 * refactor cannot move a pixel. What it cannot check is the *shape*: that both
 * presenters define the same fields, that neither relies on a value hidden in a
 * component, and that nothing a renderer needs is quietly missing from one of them.
 */

import { describe, expect, it } from "vitest";

import { AVATARS, avatarConfig, DEFAULT_AVATAR, type AvatarId } from "@/components/avatar/models";

const IDS = Object.keys(AVATARS) as AvatarId[];

describe("the presenter registry", () => {
  it("offers at least two presenters", () => {
    expect(IDS.length).toBeGreaterThanOrEqual(2);
  });

  it("has a default that is one of them", () => {
    expect(IDS).toContain(DEFAULT_AVATAR);
  });

  it("keys every entry by its own id", () => {
    // A mismatch here makes the switch select one presenter and load another.
    for (const id of IDS) {
      expect(AVATARS[id].id).toBe(id);
    }
  });

  it("falls back to the default for an id it does not know", () => {
    // The id arrives from localStorage and from the server, so it can be stale.
    expect(avatarConfig("not-a-presenter" as AvatarId).id).toBe(DEFAULT_AVATAR);
  });
});

describe("the presenters define the same things", () => {
  it("has an identical field set on every presenter", () => {
    // One presenter quietly missing a field is how the two drift apart: the renderer
    // reads `undefined`, falls back to a value buried in a component, and that rig
    // then looks subtly different for a reason nobody can find.
    const fieldSets = IDS.map((id) => Object.keys(AVATARS[id]).sort());
    for (const fields of fieldSets) {
      expect(fields).toEqual(fieldSets[0]);
    }
  });

  it("has no undefined field on any presenter", () => {
    for (const id of IDS) {
      const entries = Object.entries(AVATARS[id]).filter(([, value]) => value === undefined);
      expect(entries.map(([key]) => `${id}.${key}`)).toEqual([]);
    }
  });
});

describe("every presenter is renderable", () => {
  it.each(IDS)("%s has the asset facts the loader needs", (id) => {
    const profile = AVATARS[id];
    expect(profile.url).toMatch(/\.glb(\.gz)?$/);
    // Used for the loading percentage; a zero makes it stick or divide by zero.
    expect(profile.bytes.decoded).toBeGreaterThan(0);
    expect(profile.bytes.encoded).toBeGreaterThan(0);
  });

  it.each(IDS)("%s has the three animation windows, each non-empty", (id) => {
    const { segments } = AVATARS[id];
    for (const state of ["breathing", "listening", "talking"] as const) {
      const [from, to] = segments[state].loop;
      expect(to).toBeGreaterThan(from);
    }
  });

  it.each(IDS)("%s has framing values the camera can use", (id) => {
    const profile = AVATARS[id];
    expect(profile.fallbackHeight).toBeGreaterThan(0);
    expect(profile.headTargetY).toBeGreaterThan(0);
  });

  it.each(IDS)("%s has lighting for both themes", (id) => {
    const profile = AVATARS[id];
    for (const theme of [profile.lightThemeLighting, profile.darkThemeLighting]) {
      expect(theme.exposure).toBeGreaterThan(0);
      expect(theme.environment).toBeGreaterThanOrEqual(0);
    }
  });

  it.each(IDS)("%s has UI copy in both languages", (id) => {
    const profile = AVATARS[id];
    expect(profile.label.en.length).toBeGreaterThan(0);
    expect(profile.label.ur.length).toBeGreaterThan(0);
  });

  it.each(IDS)("%s declares a grammatical gender for the Urdu copy", (id) => {
    expect(["f", "m"]).toContain(AVATARS[id].grammaticalGender);
  });
});

describe("lipsync calibration", () => {
  it.each(IDS)("%s installs its own calibration rather than the module default", (id) => {
    // The shipped default in blendshape-player.ts (0.55 / jawOpen 0.45) was measured on an
    // older rig. A presenter that does not override it reads as murmuring.
    const { a2f } = AVATARS[id];
    expect(a2f).not.toBeNull();
    expect(a2f?.gain).toBeGreaterThan(0);
  });

  it.each(IDS)("%s keeps every shape gain within the clamp", (id) => {
    // Weights are clamped to [0,1] after gain; a trim that pushes past it just
    // flattens against the ceiling and loses the shape instead of strengthening it.
    const { a2f } = AVATARS[id];
    for (const [shape, trim] of Object.entries(a2f?.shapeGains ?? {})) {
      expect(trim, `${id}.${shape}`).toBeGreaterThan(0);
      expect(trim, `${id}.${shape}`).toBeLessThanOrEqual(2);
    }
  });

  it.each(IDS)("%s keys its shape gains in lowercase", (id) => {
    // The lookup lowercases the NIM's PascalCase name, so a capitalised key here
    // silently never matches and the trim does nothing at all.
    for (const shape of Object.keys(AVATARS[id].a2f?.shapeGains ?? {})) {
      expect(shape).toBe(shape.toLowerCase());
    }
  });
});
