"use client";

import { useEffect, useMemo, useState } from "react";
import Image from "next/image";
import styles from "./admin.module.css";
import SignIn from "@/components/admin/SignIn";
import ConfirmDialog from "@/components/admin/ConfirmDialog";
import FileTable from "@/components/admin/FileTable";
import SelectionToolbar from "@/components/admin/SelectionToolbar";
import UploadDrop from "@/components/admin/UploadDrop";
import ChangeCredentialsDialog from "@/components/admin/ChangeCredentialsDialog";
import { KeyIcon, SignOutIcon } from "@/components/admin/AdminIcons";
import { useAdminSession } from "@/hooks/use-admin-session";
import { useKbActions } from "@/hooks/use-kb-actions";

/**
 * What the file picker offers, kept in step by hand with the backend's
 * SUPPORTED_SUFFIXES (server/rag/documents.py). Widen both together - a file the
 * picker accepts but the ingester cannot read comes back as a 422.
 */
const ACCEPT = ".md,.markdown,.txt,.pdf,.docx,.xlsx,.xlsm,.csv,.tsv";

/** The files a delete confirmation is waiting on, or null when none is open. */
type PendingDelete = string[] | null;

export default function AdminPage() {
  const session = useAdminSession();
  const actions = useKbActions(session.creds, session.refresh);

  const [selected, setSelected] = useState<ReadonlySet<string>>(new Set());
  const [pendingDelete, setPendingDelete] = useState<PendingDelete>(null);
  const [changingCredentials, setChangingCredentials] = useState(false);

  // Drop any selected name whose file is gone, so the toolbar's count can never
  // outlive the rows it refers to.
  useEffect(() => {
    const present = new Set(session.files.map((file) => file.name));
    setSelected((previous) => {
      const kept = [...previous].filter((name) => present.has(name));
      return kept.length === previous.size ? previous : new Set(kept);
    });
  }, [session.files]);

  // Clear the toast on a timer, restarted whenever a new one replaces it.
  useEffect(() => {
    if (!actions.note) return;
    const timer = setTimeout(actions.dismissNote, 4000);
    return () => clearTimeout(timer);
  }, [actions.note, actions.dismissNote]);

  const selectedNames = useMemo(() => [...selected], [selected]);

  function toggle(name: string) {
    setSelected((previous) => {
      const next = new Set(previous);
      if (!next.delete(name)) next.add(name);
      return next;
    });
  }

  async function confirmDelete() {
    if (!pendingDelete) return;
    const names = pendingDelete;
    setPendingDelete(null);
    await actions.remove(names);
    setSelected(new Set());
  }

  if (session.restoring) return <div className={styles.page} />;

  if (!session.creds) {
    return (
      <div className={styles.page}>
        <SignIn onSignedIn={session.signIn} />
      </div>
    );
  }

  const isBusy = actions.busy !== "";

  return (
    <div className={styles.page}>
      <header className={styles.topbar}>
        <Image
          className={styles.topbarLogo}
          src="/mari-logo.png"
          alt="Mari Energies"
          width={413}
          height={380}
          priority
        />
        <span className={styles.topbarTitle}>Kiosk Admin</span>
        <div className={styles.spacer} />
        <button
          type="button"
          className={`${styles.btn} ${styles.clear} ${styles.small}`}
          onClick={() => setChangingCredentials(true)}
        >
          <KeyIcon />
          Change password
        </button>
        <button
          type="button"
          className={`${styles.btn} ${styles.primary} ${styles.small}`}
          onClick={session.signOut}
        >
          <SignOutIcon />
          Sign out
        </button>
      </header>

      <main className={styles.content}>
        <div className={styles.intro}>
          <h2>Kiosk Control Panel</h2>
        </div>

        <section className={styles.card}>
          <div className={styles.cardHead}>
            <h3>Knowledge base files</h3>
            <p>
              The kiosk answers visitors&rsquo; questions using these documents. Add a file to
              teach it something new; delete a file to make it forget.
            </p>
          </div>

          <UploadDrop
            accept={ACCEPT}
            disabled={isBusy}
            onFiles={(files) => void actions.upload(files)}
          />

          <div className={styles.label}>Files on the kiosk</div>

          <SelectionToolbar
            selectedCount={selectedNames.length}
            totalCount={session.files.length}
            disabled={isBusy}
            onClear={() => setSelected(new Set())}
            onDownload={() => void actions.download(selectedNames)}
            onDelete={() => setPendingDelete(selectedNames)}
          />

          <FileTable
            files={session.files}
            loading={session.loading}
            selected={selected}
            onToggle={toggle}
            onToggleAll={(checked) =>
              setSelected(checked ? new Set(session.files.map((f) => f.name)) : new Set())
            }
          />

          {session.error ? (
            <div className={styles.error} role="alert">
              {session.error}
            </div>
          ) : null}
        </section>
      </main>

      {pendingDelete ? (
        <ConfirmDialog
          title={`Delete ${pendingDelete.length} file${pendingDelete.length === 1 ? "" : "s"}?`}
          message="The kiosk will stop using these files to answer questions. This cannot be undone."
          items={pendingDelete}
          confirmLabel="Yes, delete"
          destructive
          onConfirm={() => void confirmDelete()}
          onCancel={() => setPendingDelete(null)}
        />
      ) : null}

      {changingCredentials ? (
        <ChangeCredentialsDialog
          creds={session.creds}
          onSaved={(next) => {
            setChangingCredentials(false);
            session.replaceCredentials(next);
          }}
          onCancel={() => setChangingCredentials(false)}
        />
      ) : null}

      {isBusy ? (
        <div className={styles.toast} role="status">
          <span className={styles.spinner} /> {actions.busy}
        </div>
      ) : actions.note ? (
        <div
          className={`${styles.toast} ${actions.note.isError ? styles.toastError : ""}`}
          role="status"
        >
          {actions.note.text}
        </div>
      ) : null}
    </div>
  );
}
