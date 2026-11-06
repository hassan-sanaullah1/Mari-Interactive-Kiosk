"use client";

import { useLayoutEffect, useRef } from "react";
import styles from "./Subtitle.module.css";
import type { Lang } from "@/lib/i18n";

type Props = {
  /** The reply's language, so Urdu gets the Naskh face and RTL direction. */
  lang: Lang;
  /** The one sentence being spoken right now; empty renders nothing. */
  line: string;
};

/**
 * A hard safety floor on the font scale, only so a bug can't drive the size to
 * zero. It sits far below anything a real reply sentence reaches, so the whole
 * line is always shown in full — never clipped with an ellipsis.
 */
const MIN_SCALE = 0.2;

/**
 * Live caption of the sentence the presenter is speaking, shown one line at a
 * time just above the mic. The reply is already announced through the chat
 * log's aria-live region, so this visual echo is hidden from screen readers to
 * avoid reading each sentence twice.
 */
export default function Subtitle({ lang, line }: Props) {
  const ref = useRef<HTMLParagraphElement>(null);
  const rtl = lang === "ur";

  // Shrink the font just enough that the whole sentence fits on its single line,
  // so it is shown in full rather than cut off with an ellipsis. Runs before
  // paint on each new line, and on resize since the fit depends on the frame
  // width. Converges in a few steps because each pass over-shrinks slightly.
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const fit = () => {
      el.style.fontSize = "";
      const basePx = parseFloat(getComputedStyle(el).fontSize);
      const minPx = basePx * MIN_SCALE;
      for (let guard = 0; guard < 16 && el.scrollWidth > el.clientWidth + 1; guard++) {
        const cur = parseFloat(getComputedStyle(el).fontSize);
        const next = cur * (el.clientWidth / el.scrollWidth) * 0.96;
        if (next <= minPx) {
          el.style.fontSize = `${minPx}px`;
          break;
        }
        el.style.fontSize = `${next}px`;
      }
    };
    fit();
    window.addEventListener("resize", fit);
    return () => window.removeEventListener("resize", fit);
  }, [line]);

  if (!line) return null;
  return (
    <div className={styles.wrap} aria-hidden="true">
      {/* Keyed on the text so each new sentence remounts and the fit re-runs. */}
      <p key={line} ref={ref} className={styles.line} lang={lang} dir={rtl ? "rtl" : "ltr"}>
        {line}
      </p>
    </div>
  );
}
