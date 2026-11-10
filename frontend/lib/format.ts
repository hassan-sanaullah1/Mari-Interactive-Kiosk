/** Human-readable sizes and dates for the admin panel's file table. */

/**
 * Bytes as the operator would say them. Decimal units (KB = 1000) rather than binary,
 * to match what the file manager they uploaded from shows.
 */
export function formatSize(bytes: number): string {
  if (bytes < 1000) return `${bytes} B`;
  if (bytes < 1000 * 1000) return `${(bytes / 1000).toFixed(1)} KB`;
  return `${(bytes / 1000 / 1000).toFixed(1)} MB`;
}

/**
 * A modification time as a short absolute date.
 *
 * Absolute rather than "2 days ago": the panel's job is to tell the operator which
 * copy of a document the kiosk is answering from, and a date can be checked against
 * the document itself.
 *
 * @param seconds Unix time in SECONDS, as the backend's `mtime` reports it.
 */
export function formatDate(seconds: number): string {
  return new Date(seconds * 1000).toLocaleDateString("en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
  });
}
