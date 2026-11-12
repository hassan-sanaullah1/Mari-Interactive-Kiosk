"use client";

import { useEffect, useState } from "react";
import styles from "@/app/admin/admin.module.css";
import { fetchFileBlob, type Credentials } from "@/lib/admin-api";

type Props = {
  creds: Credentials;
  name: string;
  onClose: () => void;
  /** Save the file instead, for formats with nothing to show. */
  onDownload: (name: string) => void;
};

/** One spreadsheet sheet, as rows of already-stringified cells. */
type Sheet = { name: string; rows: string[][] };

type Loaded =
  | { kind: "text"; text: string }
  | { kind: "sheets"; sheets: Sheet[] }
  | { kind: "html"; html: string }
  | { kind: "pdf"; url: string }
  | { kind: "unsupported" };

const extensionOf = (name: string) => name.slice(name.lastIndexOf(".")).toLowerCase();

/**
 * Reads one file into something the browser can actually show.
 *
 * The parsers are imported lazily, inside this function rather than at module scope:
 * exceljs and mammoth are large, and the admin page should not carry them in its
 * first-load bundle for the common case where nobody opens a preview.
 */
async function load(blob: Blob, name: string): Promise<Loaded> {
  const extension = extensionOf(name);

  if ([".md", ".markdown", ".txt", ".csv", ".tsv"].includes(extension)) {
    return { kind: "text", text: await blob.text() };
  }

  if (extension === ".pdf") {
    // Browsers render PDFs natively; an object URL is all this needs.
    return { kind: "pdf", url: URL.createObjectURL(blob) };
  }

  if (extension === ".docx") {
    const mammoth = await import("mammoth");
    const { value } = await mammoth.convertToHtml({ arrayBuffer: await blob.arrayBuffer() });
    return { kind: "html", html: value };
  }

  if (extension === ".xlsx" || extension === ".xlsm") {
    const ExcelJS = (await import("exceljs")).default;
    const workbook = new ExcelJS.Workbook();
    await workbook.xlsx.load(await blob.arrayBuffer());
    const sheets: Sheet[] = [];
    workbook.eachSheet((worksheet) => {
      const rows: string[][] = [];
      worksheet.eachRow((row) => {
        const cells: string[] = [];
        // `row.values` is 1-based with a leading hole, so read by index instead.
        for (let column = 1; column <= worksheet.columnCount; column += 1) {
          cells.push(cellText(row.getCell(column).value));
        }
        rows.push(cells);
      });
      sheets.push({ name: worksheet.name, rows });
    });
    return { kind: "sheets", sheets };
  }

  return { kind: "unsupported" };
}

/** A cell as the operator would read it, whatever exceljs stored in it. */
function cellText(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (value instanceof Date) return value.toLocaleDateString("en-GB");
  if (typeof value === "object") {
    const cell = value as { result?: unknown; text?: unknown; richText?: { text: string }[] };
    // A formula cell carries its cached result; a hyperlink or rich text carries text.
    if (cell.result !== undefined) return String(cell.result);
    if (Array.isArray(cell.richText)) return cell.richText.map((part) => part.text).join("");
    if (cell.text !== undefined) return String(cell.text);
    return "";
  }
  return String(value);
}

/**
 * Shows one knowledge-base file without leaving the page.
 *
 * Everything is parsed in the browser from the bytes the panel already downloads, so
 * no new server route is involved. Office formats have no native browser viewer,
 * which is why they need the two parsers rather than being handed to the browser.
 */
export default function FilePreview({ creds, name, onClose, onDownload }: Props) {
  const [loaded, setLoaded] = useState<Loaded | null>(null);
  const [error, setError] = useState("");
  const [activeSheet, setActiveSheet] = useState(0);

  useEffect(() => {
    let cancelled = false;
    let objectUrl: string | null = null;

    (async () => {
      try {
        const result = await load(await fetchFileBlob(creds, name), name);
        if (result.kind === "pdf") objectUrl = result.url;
        // The panel may have been closed while the file was parsing.
        if (cancelled) {
          if (objectUrl) URL.revokeObjectURL(objectUrl);
          return;
        }
        setLoaded(result);
      } catch (cause) {
        if (!cancelled) {
          setError(cause instanceof Error ? cause.message : `Could not open ${name}.`);
        }
      }
    })();

    return () => {
      cancelled = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [creds, name]);

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") onClose();
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div
      className={styles.previewBg}
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className={styles.preview} role="dialog" aria-modal="true" aria-label={`Preview of ${name}`}>
        <header className={styles.previewHead}>
          <span className={styles.previewName}>{name}</span>
          <div className={styles.spacer} />
          <button
            type="button"
            className={`${styles.btn} ${styles.clear} ${styles.small}`}
            onClick={() => onDownload(name)}
          >
            Download
          </button>
          <button
            type="button"
            className={`${styles.btn} ${styles.ghost} ${styles.small}`}
            onClick={onClose}
          >
            Close
          </button>
        </header>

        <div className={styles.previewBody}>
          {error ? (
            <p className={styles.error} role="alert">
              {error}
            </p>
          ) : !loaded ? (
            <p className={styles.previewNote}>
              <span className={styles.spinner} /> Opening…
            </p>
          ) : loaded.kind === "text" ? (
            <pre className={styles.previewText}>{loaded.text}</pre>
          ) : loaded.kind === "pdf" ? (
            <iframe className={styles.previewFrame} src={loaded.url} title={name} />
          ) : loaded.kind === "html" ? (
            // mammoth emits a fixed, small set of formatting tags from the document's
            // own content; it does not carry script through.
            <div
              className={styles.previewDoc}
              dangerouslySetInnerHTML={{ __html: loaded.html }}
            />
          ) : loaded.kind === "sheets" ? (
            <>
              {loaded.sheets.length > 1 ? (
                <div className={styles.sheetTabs}>
                  {loaded.sheets.map((sheet, index) => (
                    <button
                      key={sheet.name}
                      type="button"
                      className={`${styles.sheetTab} ${index === activeSheet ? styles.sheetTabActive : ""}`}
                      onClick={() => setActiveSheet(index)}
                    >
                      {sheet.name}
                    </button>
                  ))}
                </div>
              ) : null}
              <SheetTable sheet={loaded.sheets[activeSheet]} />
            </>
          ) : (
            <p className={styles.previewNote}>
              This file type cannot be shown here. Use Download to open it.
            </p>
          )}
        </div>
      </div>
    </div>
  );
}

/** The first row is treated as the header, which is how these corpus files are written. */
function SheetTable({ sheet }: { sheet: Sheet | undefined }) {
  if (!sheet || sheet.rows.length === 0) {
    return <p className={styles.previewNote}>This sheet is empty.</p>;
  }
  const [header, ...body] = sheet.rows;
  return (
    <div className={styles.sheetWrap}>
      <table className={styles.sheet}>
        <thead>
          <tr>
            {header.map((cell, index) => (
              <th key={index}>{cell}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {body.map((row, rowIndex) => (
            <tr key={rowIndex}>
              {row.map((cell, cellIndex) => (
                <td key={cellIndex}>{cell}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
