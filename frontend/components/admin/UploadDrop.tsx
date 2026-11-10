"use client";

import { useRef, useState } from "react";
import styles from "@/app/admin/admin.module.css";
import { DropIcon, UploadIcon } from "./AdminIcons";

type Props = {
  /** Extensions the server accepts, as an accept attribute (e.g. ".md,.markdown"). */
  accept: string;
  disabled: boolean;
  onFiles: (files: File[]) => void;
};

/** Click-or-drag upload target. */
export default function UploadDrop({ accept, disabled, onFiles }: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);

  function hand(list: FileList | null) {
    const files = Array.from(list ?? []);
    if (files.length > 0) onFiles(files);
  }

  return (
    <div
      className={`${styles.drop} ${over ? styles.dropOver : ""}`}
      onDragEnter={(e) => {
        e.preventDefault();
        if (!disabled) setOver(true);
      }}
      // Without preventDefault on dragOver the browser treats the page as a
      // non-target and opens the dropped file instead of firing onDrop.
      onDragOver={(e) => {
        e.preventDefault();
        if (!disabled) setOver(true);
      }}
      onDragLeave={(e) => {
        e.preventDefault();
        setOver(false);
      }}
      onDrop={(e) => {
        e.preventDefault();
        setOver(false);
        if (!disabled) hand(e.dataTransfer.files);
      }}
    >
      <DropIcon className={styles.dropIcon} />
      <div>
        <b>Drag files here, or click the button to choose them</b>
      </div>

      <input
        ref={inputRef}
        type="file"
        className={styles.fileInput}
        accept={accept}
        multiple
        disabled={disabled}
        onChange={(e) => {
          hand(e.target.files);
          // Clear it, so choosing the same filename twice in a row still fires
          // onChange the second time.
          e.target.value = "";
        }}
      />
      <button
        type="button"
        className={`${styles.btn} ${styles.accent}`}
        disabled={disabled}
        onClick={() => inputRef.current?.click()}
      >
        <UploadIcon />
        Upload files
      </button>
    </div>
  );
}
