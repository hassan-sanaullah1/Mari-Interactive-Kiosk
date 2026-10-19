/**
 * The kiosk's presenter looks (components/avatar/profiles/looks.ts) must be
 * exactly the lab exports the team approved (test/fixtures/lab-exports/). A
 * difference here means the kiosk no longer renders what was signed off.
 */
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { AVATARS, type AvatarId } from "@/components/avatar/models";
import { presenterLook, PRESENTER_LOOKS, type PresenterLook } from "@/components/avatar/profiles/looks";

type Export = {
  scope: { presenter: AvatarId; theme: "light" | "dark" };
  rig: {
    studio: Record<string, unknown>;
    rigLighting: Record<string, { light: unknown }>;
    camera: { desktop: { headRoom: number }; mobile: { headRoom: number } };
  };
  scene: Record<string, unknown> & { look: string; lights: string; environment: string; camera: string; tone: string };
  resolved: { lights: Record<string, unknown>; environment: Record<string, unknown>; camera: { headRoom: number } };
};

const load = (name: string): Export =>
  JSON.parse(readFileSync(fileURLToPath(new URL(`./fixtures/lab-exports/${name}`, import.meta.url)), "utf8"));

const EXPORTS = [load("female-light.json"), load("male-light.json")];

describe.each(EXPORTS)("the kiosk look for $scope.presenter, $scope.theme", (approved) => {
  const { presenter, theme } = approved.scope;
  const look = PRESENTER_LOOKS[presenter][theme] as PresenterLook;

  it("exists", () => {
    expect(look).toBeDefined();
  });

  it("has the approved surfaces, expression, AO, grade and shadows", () => {
    for (const key of ["realism", "realismParams", "life", "ao", "grade", "shadowSoftness", "shadowStrength"] as const) {
      expect(look[key], key).toEqual(approved.scene[key]);
    }
    expect(look.toneMapping).toBe(approved.scene.tone);
  });

  it("uses the materials the lab showed", () => {
    expect(look.isCorrected).toBe(approved.scene.look === "kiosk");
  });

  it("has the approved lights and reflections", () => {
    if (approved.scene.lights === "editable") {
      expect(look.lighting.kind).toBe("studio");
      if (look.lighting.kind !== "studio") return;
      expect(approved.scene.environment).toBe("panels");
      expect(look.lighting.studio).toEqual(approved.rig.studio[theme]);
      // Reflection strength as the lab displayed it, not as it recorded it: see
      // the note on the male look in profiles/looks.ts.
      expect(look.lighting.rigLighting).toEqual({
        ...(approved.rig.rigLighting[presenter][theme as "light"] as object),
        environment: 1,
      });
    } else {
      expect(look.lighting.kind).toBe("fixed");
      if (look.lighting.kind !== "fixed") return;
      const { source: _s, type: _t, ...lights } = approved.resolved.lights;
      const { source: _es, type: _et, ...environment } = approved.resolved.environment;
      expect(look.lighting.lights).toEqual(lights);
      expect(look.lighting.environment).toEqual(environment);
    }
  });

  it("frames the shot the way it was judged", () => {
    if (approved.scene.camera === "editable") {
      expect(look.headRoom).toEqual({
        landscape: approved.rig.camera.desktop.headRoom,
        portrait: approved.rig.camera.mobile.headRoom,
      });
    } else {
      // The kiosk's own framing: one head room for every layout.
      expect(look.headRoom).toEqual({ landscape: approved.resolved.camera.headRoom, portrait: approved.resolved.camera.headRoom });
    }
  });
});

describe("the feature flag", () => {
  it("is on, so the light theme renders the approved looks and the dark theme is unchanged", () => {
    for (const id of Object.keys(AVATARS) as AvatarId[]) {
      expect(presenterLook(id, "light")).toBe(PRESENTER_LOOKS[id].light);
      expect(presenterLook(id, "dark")).toBeNull();
    }
  });

  it("has no dark-theme look yet", () => {
    for (const id of Object.keys(AVATARS) as AvatarId[]) expect(PRESENTER_LOOKS[id].dark).toBeUndefined();
  });
});
