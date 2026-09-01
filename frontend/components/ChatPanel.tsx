"use client";

import { useEffect, useLayoutEffect, useRef, useState } from "react";
import styles from "./ChatPanel.module.css";
import { ChatIcon, CloseIcon, SendIcon } from "./icons";
import { COPY, type Lang } from "@/lib/i18n";
import type { Message } from "@/hooks/useVoiceSession";

type Props = {
  lang: Lang;
  open: boolean;
  onOpen: () => void;
  onClose: () => void;
  messages: Message[];
  /** Live (non-final) transcript of the current utterance. */
  partial: string;
  onSend: (text: string) => void;
};

export default function ChatPanel({ lang, open, onOpen, onClose, messages, partial, onSend }: Props) {
  const [draft, setDraft] = useState("");
  const logRef = useRef<HTMLDivElement>(null);
  const seenRef = useRef(0);
  const [unread, setUnread] = useState(0);
  const t = COPY[lang];
  const rtl = lang === "ur";

  // Pin to the newest turn as the reply streams in.
  useLayoutEffect(() => {
    if (!open) return;
    const el = logRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [open, messages, partial]);

  // Badge the launcher for turns that arrive while the panel is closed.
  useEffect(() => {
    if (open) {
      seenRef.current = messages.length;
      setUnread(0);
    } else {
      setUnread(Math.max(0, messages.length - seenRef.current));
    }
  }, [open, messages.length]);

  if (!open) {
    return (
      <button type="button" className={styles.launcher} onClick={onOpen} aria-label={`Open ${t.chat}`}>
        <ChatIcon className={styles.launcherIcon} />
        {unread > 0 && <span className={styles.badge}>{unread > 9 ? "9+" : unread}</span>}
      </button>
    );
  }

  const submit = () => {
    const text = draft.trim();
    if (!text) return;
    onSend(text);
    setDraft("");
  };

  return (
    <section className={styles.panel} aria-label={t.chat}>
      <header className={styles.header}>
        <h2 className={styles.title}>{t.chat}</h2>
        <button type="button" className={styles.close} onClick={onClose} aria-label={`Close ${t.chat}`}>
          <CloseIcon className={styles.closeIcon} />
        </button>
      </header>

      <div className={styles.log} ref={logRef} aria-live="polite">
        {messages.length === 0 && !partial && (
          <p className={styles.empty}>
            {t.idle}
            <br />
            {t.placeholder}
          </p>
        )}

        {messages.map((m) => (
          <div
            key={m.id}
            className={`${m.role === "user" ? styles.user : styles.assistant} ${rtl ? styles.rtl : ""}`}
          >
            {m.text}
          </div>
        ))}

        {partial && <div className={`${styles.user} ${styles.pending} ${rtl ? styles.rtl : ""}`}>{partial}</div>}
      </div>

      <div className={styles.composer}>
        <textarea
          className={`${styles.input} ${rtl ? styles.rtl : ""}`}
          placeholder={t.placeholder}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              submit();
            }
          }}
          rows={3}
          aria-label={t.placeholder}
        />
        <button
          type="button"
          className={styles.send}
          onClick={submit}
          disabled={!draft.trim()}
          aria-label="Send"
        >
          <SendIcon className={styles.sendIcon} />
        </button>
      </div>
    </section>
  );
}
