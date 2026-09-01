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
    return localStorage.getItem(THEME_KEY) === "light" ? "light" : "dark";
  } catch {
    return "dark";
  }
}
