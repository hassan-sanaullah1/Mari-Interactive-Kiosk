"use client";

import styles from "./Subtitle.module.css";
import type { Lang } from "@/lib/i18n";

type Props = {
  /** The reply's language, so Urdu gets the Naskh face and RTL direction. */
  lang: Lang;
  /** The one sentence being spoken right now; empty renders nothing. */
  line: string;
};

/**
 * Live caption of the sentence the presenter is speaking, shown just above the
 * mic. The reply is already announced through the chat log's aria-live region,
 * so this visual echo is hidden from screen readers to avoid reading each
 * sentence twice.
 *
 * The type size is fixed and a long sentence wraps onto more lines instead.
 * Shrinking each sentence to fit one line made the size jump between sentences
 * of the same reply, and the longest ones came out too small to read.
 */
export default function Subtitle({ lang, line }: Props) {
  if (!line) return null;
  const rtl = lang === "ur";
  return (
    <div className={styles.wrap} aria-hidden="true">
      {/* Keyed on the text so each new sentence remounts and replays the fade-in. */}
      <p key={line} className={styles.line} lang={lang} dir={rtl ? "rtl" : "ltr"}>
        {line}
      </p>
    </div>
  );
}
