"use client";

import { useState, type FormEvent } from "react";
import Image from "next/image";
import styles from "@/app/admin/admin.module.css";
import { AdminError, listFiles, type Credentials } from "@/lib/admin-api";

type Props = {
  /** Called with credentials the server has already accepted. */
  onSignedIn: (creds: Credentials) => void;
};

/**
 * The sign-in screen.
 *
 * There is no login endpoint: the panel authenticates by making the call it is about
 * to make anyway (list the corpus) and treating a 200 as proof. That keeps one
 * source of truth for "are these credentials good" — the same header check every
 * other route runs — instead of a second code path that can drift from it.
 */
export default function SignIn({ onSignedIn }: Props) {
  const [user, setUser] = useState("");
  const [token, setToken] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (busy) return;
    const creds = { user: user.trim(), token };
    if (!creds.user || !creds.token) {
      setError("Please enter your username and password.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      await listFiles(creds);
      onSignedIn(creds);
    } catch (cause) {
      // 503 means the server has no token configured, which the operator cannot fix
      // by retyping. Say so, rather than blaming their password.
      if (cause instanceof AdminError && cause.status === 503) {
        setError("The admin panel is switched off on the server (no password is set).");
      } else if (cause instanceof AdminError && cause.status === 401) {
        setError("Wrong username or password.");
      } else {
        setError(cause instanceof Error ? cause.message : "Could not reach the kiosk.");
      }
      setBusy(false);
    }
  }

  return (
    <div className={styles.login}>
      <div className={styles.hero}>
        {/* The wordmark under the 'M' is navy and grey, which all but disappears on
            this blue panel. This variant paints just that text white and leaves the
            mark's brand gradient alone; the topbar uses the normal logo on white. */}
        <Image
          className={styles.heroLogo}
          src="/mari-logo-white.png"
          alt="Mari Energies"
          width={413}
          height={380}
          priority
        />
        <div>
          <h1>Interactive Kiosk</h1>
          <p>Admin Console</p>
        </div>
      </div>

      <div className={styles.loginPanel}>
        <form className={styles.loginCard} onSubmit={submit}>
          <h2>Sign in</h2>

          <div className={styles.field}>
            <label htmlFor="admin-user">Username</label>
            <input
              id="admin-user"
              value={user}
              onChange={(e) => setUser(e.target.value)}
              autoComplete="username"
              autoFocus
            />
          </div>

          <div className={styles.field}>
            <label htmlFor="admin-pass">Password</label>
            <input
              id="admin-pass"
              type="password"
              value={token}
              onChange={(e) => setToken(e.target.value)}
              autoComplete="current-password"
            />
          </div>

          <button
            type="submit"
            className={`${styles.btn} ${styles.primary} ${styles.block}`}
            disabled={busy}
          >
            {busy ? <span className={styles.spinner} /> : null}
            {busy ? "Signing in…" : "Sign in"}
          </button>

          {/* aria-live so the failure is announced, not just shown. */}
          <div className={styles.error} role="alert" aria-live="polite">
            {error}
          </div>
        </form>
      </div>
    </div>
  );
}
