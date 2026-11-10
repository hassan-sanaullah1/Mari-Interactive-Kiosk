"use client";

import styles from "@/app/admin/admin.module.css";
import { DownloadIcon, TrashIcon } from "./AdminIcons";

type Props = {
  selectedCount: number;
  totalCount: number;
  disabled: boolean;
  onClear: () => void;
  onDownload: () => void;
  onDelete: () => void;
};

/** The bar above the file table: what is selected, and what can be done with it. */
export default function SelectionToolbar({
  selectedCount,
  totalCount,
  disabled,
  onClear,
  onDownload,
  onDelete,
}: Props) {
  const some = selectedCount > 0;
  const plural = selectedCount === 1 ? "" : "s";

  return (
    <div className={styles.toolbar}>
      <span className={styles.selText}>
        {some ? (
          <>
            <b>{selectedCount}</b> of {totalCount} selected
          </>
        ) : (
          "No files selected"
        )}
      </span>
      {some ? null : (
        <span className={styles.hint}>
          Tick the boxes next to files you want to download or delete.
        </span>
      )}

      <div className={styles.spacer} />

      {some ? (
        <button type="button" className={`${styles.btn} ${styles.clear} ${styles.small}`} onClick={onClear}>
          Clear selection
        </button>
      ) : null}

      <button
        type="button"
        className={`${styles.btn} ${styles.primary} ${styles.small}`}
        disabled={!some || disabled}
        onClick={onDownload}
      >
        <DownloadIcon />
        {some ? `Download ${selectedCount} file${plural}` : "Download selected"}
      </button>

      <button
        type="button"
        className={`${styles.btn} ${styles.danger} ${styles.small}`}
        disabled={!some || disabled}
        onClick={onDelete}
      >
        <TrashIcon />
        {some ? `Delete ${selectedCount} file${plural}` : "Delete selected"}
      </button>
    </div>
  );
}
