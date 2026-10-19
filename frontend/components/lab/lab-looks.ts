/**
 * One Phase A look per presenter per theme. The lab's top-level Phase A fields
 * are always the look of the presenter and theme on screen; `looks` keeps the
 * other three. Switching presenter or theme files the outgoing look away and
 * brings the incoming one in, so tuning one never changes another.
 */

import { AVATARS, type AvatarId } from "@/components/avatar/models";
import type { Theme } from "@/lib/theme";
import type { LabSettings } from "./LabScene";

export const PHASE_A_KEYS = [
  "realism",
  "realismParams",
  "life",
  "ao",
  "grade",
  "shadowSoftness",
  "shadowStrength",
] as const;

export type PhaseA = Pick<LabSettings, (typeof PHASE_A_KEYS)[number]>;
export type Looks = Record<AvatarId, Record<Theme, PhaseA>>;

const THEMES: Theme[] = ["dark", "light"];

export function phaseAOf(settings: PhaseA): PhaseA {
  return Object.fromEntries(PHASE_A_KEYS.map((key) => [key, settings[key]])) as PhaseA;
}

/** The same look for every presenter and theme: the starting point. */
export function sameLookEverywhere(look: PhaseA): Looks {
  const presenters = Object.keys(AVATARS) as AvatarId[];
  return Object.fromEntries(
    presenters.map((id) => [id, Object.fromEntries(THEMES.map((theme) => [theme, structuredClone(look)]))]),
  ) as Looks;
}

export function setLook(looks: Looks, presenter: AvatarId, theme: Theme, look: PhaseA): Looks {
  return { ...looks, [presenter]: { ...looks[presenter], [theme]: look } };
}

/** Make `looks` agree with the top-level fields, for the presenter and theme on screen. */
export function fileCurrentLook(settings: LabSettings): LabSettings {
  return { ...settings, looks: setLook(settings.looks, settings.presenter, settings.theme, phaseAOf(settings)) };
}

/**
 * Every settings change goes through this. Same presenter and theme: the edit
 * is filed under them. A switch: the outgoing look is filed as it was before
 * the change, and the incoming one becomes the top-level fields.
 */
export function syncLooks(previous: LabSettings, next: LabSettings): LabSettings {
  const isSwitch = previous.presenter !== next.presenter || previous.theme !== next.theme;
  if (!isSwitch) return fileCurrentLook(next);
  const looks = setLook(next.looks, previous.presenter, previous.theme, phaseAOf(previous));
  return { ...next, ...looks[next.presenter][next.theme], looks };
}
