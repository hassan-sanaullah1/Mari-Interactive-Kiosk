"use client";

import { useCallback, useState } from "react";
import {
  AdminError,
  deleteFile,
  fetchFileBlob,
  uploadFile,
  type Credentials,
} from "@/lib/admin-api";

/** A transient message under the page: progress, success or failure. */
export type Note = { text: string; isError: boolean } | null;

export type KbActions = {
  /** Non-empty while an action is running; the text describes it. */
  busy: string;
  note: Note;
  dismissNote: () => void;
  upload: (files: File[]) => Promise<void>;
  remove: (names: string[]) => Promise<void>;
  download: (names: string[]) => Promise<void>;
};

function message(cause: unknown, fallback: string): string {
  return cause instanceof Error ? cause.message : fallback;
}

/** Hand the browser a blob to save under `name`. */
function saveBlob(blob: Blob, name: string): void {
  // A blob URL rather than linking at the API: the download needs the auth header,
  // which a plain <a href> cannot send.
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

/**
 * The operations the admin panel performs on the corpus, with the progress and
 * result messages they produce.
 *
 * Uploads and deletes run one at a time rather than in parallel: each one makes the
 * server re-index the whole corpus, so firing them together would have several
 * ingests competing for the same embedding service for no gain.
 *
 * @param creds  The signed-in credentials; actions are no-ops without them.
 * @param onChanged  Called after the corpus changes, to re-list it.
 */
export function useKbActions(
  creds: Credentials | null,
  onChanged: () => Promise<void>,
): KbActions {
  const [busy, setBusy] = useState("");
  const [note, setNote] = useState<Note>(null);

  const say = useCallback((text: string, isError = false) => {
    setNote({ text, isError });
  }, []);

  const dismissNote = useCallback(() => setNote(null), []);

  const upload = useCallback(
    async (chosen: File[]) => {
      if (!creds) return;
      let saved = 0;
      const failed: string[] = [];
      for (const file of chosen) {
        // Converting a PDF or a spreadsheet and re-embedding the corpus takes
        // seconds, so name the file being worked on rather than a bare spinner.
        setBusy(`Uploading and indexing ${file.name}…`);
        try {
          await uploadFile(creds, file);
          saved += 1;
        } catch (cause) {
          // 422 is the backend rejecting a file it could not read; it has already
          // removed it again, so the corpus is unchanged.
          const why =
            cause instanceof AdminError && cause.status === 422
              ? `could not be read: ${cause.message}`
              : message(cause, "upload failed");
          failed.push(`${file.name} (${why})`);
        }
      }
      setBusy("");
      await onChanged();
      if (failed.length === 0) say(`${saved} file${saved === 1 ? "" : "s"} uploaded and indexed.`);
      else if (saved === 0) say(`Could not upload ${failed.join("; ")}`, true);
      else say(`${saved} uploaded. Could not upload ${failed.join("; ")}`, true);
    },
    [creds, onChanged, say],
  );

  const remove = useCallback(
    async (names: string[]) => {
      if (!creds) return;
      setBusy(`Deleting ${names.length} file${names.length === 1 ? "" : "s"}…`);
      const failed: string[] = [];
      for (const name of names) {
        try {
          await deleteFile(creds, name);
        } catch {
          failed.push(name);
        }
      }
      setBusy("");
      await onChanged();
      if (failed.length > 0) say(`Could not delete: ${failed.join(", ")}`, true);
      else say(`${names.length} file${names.length === 1 ? "" : "s"} deleted.`);
    },
    [creds, onChanged, say],
  );

  const download = useCallback(
    async (names: string[]) => {
      if (!creds) return;
      setBusy(`Preparing ${names.length} file${names.length === 1 ? "" : "s"}…`);
      const failed: string[] = [];
      for (const name of names) {
        try {
          saveBlob(await fetchFileBlob(creds, name), name);
        } catch {
          failed.push(name);
        }
      }
      setBusy("");
      if (failed.length > 0) say(`Could not download: ${failed.join(", ")}`, true);
    },
    [creds, say],
  );

  return { busy, note, dismissNote, upload, remove, download };
}
