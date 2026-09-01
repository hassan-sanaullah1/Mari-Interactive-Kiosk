"use client";

import styles from "./LanguageBar.module.css";
import { BrightnessIcon, MoonIcon } from "./icons";
import type { Lang } from "@/lib/i18n";
import type { Theme } from "@/lib/theme";

type Props = {
  className?: string;
  lang: Lang;
  onLang: (l: Lang) => void;
  theme: Theme;
  onTheme: (t: Theme) => void;
};

export default function LanguageBar({ className, lang, onLang, theme, onTheme }: Props) {
  const next: Theme = theme === "dark" ? "light" : "dark";

  return (
    <div className={`${styles.bar} ${className ?? ""}`}>
      <div className={styles.pill} role="group" aria-label="Language">
        <button
          type="button"
          className={`${styles.seg} ${lang === "en" ? styles.active : ""}`}
          onClick={() => onLang("en")}
          aria-pressed={lang === "en"}
        >
          English
        </button>
        <button
          type="button"
          lang="ur"
          dir="rtl"
          className={`${styles.seg} ${styles.urdu} ${lang === "ur" ? styles.active : ""}`}
          onClick={() => onLang("ur")}
          aria-pressed={lang === "ur"}
        >
          اردو
        </button>
      </div>

      {/* Dark ⇄ light switch. The icon shows the theme you'd switch TO. */}
      <button
        type="button"
        className={styles.theme}
        onClick={() => onTheme(next)}
        aria-label={`Switch to ${next} mode`}
        title={`Switch to ${next} mode`}
      >
        {theme === "dark" ? (
          <BrightnessIcon className={styles.themeIcon} />
        ) : (
          <MoonIcon className={styles.themeIcon} />
        )}
      </button>
    </div>
  );
}
