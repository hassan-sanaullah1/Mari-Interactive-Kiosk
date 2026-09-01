"use client";

import styles from "./LoadingScreen.module.css";
import { COPY, type Lang } from "@/lib/i18n";

export interface LoadingScreenProps {
  lang: Lang;
  /** False once the avatar is loaded and posed — see page.tsx's avatarReady. */
  ready: boolean;
}

/**
 * Full-screen gate on first load: nothing else — background art, dock,
 * language bar, chat launcher — is meant to be seen until the avatar is
 * actually ready. It stays mounted (fading out via opacity/pointer-events
 * rather than unmounting) so the transition itself never leaves a one-frame
 * gap where the page underneath flashes through.
 */
export default function LoadingScreen({ lang, ready }: LoadingScreenProps) {
  return (
    <div className={`${styles.screen} ${ready ? styles.done : ""}`} aria-hidden={ready}>
      <span className={styles.spinner} />
      <span className={styles.text}>{COPY[lang].loading}</span>
    </div>
  );
}
