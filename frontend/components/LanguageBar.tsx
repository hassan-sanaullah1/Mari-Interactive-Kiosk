"use client";

import styles from "./LanguageBar.module.css";
import {
  BrightnessIcon,
  FemaleAvatarIcon,
  MaleAvatarIcon,
  MoonIcon,
} from "./icons";
import { uiCopy, type Lang } from "@/lib/i18n";
import type { Theme } from "@/lib/theme";
import { AVATARS, type AvatarConfig, type AvatarId } from "./avatar/models";

type Props = {
  className?: string;
  lang: Lang;
  onLang: (l: Lang) => void;
  avatar: AvatarId;
  onAvatar: (a: AvatarId) => void;
  theme: Theme;
  onTheme: (t: Theme) => void;
};

/** The profile names a silhouette; this is the only place that maps one to a component. */
const ICONS = {
  female: FemaleAvatarIcon,
  male: MaleAvatarIcon,
} as const;

/** The presenters, in the order they are declared. */
const PRESENTERS: AvatarConfig[] = Object.values(AVATARS);

export default function LanguageBar({
  className,
  lang,
  onLang,
  avatar,
  onAvatar,
  theme,
  onTheme,
}: Props) {
  const t = uiCopy(lang);
  const nextTheme: Theme = theme === "dark" ? "light" : "dark";
  // The next presenter round, so the compact button cycles rather than selects.
  const currentIndex = PRESENTERS.findIndex((p) => p.id === avatar);
  const nextPresenter = PRESENTERS[(currentIndex + 1) % PRESENTERS.length];
  const NextIcon = ICONS[nextPresenter.icon];

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
      <div className={`${styles.pill} ${styles.iconPill}`} role="group" aria-label={t.presenter}>
        {PRESENTERS.map((presenter) => {
          const Icon = ICONS[presenter.icon];
          const label = presenter.label[lang];
          return (
            <button
              key={presenter.id}
              type="button"
              className={`${styles.seg} ${styles.iconSeg} ${avatar === presenter.id ? styles.active : ""}`}
              onClick={() => onAvatar(presenter.id)}
              aria-pressed={avatar === presenter.id}
              aria-label={label}
              title={label}
            >
              <Icon className={styles.avatarIcon} />
            </button>
          );
        })}
      </div>

      {/* The phone form of the same control. Like the theme switch, the icon
          shows what you'd switch TO. */}
      <button
        type="button"
        className={styles.compactAvatar}
        onClick={() => onAvatar(nextPresenter.id)}
        aria-label={nextPresenter.label[lang]}
        title={nextPresenter.label[lang]}
      >
        <NextIcon className={styles.compactIcon} />
      </button>

      {/* Dark ⇄ light switch. The icon shows the theme you'd switch TO. */}
      <button
        type="button"
        className={styles.theme}
        onClick={() => onTheme(nextTheme)}
        aria-label={`Switch to ${nextTheme} mode`}
        title={`Switch to ${nextTheme} mode`}
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
