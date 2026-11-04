"use client";

import { useEffect, useState } from "react";
import styles from "./LoadingScreen.module.css";
import { uiCopy, type Lang } from "@/lib/i18n";
import { onAvatarProgress } from "@/lib/avatar-fetch";

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
 *
 * It shows real download progress rather than an indeterminate spinner alone.
 * The model is ~20MB, and on a slow link that is the difference between "this
 * is working, it is 40% through" and a screen that looks frozen — which is
 * exactly how a slow deployment was being read.
 */
export default function LoadingScreen({ lang, ready }: LoadingScreenProps) {
  const [pct, setPct] = useState<number | null>(null);
  const [slow, setSlow] = useState(false);

  useEffect(() => {
    if (ready) return;
    // Start each load from nothing. Switching presenters re-arms this overlay
    // with the previous rig's percentage still in state, which would show the
    // new download opening at "99%" and counting down.
    setPct(null);
    setSlow(false);
    // Subscribe to the one shared download (lib/avatar-fetch.ts). This used to
    // open its own fetch for the model, which on a slow link was a third
    // parallel copy of the same 20MB — a progress indicator that made the thing
    // it was measuring slower.
    const off = onAvatarProgress((loaded, total) => {
      if (total > 0) setPct(Math.min(99, Math.round((loaded / total) * 100)));
    });
    // Past this point the connection, not the app, is the story — say so rather
    // than showing a spinner that is indistinguishable from a hang.
    const t = setTimeout(() => setSlow(true), 20000);
    return () => { off(); clearTimeout(t); };
  }, [ready]);

  const t = uiCopy(lang);

  return (
    <div className={`${styles.screen} ${ready ? styles.done : ""}`} aria-hidden={ready}>
      <div className={styles.card}>
        <span className={styles.spinner} />
        {/* The percentage is its own element with dir="ltr". Concatenated into
            the Urdu string it gets reordered by the bidi algorithm - "45%"
            jumps to the wrong side of the sentence and the % lands before the
            digits. Separating them keeps the number reading left-to-right
            inside a right-to-left line, which is what a reader expects. */}
        <span className={styles.text} dir={lang === "ur" ? "rtl" : "ltr"}>
          <span>{t.loading}</span>
          {pct !== null ? (
            <span className={styles.pct} dir="ltr">
              {pct}%
            </span>
          ) : null}
        </span>
        {slow && !ready ? <span className={styles.note}>{t.slowConnection}</span> : null}
      </div>
    </div>
  );
}
