export type Theme = "dark" | "light";

export const THEME_KEY = "mari-theme";

/** Applied before first paint by the inline script in app/layout.tsx. */
export function applyTheme(theme: Theme) {
  document.documentElement.dataset.theme = theme;
  try {
    localStorage.setItem(THEME_KEY, theme);
  } catch {
    /* private mode / storage disabled — the theme just won't persist */
  }
}

export function readTheme(): Theme {
  try {
    const stored = localStorage.getItem(THEME_KEY);
    if (stored === "light" || stored === "dark") return stored;
  } catch {
    return "dark";
  }
  // No explicit choice yet: mobile/portrait defaults to light (the mobile
  // background art is light-themed); desktop stays dark. Same breakpoint the
  // CSS uses everywhere (app/globals.css and friends), kept in sync with the
  // inline script in app/layout.tsx that applies this before first paint.
  // Forced on for every screen right now (`min-width: 0` always matches), so
  // the site opens in light mode by default; restore `(max-aspect-ratio: 6/5)`
  // to go back to real-device detection.
  try {
    if (window.matchMedia("(min-width: 0)").matches) return "light";
  } catch {
    /* matchMedia unavailable */
  }
  return "dark";
}
