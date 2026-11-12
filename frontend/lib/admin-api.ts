/**
 * The admin panel's view of the knowledge-base API (server/admin.py).
 *
 * Calls go through Next's /api/admin/* rewrite to the backend's /upload/* routes, so
 * the browser stays same-origin and the backend needs no CORS handling. Credentials
 * travel as headers rather than a cookie: the backend is a plain token check with no
 * session store, and the panel is LAN-only.
 */

/** Where the rewrite in next.config.ts forwards admin calls to FastAPI. */
const BASE = "/api/admin";

/**
 * Next 15.5 truncates a proxied request body at 10 MB and has no setting to raise it,
 * so a larger upload reaches the backend as a corrupt fragment. Anything above this
 * is posted straight to FastAPI instead; everything else keeps using the same-origin
 * proxy, which needs no CORS.
 */
const PROXY_BODY_LIMIT = 8 * 1024 * 1024;

/**
 * The backend's own origin, for the uploads that cannot go through the proxy.
 *
 * Derived from the page's hostname rather than configured: the kiosk is reached by IP,
 * by mari-MS-7E44.local and by localhost, and the right answer is always "the same
 * host, port 8010". Mirrors how lib/endpoints.ts resolves the WebSocket.
 */
function backendOrigin(): string {
  const { protocol, hostname, port, host } = window.location;
  // Served by next dev/start on :3000 -> FastAPI is the separate process on :8010.
  // Any other origin -> assume one host in front of both.
  return port === "3000" ? `${protocol}//${hostname}:8010` : `${protocol}//${host}`;
}

/** What the operator typed on the sign-in screen. */
export type Credentials = {
  user: string;
  token: string;
};

/** One knowledge-base file, as the server lists it. */
export type KbFile = {
  name: string;
  /** Bytes on disk. */
  size: number;
  /** Last-modified time, in seconds since the epoch (not milliseconds). */
  mtime: number;
};

/** What `ingest_all()` reports after an upload or delete. */
export type IngestReport = {
  chunks?: number;
  duration_s?: number;
  /** Filename → reason, for files the ingester could not read. */
  failed?: Record<string, string>;
};

export type UploadResult = {
  saved: string;
  size: number;
  ingest?: IngestReport;
};

/**
 * A failed admin call, carrying the HTTP status so callers can tell "wrong password"
 * (401) from "the admin API is switched off" (503) or "that file could not be
 * converted" (422) without parsing the message.
 */
export class AdminError extends Error {
  readonly status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "AdminError";
    this.status = status;
  }
}

function authHeaders({ user, token }: Credentials): HeadersInit {
  // BOTH halves, on every request. The server compares each one and a missing header
  // fails the check outright - it does not fall back to the stored username, which is
  // what previously let a caller in on the password alone.
  return { "X-Admin-User": user, "X-Admin-Token": token };
}

/**
 * The backend reports errors as FastAPI's `{detail: {error: {code, message}}}`.
 * A proxy or a crash can return something else entirely, so fall back to the status
 * text rather than showing the operator "undefined".
 */
function errorMessage(body: unknown, fallback: string): string {
  if (typeof body === "object" && body !== null && "detail" in body) {
    const { detail } = body as { detail: unknown };
    if (typeof detail === "string") return detail;
    if (typeof detail === "object" && detail !== null && "error" in detail) {
      const { error } = detail as { error: unknown };
      if (typeof error === "object" && error !== null && "message" in error) {
        const { message } = error as { message: unknown };
        if (typeof message === "string") return message;
      }
    }
  }
  return fallback;
}

async function request<T>(path: string, creds: Credentials, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`${BASE}${path}`, {
    ...init,
    headers: { ...(init.headers ?? {}), ...authHeaders(creds) },
  });
  // Read as text first: an error from the proxy rather than the app may not be JSON,
  // and response.json() would throw over the real status code.
  const raw = await response.text();
  let body: unknown = null;
  if (raw) {
    try {
      body = JSON.parse(raw);
    } catch {
      body = { detail: raw.slice(0, 200) };
    }
  }
  if (!response.ok) {
    throw new AdminError(errorMessage(body, response.statusText), response.status);
  }
  return body as T;
}

/**
 * List the corpus. The sign-in screen also uses this to check the password: a 200
 * means it is good, so there is no separate login endpoint to keep in step.
 */
export async function listFiles(creds: Credentials): Promise<KbFile[]> {
  const body = await request<{ files: KbFile[] }>("/kb", creds);
  return body.files ?? [];
}

/**
 * Upload one file. The backend converts, chunks and embeds before replying, so a
 * resolved promise means the file is already searchable — there is no processing
 * state to poll for. A file the converter cannot read is removed again server-side
 * and reported as a 422.
 */
export async function uploadFile(creds: Credentials, file: File): Promise<UploadResult> {
  const form = new FormData();
  form.append("file", file, file.name);
  // Small files keep the same-origin proxy. A large one goes straight to the backend,
  // because the proxy would silently cut its body at 10 MB.
  const direct = file.size > PROXY_BODY_LIMIT;
  const url = direct ? `${backendOrigin()}/upload/kb` : `${BASE}/kb`;
  return sendUpload(url, creds, form);
}

/** POST a multipart body and read the same error shape `request` does. */
async function sendUpload(
  url: string,
  creds: Credentials,
  form: FormData,
): Promise<UploadResult> {
  const response = await fetch(url, {
    method: "POST",
    headers: authHeaders(creds),
    body: form,
  });
  const raw = await response.text();
  let body: unknown = null;
  if (raw) {
    try {
      body = JSON.parse(raw);
    } catch {
      body = { detail: raw.slice(0, 200) };
    }
  }
  if (!response.ok) {
    throw new AdminError(errorMessage(body, response.statusText), response.status);
  }
  return body as UploadResult;
}

export async function deleteFile(creds: Credentials, name: string): Promise<void> {
  await request(`/kb/${encodeURIComponent(name)}`, creds, { method: "DELETE" });
}

/** The file's bytes, for viewing or saving. */
export async function fetchFileBlob(creds: Credentials, name: string): Promise<Blob> {
  const response = await fetch(`${BASE}/kb/${encodeURIComponent(name)}`, {
    headers: authHeaders(creds),
  });
  if (!response.ok) {
    throw new AdminError(`Could not read ${name}`, response.status);
  }
  return response.blob();
}

/** The fields the change-credentials form sends. */
export type CredentialChange = {
  current_password: string;
  new_user: string;
  new_password: string;
};

/**
 * Change the sign-in username and password.
 *
 * The server requires the current password as well as the signed-in session, so a
 * browser left open on the kiosk cannot be used to lock the owner out. Once this
 * resolves the old password no longer works, so the caller must keep the new one.
 */
export async function setCredentials(
  creds: Credentials,
  change: CredentialChange,
): Promise<void> {
  await request("/credentials", creds, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(change),
  });
}
