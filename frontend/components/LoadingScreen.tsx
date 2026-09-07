"use client";

import { useEffect, useState } from "react";
import styles from "./LoadingScreen.module.css";
import { COPY, type Lang } from "@/lib/i18n";
import { AVATAR_MODEL_URL } from "./avatar/state";

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
 * exactly how a slow deployment was being read. Progress comes from the
 * fetch itself rather than three.js's LoadingManager, because the manager only
 * reports totals for requests it issues, and the browser may serve this one
 * from the <link rel="preload"> in layout.tsx instead.
 */
export default function LoadingScreen({ lang, ready }: LoadingScreenProps) {
  const [pct, setPct] = useState<number | null>(null);
  const [slow, setSlow] = useState(false);

  useEffect(() => {
    if (ready) return;
    let live = true;
    // Report progress against the same URL the scene loads. This resolves from
    // the preload/HTTP cache, so it does not cost a second download.
    (async () => {
      try {
        const res = await fetch(AVATAR_MODEL_URL);
        const total = Number(res.headers.get("content-length")) || 0;
        const reader = res.body?.getReader();
        if (!reader || !total) return;
        let got = 0;
        for (;;) {
          const { done, value } = await reader.read();
          if (done || !live) break;
          got += value?.length ?? 0;
          setPct(Math.min(99, Math.round((got / total) * 100)));
        }
      } catch {
        /* progress is a nicety; failure here must not affect loading */
      }
    })();
    // If it is still going after 20s the connection, not the app, is the story.
    const t = setTimeout(() => live && setSlow(true), 20000);
    return () => { live = false; clearTimeout(t); };
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
