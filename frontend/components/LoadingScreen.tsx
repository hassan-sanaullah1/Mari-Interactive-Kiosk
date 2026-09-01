"use client";

import styles from "./LoadingScreen.module.css";
import { COPY, type Lang } from "@/lib/i18n";

export interface LoadingScreenProps {
  lang: Lang;
  /** False once the avatar is loaded and posed — see page.tsx's avatarReady. */
  ready: boolean;
}

/**
 * Small overlay shown only while the avatar model is loading. The background
 * art and the rest of the UI (dock, language bar, chat launcher) are visible
 * underneath from the first paint — only this indicator sits on top until
 * the avatar reports ready. It stays mounted (fading out via opacity rather
 * than unmounting) so the transition never leaves a one-frame gap.
 */
export default function LoadingScreen({ lang, ready }: LoadingScreenProps) {
  return (
    <div className={`${styles.screen} ${ready ? styles.done : ""}`} aria-hidden={ready}>
      <div className={styles.card}>
        <span className={styles.spinner} />
        <span className={styles.text}>{COPY[lang].loading}</span>
      </div>
    </div>
  );
}
