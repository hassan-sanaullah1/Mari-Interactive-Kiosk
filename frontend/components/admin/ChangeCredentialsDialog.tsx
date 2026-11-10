"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";
import styles from "@/app/admin/admin.module.css";
import { AdminError, setCredentials, type Credentials } from "@/lib/admin-api";

type Props = {
  creds: Credentials;
  /** Called with the new credentials once the server has accepted them. */
  onSaved: (next: Credentials) => void;
  onCancel: () => void;
};

/** Mirrors admin_credentials.validate() on the server, so the rules read the same. */
const MIN_LENGTH = 8;

export default function ChangeCredentialsDialog({ creds, onSaved, onCancel }: Props) {
  const [user, setUser] = useState(creds.user);
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [reveal, setReveal] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const firstField = useRef<HTMLInputElement>(null);

  useEffect(() => {
    firstField.current?.focus();
  }, []);

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") onCancel();
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onCancel]);

  // Live rules, shown as the operator types rather than only on submit.
  const rules = [
    { id: "len", label: `At least ${MIN_LENGTH} characters`, ok: next.length >= MIN_LENGTH },
    { id: "num", label: "Contains a number", ok: /\d/.test(next) },
    { id: "diff", label: "Different from the current password", ok: next.length > 0 && next !== current },
  ];
  const rulesPass = rules.every((rule) => rule.ok);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (busy) return;
    const trimmed = user.trim();
    if (!trimmed) {
      setError("The username cannot be empty.");
      return;
    }
    if (!current) {
      setError("Enter your current password.");
      return;
    }
    if (!rulesPass) {
      setError("The new password does not meet the requirements above.");
      return;
    }
    if (next !== confirm) {
      setError("The new passwords do not match.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      await setCredentials(creds, {
        current_password: current,
        new_user: trimmed,
        new_password: next,
      });
      // From here the old password is dead, so the session has to carry the new one.
      onSaved({ user: trimmed, token: next });
    } catch (cause) {
      if (cause instanceof AdminError && cause.status === 401) {
        setError("The current password is incorrect.");
      } else {
        setError(cause instanceof Error ? cause.message : "Could not save the new details.");
      }
      setBusy(false);
    }
  }

  return (
    <div
      className={styles.modalBg}
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onCancel();
      }}
    >
      <form
        className={styles.modal}
        role="dialog"
        aria-modal="true"
        aria-labelledby="creds-title"
        onSubmit={submit}
      >
        <h4 id="creds-title">Change username and password</h4>
        <p>Enter your current password, then choose the new details.</p>

        <div className={styles.field}>
          <label htmlFor="creds-user">Username</label>
          <input
            id="creds-user"
            ref={firstField}
            value={user}
            onChange={(e) => setUser(e.target.value)}
            autoComplete="username"
          />
        </div>

        <div className={styles.field}>
          <label htmlFor="creds-current">Current password</label>
          <input
            id="creds-current"
            type={reveal ? "text" : "password"}
            value={current}
            onChange={(e) => setCurrent(e.target.value)}
            autoComplete="current-password"
          />
        </div>

        <div className={styles.field}>
          <label htmlFor="creds-new">New password</label>
          <input
            id="creds-new"
            type={reveal ? "text" : "password"}
            value={next}
            onChange={(e) => setNext(e.target.value)}
            autoComplete="new-password"
          />
        </div>

        <ul className={styles.rules}>
          {rules.map((rule) => (
            <li key={rule.id} className={rule.ok ? styles.rulePass : ""}>
              {rule.label}
            </li>
          ))}
        </ul>

        <div className={styles.field}>
          <label htmlFor="creds-confirm">Confirm new password</label>
          <input
            id="creds-confirm"
            type={reveal ? "text" : "password"}
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
            autoComplete="new-password"
          />
        </div>

        <label className={styles.reveal}>
          <input
            type="checkbox"
            checked={reveal}
            onChange={(e) => setReveal(e.target.checked)}
          />
          Show passwords
        </label>

        <div className={styles.error} role="alert" aria-live="polite">
          {error}
        </div>

        <div className={styles.modalActions}>
          <button type="button" className={`${styles.btn} ${styles.ghost}`} onClick={onCancel}>
            Cancel
          </button>
          <button type="submit" className={`${styles.btn} ${styles.primary}`} disabled={busy}>
            {busy ? <span className={styles.spinner} /> : null}
            {busy ? "Saving…" : "Save"}
          </button>
        </div>
      </form>
    </div>
  );
}
