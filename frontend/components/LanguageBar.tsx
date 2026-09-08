"use client";

import styles from "./LanguageBar.module.css";
import {
  BrightnessIcon,
  FemaleAvatarIcon,
  MaleAvatarIcon,
  MoonIcon,
} from "./icons";
import type { Lang } from "@/lib/i18n";
import type { Theme } from "@/lib/theme";
import type { AvatarId } from "./avatar/models";

type Props = {
  className?: string;
  lang: Lang;
  onLang: (l: Lang) => void;
  avatar: AvatarId;
  onAvatar: (a: AvatarId) => void;
  theme: Theme;
  onTheme: (t: Theme) => void;
};

/** Labels for the presenter pill — spoken names, not file names. */
const AVATAR_LABELS: Record<Lang, Record<AvatarId, string>> = {
  en: { female: "Female presenter", male: "Male presenter" },
  ur: { female: "خاتون پیشکار", male: "مرد پیشکار" },
};

export default function LanguageBar({
  className,
  lang,
  onLang,
  avatar,
  onAvatar,
  theme,
  onTheme,
}: Props) {
  const next: Theme = theme === "dark" ? "light" : "dark";
  const other: AvatarId = avatar === "female" ? "male" : "female";
  const labels = AVATAR_LABELS[lang];

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

      {/* Presenter switch, in two forms — one shown at a time, by media query.
          Wide screens get the pill: the same shape as the language one, the
          same blue on the active side, but with silhouettes rather than words
          (a glyph needs no translating, and the labels ride along as the
          accessible name and the tooltip).

          A phone cannot have that pill. The cluster shares one bottom row with
          the chat launcher, and measured at the 402-unit reference width the
          row already ends 4 units short of it — a second two-segment pill is
          about 36 units more than the row has, and shrinking its segments to
          fit would put them under any sensible touch target. So narrow screens
          get the compact button below instead, which toggles rather than
          selects, exactly as the theme switch beside it already does. */}
      <div
        className={`${styles.pill} ${styles.iconPill}`}
        role="group"
        aria-label={lang === "ur" ? "پیشکار" : "Presenter"}
      >
        <button
          type="button"
          className={`${styles.seg} ${styles.iconSeg} ${avatar === "female" ? styles.active : ""}`}
          onClick={() => onAvatar("female")}
          aria-pressed={avatar === "female"}
          aria-label={labels.female}
          title={labels.female}
        >
          <FemaleAvatarIcon className={styles.avatarIcon} />
        </button>
        <button
          type="button"
          className={`${styles.seg} ${styles.iconSeg} ${avatar === "male" ? styles.active : ""}`}
          onClick={() => onAvatar("male")}
          aria-pressed={avatar === "male"}
          aria-label={labels.male}
          title={labels.male}
        >
          <MaleAvatarIcon className={styles.avatarIcon} />
        </button>
      </div>

      {/* The phone form of the same control. Like the theme switch, the icon
          shows what you'd switch TO. */}
      <button
        type="button"
        className={styles.compactAvatar}
        onClick={() => onAvatar(other)}
        aria-label={labels[other]}
        title={labels[other]}
      >
        {other === "male" ? (
          <MaleAvatarIcon className={styles.compactIcon} />
        ) : (
          <FemaleAvatarIcon className={styles.compactIcon} />
        )}
      </button>

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
