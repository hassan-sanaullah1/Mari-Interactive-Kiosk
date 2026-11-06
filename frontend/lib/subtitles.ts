/**
 * Whether the live caption under the presenter is shown, remembered across
 * reloads.
 *
 * Same shape as lib/theme.ts and lib/avatar.ts, and for the same reason: a
 * kiosk reloads often, and an operator who switched the captions off should not
 * have to switch them off again.
 *
 * Like the presenter and unlike the theme there is no pre-paint inline script
 * for this — the caption only appears once a reply is being spoken, which is
 * long after first paint, so reading it from an effect is early enough.
 */

export const SUBTITLES_KEY = "mari-subtitles";

/** Shown unless the visitor has turned them off. */
export const DEFAULT_SUBTITLES_ON = true;

export function applySubtitles(on: boolean) {
  try {
    localStorage.setItem(SUBTITLES_KEY, on ? "on" : "off");
  } catch {
    /* private mode / storage disabled — the choice just won't persist */
  }
}

export function readSubtitles(): boolean {
  try {
    const stored = localStorage.getItem(SUBTITLES_KEY);
    if (stored === "on") return true;
    if (stored === "off") return false;
  } catch {
    return DEFAULT_SUBTITLES_ON;
  }
  return DEFAULT_SUBTITLES_ON;
}
