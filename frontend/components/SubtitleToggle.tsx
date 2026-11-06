"use client";

import styles from "./SubtitleToggle.module.css";
import { CaptionsIcon } from "./Icons";
import { uiCopy, type Lang } from "@/lib/i18n";

type Props = {
  lang: Lang;
  /** Whether the live caption is currently shown. */
  on: boolean;
  onToggle: (on: boolean) => void;
};

/**
 * Shows or hides the live caption under the presenter.
 *
 * Sits in the bottom row immediately left of the chat launcher. The caption it
 * controls is a view preference, not a conversation control, so it takes the
 * chrome surface of the theme/presenter buttons rather than the launcher's blue
 * — and it never touches the voice session: the reply is spoken either way and
 * the chat log keeps the full text, so this hides the on-screen echo only.
 */
export default function SubtitleToggle({ lang, on, onToggle }: Props) {
  const t = uiCopy(lang);
  // The label names the action this tap performs, like the theme switch beside
  // it, so a visitor knows what happens before pressing. `aria-pressed` carries
  // the current state for a screen reader.
  const label = on ? t.subtitlesOff : t.subtitlesOn;

  return (
    <button
      type="button"
      className={`${styles.toggle} ${on ? "" : styles.off}`}
      onClick={() => onToggle(!on)}
      aria-pressed={on}
      aria-label={label}
      title={label}
      // The styling class is a hashed CSS-module name, so a browser test cannot
      // find this button by class; e2e/kiosk.spec.ts asserts on these instead.
      data-testid="subtitle-toggle"
      data-on={on ? "1" : "0"}
    >
      <CaptionsIcon className={styles.icon} off={!on} />
    </button>
  );
}
