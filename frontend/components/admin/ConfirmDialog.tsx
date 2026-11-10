"use client";

import { useEffect, useRef } from "react";
import styles from "@/app/admin/admin.module.css";

type Props = {
  title: string;
  message: string;
  /** Optional names the action applies to, listed under the message. */
  items?: string[];
  confirmLabel: string;
  /** Paints the confirm button red. For actions that destroy or interrupt something. */
  destructive?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
};

/**
 * A modal confirmation, used for deleting files and for powering the kiosk off.
 *
 * Focus starts on Cancel rather than Confirm: every use of this dialog guards
 * something irreversible, so a stray Enter should do nothing.
 */
export default function ConfirmDialog({
  title,
  message,
  items,
  confirmLabel,
  destructive = false,
  onConfirm,
  onCancel,
}: Props) {
  const cancelRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    cancelRef.current?.focus();
  }, []);

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") onCancel();
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onCancel]);

  return (
    // A click on the backdrop cancels, but only when it started there: without the
    // target check, releasing the mouse outside after selecting text inside the
    // dialog would close it.
    <div
      className={styles.modalBg}
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onCancel();
      }}
    >
      <div className={styles.modal} role="dialog" aria-modal="true" aria-labelledby="confirm-title">
        <h4 id="confirm-title">{title}</h4>
        <p>{message}</p>
        {items && items.length > 0 ? (
          <ul className={styles.modalList}>
            {items.map((name) => (
              <li key={name}>{name}</li>
            ))}
          </ul>
        ) : null}
        <div className={styles.modalActions}>
          <button type="button" ref={cancelRef} className={`${styles.btn} ${styles.ghost}`} onClick={onCancel}>
            Cancel
          </button>
          <button
            type="button"
            className={`${styles.btn} ${destructive ? styles.danger : styles.primary}`}
            onClick={onConfirm}
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
