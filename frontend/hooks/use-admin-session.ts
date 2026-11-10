"use client";

import { useCallback, useEffect, useState } from "react";
import { listFiles, type Credentials, type KbFile } from "@/lib/admin-api";

/** Where the password is held between page loads. */
const STORAGE_KEY = "mari-admin-credentials";

export type AdminSession = {
  /** The signed-in credentials, or null when signed out. */
  creds: Credentials | null;
  /**
   * True until the stored session has been checked. The page renders nothing
   * meanwhile: showing the sign-in screen first makes it flash on every reload.
   */
  restoring: boolean;
  files: KbFile[];
  loading: boolean;
  /** Set when listing the corpus failed, so the page can report it. */
  error: string;
  signIn: (creds: Credentials) => void;
  /** Replace the stored credentials after the operator changes them. */
  replaceCredentials: (creds: Credentials) => void;
  signOut: () => void;
  /** Re-list the corpus. Call after anything that changes it. */
  refresh: () => Promise<void>;
};

/**
 * Holds the admin panel's session and its copy of the corpus listing.
 *
 * The credentials live in sessionStorage rather than localStorage: on a shared office
 * PC the password should not outlive the browser session. Every storage access is
 * wrapped — a locked-down browser throws on access rather than returning null, and a
 * blocked store should cost the operator a re-login, not a blank page.
 */
export function useAdminSession(): AdminSession {
  const [creds, setCreds] = useState<Credentials | null>(null);
  const [restoring, setRestoring] = useState(true);
  const [files, setFiles] = useState<KbFile[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    try {
      const raw = sessionStorage.getItem(STORAGE_KEY);
      if (raw) setCreds(JSON.parse(raw) as Credentials);
    } catch {
      // Nothing stored, or storage is blocked: sign in again.
    }
    setRestoring(false);
  }, []);

  const refresh = useCallback(async () => {
    if (!creds) return;
    setLoading(true);
    try {
      setFiles(await listFiles(creds));
      setError("");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not list the files.");
    } finally {
      setLoading(false);
    }
  }, [creds]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const signIn = useCallback((active: Credentials) => {
    try {
      sessionStorage.setItem(STORAGE_KEY, JSON.stringify(active));
    } catch {
      // Storage blocked: the session works, it just will not survive a reload.
    }
    setCreds(active);
  }, []);

  // Changing the password invalidates the old one immediately, so the live session
  // has to switch to the new pair or the next request would 401.
  const replaceCredentials = useCallback((next: Credentials) => {
    try {
      sessionStorage.setItem(STORAGE_KEY, JSON.stringify(next));
    } catch {
      // Storage blocked: the session works until the tab is closed.
    }
    setCreds(next);
  }, []);

  const signOut = useCallback(() => {
    try {
      sessionStorage.removeItem(STORAGE_KEY);
    } catch {
      // Nothing stored to clear.
    }
    setCreds(null);
    setFiles([]);
    setError("");
  }, []);

  return { creds, restoring, files, loading, error, signIn, replaceCredentials, signOut, refresh };
}
