"use client";

import { useEffect, useState } from "react";
import styles from "./LoadingScreen.module.css";
import { COPY, type Lang } from "@/lib/i18n";
import { onAvatarProgress } from "@/lib/avatarFetch";

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
    // Subscribe to the one shared download (lib/avatarFetch.ts). This used to
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

  return (
    <div className={`${styles.screen} ${ready ? styles.done : ""}`} aria-hidden={ready}>
      <div className={styles.card}>
        <span className={styles.spinner} />
        <span className={styles.text}>
          {COPY[lang].loading}
          {pct !== null ? ` ${pct}%` : ""}
        </span>
        {slow && !ready ? (
          <span className={styles.text} style={{ opacity: 0.7, fontSize: "0.85em" }}>
            {lang === "ur" ? "سست کنکشن…" : "Slow connection…"}
          </span>
        ) : null}
      </div>
    </div>
  );
}
