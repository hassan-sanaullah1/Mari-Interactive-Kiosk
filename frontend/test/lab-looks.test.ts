/**
 * The avatar lab keeps one Phase A look per presenter per theme, and exports
 * and imports one presenter in one theme at a time. These pin that a change,
 * a switch or an import for one of them never reaches another.
 */
import { describe, expect, it } from "vitest";
import { AVATARS, type AvatarId } from "@/components/avatar/models";
import { buildExport, kioskRig } from "@/components/lab/lab-rig";
import { phaseAOf, sameLookEverywhere, syncLooks, type PhaseA } from "@/components/lab/lab-looks";
import type { LabSettings } from "@/components/lab/LabScene";
import { settingsFromImport } from "@/components/lab/lab-storage";
import { DEFAULT_LIFE, NO_LIFE } from "@/components/avatar/liveliness";
import { NO_GRADE } from "@/components/avatar/PostEffects";
import { DEFAULT_REALISM_PARAMS, KIOSK_REALISM } from "@/components/avatar/realism";

const [FIRST, SECOND] = Object.keys(AVATARS) as AvatarId[];

const PLAIN: PhaseA = {
  realism: KIOSK_REALISM,
  realismParams: DEFAULT_REALISM_PARAMS,
  life: NO_LIFE,
  ao: { enabled: false, intensity: 0.8, radius: 0.12 },
  grade: NO_GRADE,
  shadowSoftness: 0,
  shadowStrength: 0,
};

function settings(overrides: Partial<LabSettings> = {}): LabSettings {
  return {
    ...PLAIN,
    presenter: FIRST,
    theme: "light",
    rig: kioskRig(),
    looks: sameLookEverywhere(PLAIN),
    ...overrides,
  } as LabSettings;
}

const tuned = (base: LabSettings): LabSettings => ({
  ...base,
  ao: { enabled: true, intensity: 0.4, radius: 0.05 },
  life: DEFAULT_LIFE,
  shadowSoftness: 5,
});

describe("one Phase A look per presenter per theme", () => {
  it("files an edit under the presenter and theme on screen only", () => {
    const before = settings();
    const after = syncLooks(before, tuned(before));
    expect(after.looks[FIRST].light.ao.enabled).toBe(true);
    expect(after.looks[FIRST].dark).toEqual(PLAIN);
    expect(after.looks[SECOND].light).toEqual(PLAIN);
    expect(after.looks[SECOND].dark).toEqual(PLAIN);
  });

  it("switching presenter brings in theirs and keeps the outgoing one", () => {
    const edited = syncLooks(settings(), tuned(settings()));
    const switched = syncLooks(edited, { ...edited, presenter: SECOND });
    expect(phaseAOf(switched)).toEqual(PLAIN);
    expect(switched.looks[FIRST].light.shadowSoftness).toBe(5);

    const back = syncLooks(switched, { ...switched, presenter: FIRST });
    expect(phaseAOf(back)).toEqual(phaseAOf(tuned(settings())));
  });

  it("switching theme does the same, the other way round", () => {
    const start = settings({ presenter: SECOND, theme: "dark" });
    const edited = syncLooks(start, tuned(start));
    const switched = syncLooks(edited, { ...edited, theme: "light" });
    expect(phaseAOf(switched)).toEqual(PLAIN);
    expect(switched.looks[SECOND].dark.ao.enabled).toBe(true);
    expect(switched.looks[FIRST].dark).toEqual(PLAIN);
  });
});

describe("export and import are scoped to one presenter and theme", () => {
  const exported = (from: LabSettings) => {
    const { rig, looks: _looks, ...scene } = from;
    return JSON.stringify(buildExport(rig, scene, { presenter: from.presenter, theme: from.theme }));
  };

  it("an export carries only its presenter and theme", () => {
    const document = JSON.parse(exported(tuned(settings({ presenter: SECOND, theme: "dark" }))));
    expect(document.scope).toEqual({ presenter: SECOND, theme: "dark" });
    expect(Object.keys(document.rig.studio)).toEqual(["dark"]);
    expect(Object.keys(document.rig.rigLighting)).toEqual([SECOND]);
    expect(Object.keys(document.rig.rigLighting[SECOND])).toEqual(["dark", "backLight"]);
    expect(Object.keys(document.rig.camera.desktop.rigs)).toEqual([SECOND]);
    expect(Object.keys(document.rig.camera.mobile.rigs)).toEqual([SECOND]);
    expect(document.scene.looks).toBeUndefined();
  });

  it.each([
    [FIRST, "light"],
    [SECOND, "dark"],
  ] as const)("importing %s/%s changes that look and rig part only", (presenter, theme) => {
    const source = tuned(settings({ presenter, theme }));
    source.rig.studio[theme].placement.key.intensity = 9;
    source.rig.rigLighting[presenter][theme].exposure = 0.5;

    // Imported while looking at a different presenter and theme.
    const other = presenter === FIRST ? SECOND : FIRST;
    const otherTheme = theme === "light" ? "dark" : "light";
    const base = settings({ presenter: other, theme: otherTheme });
    const result = settingsFromImport(base, exported(source));
    if (!result.ok) throw new Error(result.error);
    const imported = result.settings;

    expect([imported.presenter, imported.theme]).toEqual([presenter, theme]);
    expect(imported.looks[presenter][theme].shadowSoftness).toBe(5);
    expect(imported.rig.studio[theme].placement.key.intensity).toBe(9);
    expect(imported.rig.rigLighting[presenter][theme].exposure).toBe(0.5);

    expect(imported.looks[presenter][otherTheme]).toEqual(PLAIN);
    expect(imported.looks[other][theme]).toEqual(PLAIN);
    expect(imported.looks[other][otherTheme]).toEqual(PLAIN);
    expect(imported.rig.studio[otherTheme]).toEqual(base.rig.studio[otherTheme]);
    expect(imported.rig.rigLighting[other]).toEqual(base.rig.rigLighting[other]);
    expect(imported.rig.rigLighting[presenter][otherTheme]).toEqual(base.rig.rigLighting[presenter][otherTheme]);
    expect(imported.rig.camera.desktop.rigs[other]).toEqual(base.rig.camera.desktop.rigs[other]);
  });
});
