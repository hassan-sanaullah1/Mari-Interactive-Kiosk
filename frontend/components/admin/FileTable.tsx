"use client";

import styles from "@/app/admin/admin.module.css";
import { FileIcon } from "./AdminIcons";
import { formatDate, formatSize } from "@/lib/format";
import type { KbFile } from "@/lib/admin-api";

type Props = {
  files: KbFile[];
  loading: boolean;
  /** Names currently ticked. */
  selected: ReadonlySet<string>;
  onToggle: (name: string) => void;
  onToggleAll: (checked: boolean) => void;
};

/** The corpus as a table, with a checkbox column driving the toolbar's bulk actions. */
export default function FileTable({ files, loading, selected, onToggle, onToggleAll }: Props) {
  const allChecked = files.length > 0 && selected.size === files.length;

  return (
    <div className={styles.tableWrap}>
      <table className={styles.table}>
        <thead>
          <tr>
            <th className={styles.checkCol}>
              <input
                type="checkbox"
                className={styles.check}
                checked={allChecked}
                disabled={files.length === 0}
                // Indeterminate is not an attribute, only a DOM property, so it has
                // to be set on the node itself rather than through JSX.
                ref={(node) => {
                  if (node) node.indeterminate = selected.size > 0 && !allChecked;
                }}
                onChange={(e) => onToggleAll(e.target.checked)}
                aria-label="Select all files"
              />
            </th>
            <th>File name</th>
            <th>Size</th>
            <th>Added</th>
          </tr>
        </thead>
        <tbody>
          {loading ? (
            <tr>
              <td colSpan={4} className={styles.empty}>
                <span className={styles.spinner} /> Loading…
              </td>
            </tr>
          ) : files.length === 0 ? (
            <tr>
              <td colSpan={4} className={styles.empty}>
                No files yet. Upload one above to get started.
              </td>
            </tr>
          ) : (
            files.map((file) => {
              const isSelected = selected.has(file.name);
              return (
                <tr
                  key={file.name}
                  className={`${styles.row} ${isSelected ? styles.rowSelected : ""}`}
                  onClick={() => onToggle(file.name)}
                >
                  <td className={styles.checkCol}>
                    <input
                      type="checkbox"
                      className={styles.check}
                      checked={isSelected}
                      // The row's own handler toggles it; without this React warns
                      // about a controlled input with no onChange.
                      onChange={() => onToggle(file.name)}
                      onClick={(e) => e.stopPropagation()}
                      aria-label={`Select ${file.name}`}
                    />
                  </td>
                  <td>
                    <span className={styles.fileName}>
                      <FileIcon className={styles.fileIcon} />
                      {file.name}
                    </span>
                  </td>
                  <td>{formatSize(file.size)}</td>
                  <td>{formatDate(file.mtime)}</td>
                </tr>
              );
            })
          )}
        </tbody>
      </table>
    </div>
  );
}
