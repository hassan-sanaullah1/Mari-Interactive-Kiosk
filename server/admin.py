"""Admin KB endpoints: list / upload / download / delete files in the RAG corpus.

LAN-only by convention — the frontend container is on 0.0.0.0:3000 and this backend
is on 0.0.0.0:8010, both reachable from any PC on the Wi-Fi. A shared-secret header
(X-Admin-Token, env MARI_ADMIN_TOKEN) gates every route. If the env is empty, the
endpoints return 503: no token → closed.

Uploaded files land in the corpus directory and are ingested in-process, reusing the
same QdrantStore + EmbeddingService the running retriever already warmed. No restart.
"""

from __future__ import annotations

import hmac
import logging
import os
import uuid
from pathlib import Path

from fastapi import APIRouter, Header, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

from .rag.ingestion import IngestionService
from .rag.retriever import get_retriever
from .rag.settings import get_settings

logger = logging.getLogger(__name__)

router = APIRouter()

_ALLOWED_SUFFIXES = {".md", ".markdown"}
_MAX_BYTES = 5 * 1024 * 1024  # 5 MB per file


def _check_token(provided: str | None) -> None:
    expected = os.environ.get("MARI_ADMIN_TOKEN", "")
    if not expected:
        raise HTTPException(status_code=503, detail={"error": {"code": "admin_disabled", "message": "MARI_ADMIN_TOKEN is not set on the server"}})
    if not provided or not hmac.compare_digest(expected, provided):
        raise HTTPException(status_code=401, detail={"error": {"code": "unauthorized", "message": "bad or missing admin token"}})


def _safe_target(filename: str, corpus_dir: Path) -> Path:
    name = Path(filename).name  # strip any path components
    if not name or name.startswith(".") or name in {"README.md", "sky47_knowledge_base.md"}:
        raise HTTPException(status_code=400, detail={"error": {"code": "bad_name", "message": f"filename {name!r} not allowed"}})
    if Path(name).suffix.lower() not in _ALLOWED_SUFFIXES:
        raise HTTPException(status_code=400, detail={"error": {"code": "bad_type", "message": "only .md / .markdown files are accepted"}})
    target = (corpus_dir / name).resolve()
    if corpus_dir.resolve() not in target.parents and target.parent != corpus_dir.resolve():
        raise HTTPException(status_code=400, detail={"error": {"code": "bad_path", "message": "path escapes corpus directory"}})
    return target


async def _reingest() -> dict:
    """Reuse the running retriever's store + embedding service so no models are reloaded."""
    settings = get_settings()
    retriever = await get_retriever(settings)
    service = IngestionService(retriever.store, retriever.embedding, settings=settings)
    report = await service.ingest_all()
    return report.as_dict()


@router.get("/upload/logo.png")
async def admin_logo() -> FileResponse:
    """The Mari Energies logo shown on the admin page header."""
    path = Path(__file__).parent / "static" / "mari-logo.png"
    return FileResponse(path, media_type="image/png")


@router.get("/upload", response_class=HTMLResponse)
async def admin_page() -> HTMLResponse:
    """Password form on first load; the page itself fetches the file list with the token."""
    return HTMLResponse(_PAGE_HTML)


@router.get("/upload/kb")
async def admin_list(x_admin_token: str | None = Header(default=None)) -> JSONResponse:
    _check_token(x_admin_token)
    settings = get_settings()
    corpus_dir: Path = settings.corpus_dir
    corpus_dir.mkdir(parents=True, exist_ok=True)
    files = []
    for p in sorted(corpus_dir.iterdir()):
        if p.is_file() and not p.name.startswith(".") and p.suffix.lower() in _ALLOWED_SUFFIXES:
            if p.name in {"README.md", "sky47_knowledge_base.md"}:
                continue
            st = p.stat()
            files.append({"name": p.name, "size": st.st_size, "mtime": int(st.st_mtime)})
    return JSONResponse({"files": files, "corpus_dir": str(corpus_dir)})


@router.get("/upload/kb/{name}")
async def admin_get(name: str, x_admin_token: str | None = Header(default=None)) -> FileResponse:
    _check_token(x_admin_token)
    settings = get_settings()
    target = _safe_target(name, settings.corpus_dir)
    if not target.exists():
        raise HTTPException(status_code=404, detail={"error": {"code": "not_found", "message": f"{name} not in corpus"}})
    return FileResponse(target, media_type="text/markdown", filename=target.name)


@router.post("/upload/kb")
async def admin_upload(request: Request, file: UploadFile, x_admin_token: str | None = Header(default=None)) -> JSONResponse:
    _check_token(x_admin_token)
    settings = get_settings()
    corpus_dir: Path = settings.corpus_dir
    corpus_dir.mkdir(parents=True, exist_ok=True)

    if not file.filename:
        raise HTTPException(status_code=400, detail={"error": {"code": "bad_name", "message": "missing filename"}})
    target = _safe_target(file.filename, corpus_dir)

    # Stream to a sibling temp file, then atomically rename. Avoids a half-written file
    # being discovered mid-ingest.
    tmp = corpus_dir / f".incoming-{uuid.uuid4().hex}.md"
    size = 0
    try:
        with tmp.open("wb") as fh:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > _MAX_BYTES:
                    raise HTTPException(status_code=413, detail={"error": {"code": "too_large", "message": f"max {_MAX_BYTES // 1024 // 1024} MB per file"}})
                fh.write(chunk)
        os.replace(tmp, target)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass

    logger.info("admin: uploaded %s (%d bytes)", target.name, size)
    report = await _reingest()
    return JSONResponse({"saved": target.name, "size": size, "ingest": report})


@router.delete("/upload/kb/{name}")
async def admin_delete(name: str, x_admin_token: str | None = Header(default=None)) -> JSONResponse:
    _check_token(x_admin_token)
    settings = get_settings()
    target = _safe_target(name, settings.corpus_dir)
    if not target.exists():
        raise HTTPException(status_code=404, detail={"error": {"code": "not_found", "message": f"{name} not in corpus"}})
    target.unlink()
    logger.info("admin: deleted %s", name)
    report = await _reingest()
    return JSONResponse({"deleted": name, "ingest": report})


_PAGE_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Mari Kiosk · Knowledge</title>
<style>
  :root {
    --blue: #0077dc;
    --blue-hover: #0f88ee;
    --blue-soft: rgba(0, 119, 220, 0.08);
    --surface: #f4f5f7;         /* page bg, kiosk light token */
    --surface-raised: #ffffff;   /* cards */
    --surface-sunken: #e3e5e9;   /* inputs, subtle wells */
    --surface-hover: #e8eaee;
    --text: #14161a;
    --text-dim: rgba(20, 22, 26, 0.6);
    --text-faint: rgba(20, 22, 26, 0.42);
    --border: rgba(20, 22, 26, 0.08);
    --border-strong: rgba(20, 22, 26, 0.18);
    --danger: #d32f2f;
    --danger-hover: #b92626;
    --danger-soft: rgba(211, 47, 47, 0.08);
    --ok: #2e7d32;
    --ok-soft: rgba(46, 125, 50, 0.08);
    --shadow-sm: 0 1px 2px rgba(20, 22, 26, 0.04), 0 1px 3px rgba(20, 22, 26, 0.06);
    --shadow-md: 0 4px 10px rgba(20, 22, 26, 0.06), 0 2px 4px rgba(20, 22, 26, 0.04);
    --shadow-lg: 0 20px 48px rgba(20, 22, 26, 0.18), 0 6px 14px rgba(20, 22, 26, 0.08);
    --radius: 16px;
    --radius-sm: 10px;
    --radius-pill: 999px;
  }
  * { box-sizing: border-box; }
  html, body { height: 100%; }
  body {
    margin: 0;
    font-family: "Inter", system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", sans-serif;
    font-size: 15px;
    line-height: 1.5;
    color: var(--text);
    background: var(--surface);
    -webkit-font-smoothing: antialiased;
    -moz-osx-font-smoothing: grayscale;
  }
  .wrap { max-width: 820px; margin: 0 auto; padding: 40px 24px 80px; }

  /* Header */
  .header { display: flex; align-items: center; gap: 14px; margin-bottom: 8px; }
  .logo {
    width: 48px; height: 48px; border-radius: 12px;
    background: #ffffff;
    border: 1px solid var(--border);
    padding: 6px;
    display: flex; align-items: center; justify-content: center;
    box-shadow: var(--shadow-sm);
    flex-shrink: 0;
  }
  .logo img { width: 100%; height: 100%; object-fit: contain; display: block; image-rendering: -webkit-optimize-contrast; }
  .header h1 { margin: 0; font-size: 22px; font-weight: 600; letter-spacing: -0.01em; }
  .header .sub { margin: 2px 0 0; color: var(--text-dim); font-size: 13px; }

  /* Cards */
  .card {
    background: var(--surface-raised);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 24px;
    margin-top: 20px;
    box-shadow: var(--shadow-sm);
  }
  .card-title { display: flex; align-items: center; justify-content: space-between; margin-bottom: 14px; }
  .card-title h2 { margin: 0; font-size: 15px; font-weight: 600; color: var(--text); letter-spacing: -0.005em; }
  .card-title .hint { color: var(--text-faint); font-size: 12px; }

  /* Form */
  label.field-label { display: block; font-size: 13px; color: var(--text-dim); margin-bottom: 8px; font-weight: 500; }
  input[type=password], input[type=text] {
    width: 100%; padding: 12px 14px;
    background: var(--surface-raised);
    border: 1px solid var(--border-strong);
    border-radius: var(--radius-sm);
    color: var(--text); font: inherit;
    transition: border-color 160ms ease, box-shadow 160ms ease;
  }
  input[type=password]:focus, input[type=text]:focus {
    outline: none; border-color: var(--blue);
    box-shadow: 0 0 0 3px var(--blue-soft);
  }

  /* Buttons */
  button {
    padding: 10px 18px;
    background: var(--blue); color: #fff;
    border: 0; border-radius: var(--radius-pill);
    font: inherit; font-weight: 600; font-size: 14px;
    cursor: pointer;
    transition: background 160ms ease, transform 80ms ease, box-shadow 160ms ease;
    display: inline-flex; align-items: center; gap: 6px;
  }
  button:hover:not(:disabled) { background: var(--blue-hover); }
  button:active:not(:disabled) { transform: translateY(1px); }
  button:disabled { opacity: 0.4; cursor: not-allowed; }
  button.ghost {
    background: var(--surface-sunken); color: var(--text);
    border: 1px solid var(--border-strong);
    font-weight: 500;
  }
  button.ghost:hover:not(:disabled) { background: var(--surface-hover); }
  button.danger { background: var(--danger); }
  button.danger:hover:not(:disabled) { background: var(--danger-hover); }
  button.small { padding: 6px 12px; font-size: 13px; }

  /* Drop zone */
  .drop {
    display: flex; flex-direction: column; align-items: center; justify-content: center;
    gap: 6px;
    border: 2px dashed var(--border-strong);
    border-radius: var(--radius);
    padding: 36px 24px;
    text-align: center; color: var(--text-dim);
    cursor: pointer;
    transition: border-color 160ms ease, background 160ms ease, color 160ms ease;
  }
  .drop:hover { border-color: var(--blue); color: var(--text); background: var(--blue-soft); }
  .drop.hover { border-color: var(--blue); background: var(--blue-soft); color: var(--text); }
  .drop input { display: none; }
  .drop-icon { font-size: 28px; line-height: 1; color: var(--blue); margin-bottom: 4px; }
  .drop-main { font-weight: 600; font-size: 15px; color: var(--text); }
  .drop-sub { font-size: 12px; color: var(--text-faint); }

  /* Toolbar above the file list */
  .bulkbar {
    display: flex; align-items: center; gap: 12px;
    padding: 10px 14px;
    background: var(--surface-sunken);
    border-radius: var(--radius-sm);
    margin-bottom: 10px;
    font-size: 13px; color: var(--text-dim);
  }
  .bulkbar.hidden { display: none; }
  .hidden { display: none !important; }
  .bulkbar label { display: flex; align-items: center; gap: 8px; cursor: pointer; color: var(--text); font-weight: 500; }
  .bulkbar .count { color: var(--blue); font-weight: 600; }

  /* File rows */
  .list { display: flex; flex-direction: column; }
  .row {
    display: flex; align-items: center; gap: 12px;
    padding: 12px 14px;
    border-radius: var(--radius-sm);
    transition: background 120ms ease;
  }
  .row:hover { background: var(--surface-sunken); }
  .row .pick { display: flex; align-items: center; gap: 12px; flex: 1; min-width: 0; cursor: pointer; }
  .row input[type=checkbox] {
    width: 18px; height: 18px; cursor: pointer; accent-color: var(--blue);
    flex-shrink: 0;
  }
  .file-icon {
    width: 36px; height: 36px; flex-shrink: 0;
    border-radius: 9px;
    background: var(--blue-soft);
    color: var(--blue);
    display: flex; align-items: center; justify-content: center;
    font-size: 12px; font-weight: 700; letter-spacing: 0.5px;
  }
  .file-info { min-width: 0; flex: 1; }
  .file-name { font-weight: 600; font-size: 14px; color: var(--text); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .file-meta { color: var(--text-faint); font-size: 12px; margin-top: 2px; }
  .file-actions { display: flex; gap: 8px; flex-shrink: 0; }
  .empty {
    text-align: center; color: var(--text-faint); padding: 32px 16px;
    font-size: 14px;
  }

  /* Messages */
  .msg {
    margin-top: 14px;
    padding: 12px 14px;
    border-radius: var(--radius-sm);
    font-size: 13px;
    display: flex; align-items: center; gap: 8px;
  }
  .msg.ok { background: var(--ok-soft); color: var(--ok); border: 1px solid rgba(46, 125, 50, 0.18); }
  .msg.err { background: var(--danger-soft); color: var(--danger); border: 1px solid rgba(211, 47, 47, 0.18); }
  .msg.hidden { display: none; }
  .msg b { color: inherit; font-weight: 700; }

  /* Modal */
  .mask {
    position: fixed; inset: 0;
    background: rgba(20, 22, 26, 0.5);
    backdrop-filter: blur(4px);
    display: flex; align-items: center; justify-content: center;
    z-index: 50;
    animation: fadeIn 140ms ease;
  }
  .mask.hidden { display: none; }
  .dialog {
    background: var(--surface-raised);
    border-radius: var(--radius);
    padding: 24px;
    max-width: 440px; width: 90%;
    box-shadow: var(--shadow-lg);
    animation: slideUp 180ms ease;
  }
  .dialog h3 { margin: 0 0 8px; font-size: 17px; font-weight: 600; letter-spacing: -0.005em; }
  .dialog p { margin: 0 0 18px; color: var(--text-dim); font-size: 14px; line-height: 1.5; }
  .dialog .fname { color: var(--text); font-weight: 600; word-break: break-all; }
  .dialog .buttons { display: flex; gap: 8px; justify-content: flex-end; }
  .dialog .file-list { max-height: 140px; overflow: auto; margin-top: 8px; padding: 8px; background: var(--surface-sunken); border-radius: 8px; }
  .dialog .file-list div { font-size: 13px; padding: 2px 0; }

  /* Spinner */
  .spinner {
    display: inline-block;
    width: 13px; height: 13px;
    border: 2px solid var(--border-strong);
    border-top-color: var(--blue);
    border-radius: 50%;
    animation: spin 0.7s linear infinite;
    vertical-align: middle;
  }
  @keyframes spin { to { transform: rotate(360deg); } }
  @keyframes fadeIn { from { opacity: 0; } to { opacity: 1; } }
  @keyframes slideUp { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: translateY(0); } }

  /* Login card is centered and slim */
  #login { max-width: 420px; margin: 80px auto 0; }

  @media (max-width: 640px) {
    .wrap { padding: 24px 16px 64px; }
    .card { padding: 20px; }
    .drop { padding: 28px 16px; }
    .file-actions button.small { padding: 6px 10px; }
  }
</style>
</head>
<body>

<div class="wrap">
  <div id="login" class="card">
    <div class="header" style="margin-bottom:18px">
      <div class="logo"><img src="/upload/logo.png" alt="Mari Energies"></div>
      <div>
        <h1>Mari Kiosk</h1>
        <div class="sub">Knowledge Base Admin</div>
      </div>
    </div>
    <label class="field-label" for="tok">Admin password</label>
    <input id="tok" type="password" autocomplete="current-password" placeholder="Enter password">
    <div style="margin-top:14px"><button id="enter">Sign in</button></div>
    <div id="loginMsg" class="msg hidden"></div>
  </div>

  <div id="app" class="hidden">
    <div class="header">
      <div class="logo"><img src="/upload/logo.png" alt="Mari Energies"></div>
      <div>
        <h1>Knowledge Base</h1>
        <div class="sub">Upload, review and manage the files the kiosk answers from.</div>
      </div>
    </div>

    <div class="card">
      <div class="card-title">
        <h2>Upload</h2>
        <span class="hint">Markdown files only · max 5 MB each</span>
      </div>
      <label for="fileInput" class="drop" id="drop">
        <input id="fileInput" type="file" accept=".md,.markdown" multiple>
        <div class="drop-icon">⇪</div>
        <div class="drop-main">Drop .md files here or click to browse</div>
        <div class="drop-sub">Multiple files supported · indexed automatically</div>
      </label>
      <div id="uploadMsg" class="msg hidden"></div>
    </div>

    <div class="card">
      <div class="card-title">
        <h2>Current files</h2>
        <button class="ghost small" id="refresh">Refresh</button>
      </div>
      <div id="bulkbar" class="bulkbar hidden">
        <label><input type="checkbox" id="selectAll"> Select all</label>
        <span id="selCount" class="count"></span>
        <div style="flex:1"></div>
        <button class="danger small" id="bulkDel" disabled>Delete selected</button>
      </div>
      <div id="list" class="list">Loading…</div>
    </div>
  </div>
</div>

<div id="modal" class="mask hidden" role="dialog" aria-modal="true">
  <div class="dialog">
    <h3 id="modalTitle">Delete file?</h3>
    <p><span id="modalBody">This will remove <span id="modalName" class="fname"></span> from the knowledge base and drop its chunks from the search index.</span> This cannot be undone.</p>
    <div class="buttons">
      <button class="ghost" id="modalCancel">Cancel</button>
      <button class="danger" id="modalOk">Delete</button>
    </div>
  </div>
</div>

<script>
const $ = (id) => document.getElementById(id);
let TOKEN = sessionStorage.getItem("mari_admin_token") || "";

async function api(path, opts={}) {
  const headers = Object.assign({}, opts.headers || {}, { "X-Admin-Token": TOKEN });
  const res = await fetch(path, Object.assign({}, opts, { headers }));
  const text = await res.text();
  let data; try { data = text ? JSON.parse(text) : {}; } catch { data = { raw: text }; }
  if (!res.ok) { throw Object.assign(new Error(data?.detail?.error?.message || data?.detail || res.statusText), { status: res.status, data }); }
  return data;
}

function fmtSize(n) { if (n < 1024) return n + " B"; if (n < 1024*1024) return (n/1024).toFixed(1) + " KB"; return (n/1024/1024).toFixed(2) + " MB"; }
function fmtTime(ts) {
  const d = new Date(ts * 1000);
  const now = new Date();
  const diff = (now - d) / 1000;
  if (diff < 60) return "just now";
  if (diff < 3600) return Math.floor(diff/60) + " min ago";
  if (diff < 86400) return Math.floor(diff/3600) + " h ago";
  return d.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

async function loadList() {
  const el = $("list");
  el.innerHTML = '<div class="empty"><span class="spinner"></span>&nbsp;&nbsp;Loading…</div>';
  try {
    const data = await api("/upload/kb");
    if (!data.files.length) {
      el.innerHTML = '<div class="empty">No files yet. Upload one above to get started.</div>';
      $("bulkbar").classList.add("hidden");
      return;
    }
    el.innerHTML = "";
    for (const f of data.files) {
      const row = document.createElement("div"); row.className = "row";
      row.innerHTML = `
        <label class="pick">
          <input type="checkbox" class="pickbox" data-name="${encodeURIComponent(f.name)}">
          <div class="file-icon">MD</div>
          <div class="file-info">
            <div class="file-name">${escapeHtml(f.name)}</div>
            <div class="file-meta">${fmtSize(f.size)} · ${fmtTime(f.mtime)}</div>
          </div>
        </label>
        <div class="file-actions">
          <button class="ghost small" data-view="${encodeURIComponent(f.name)}">View</button>
        </div>`;
      el.appendChild(row);
    }
    el.querySelectorAll("[data-view]").forEach(b => b.onclick = (e) => { e.preventDefault(); viewFile(decodeURIComponent(b.dataset.view)); });
    el.querySelectorAll(".pickbox").forEach(cb => cb.addEventListener("change", updateBulkBar));
    $("bulkbar").classList.remove("hidden");
    $("selectAll").checked = false;
    updateBulkBar();
  } catch (e) { el.innerHTML = `<div class="msg err">${escapeHtml(e.message)}</div>`; }
}

async function viewFile(name) {
  try {
    const res = await fetch("/upload/kb/" + encodeURIComponent(name), { headers: { "X-Admin-Token": TOKEN } });
    if (!res.ok) throw new Error("HTTP " + res.status);
    const text = await res.text();
    const w = window.open("", "_blank");
    w.document.write(`<!doctype html><html><head><meta charset=utf-8><title>${escapeHtml(name)}</title><style>body{margin:0;background:#f4f5f7;font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif}pre{white-space:pre-wrap;padding:32px;max-width:820px;margin:0 auto;color:#14161a;font-size:14px;line-height:1.6;background:#fff;min-height:100vh;box-shadow:0 1px 3px rgba(0,0,0,0.06)}h1.ttl{max-width:820px;margin:32px auto 0;padding:0 32px;font-size:14px;color:#14161a99;font-weight:500}</style></head><body><h1 class=ttl>${escapeHtml(name)}</h1><pre>${escapeHtml(text)}</pre></body></html>`);
    w.document.title = name;
  } catch (e) { setMsg("uploadMsg", "err", "View failed: " + escapeHtml(e.message)); }
}

function openModal(name, opts) {
  return new Promise((resolve) => {
    opts = opts || {};
    $("modalTitle").textContent = opts.title || "Delete file?";
    if (opts.bodyHtml) { $("modalBody").innerHTML = opts.bodyHtml; }
    else { $("modalBody").innerHTML = 'This will remove <span id="modalName" class="fname"></span> from the knowledge base and drop its chunks from the search index.'; $("modalName").textContent = name; }
    const m = $("modal"); m.classList.remove("hidden");
    const cleanup = (answer) => { m.classList.add("hidden"); $("modalOk").onclick = null; $("modalCancel").onclick = null; document.onkeydown = null; resolve(answer); };
    $("modalOk").onclick = () => cleanup(true);
    $("modalCancel").onclick = () => cleanup(false);
    document.onkeydown = (e) => { if (e.key === "Escape") cleanup(false); else if (e.key === "Enter") cleanup(true); };
    $("modalCancel").focus();
  });
}

async function uploadFiles(files) {
  for (const f of files) {
    if (!/\.(md|markdown)$/i.test(f.name)) { setMsg("uploadMsg", "err", "Only .md files are accepted: " + escapeHtml(f.name)); continue; }
    setMsg("uploadMsg", "ok", `<span class="spinner"></span> Uploading <b>${escapeHtml(f.name)}</b>…`);
    try {
      const fd = new FormData(); fd.append("file", f, f.name);
      const data = await api("/upload/kb", { method: "POST", body: fd });
      const r = data.ingest || {};
      const chunks = r.chunks ?? 0;
      const dur = (r.duration_s ?? 0).toFixed(2);
      const plural = (n, w) => `${n} ${w}${n === 1 ? "" : "s"}`;
      let msg = `Uploaded <b>${escapeHtml(data.saved)}</b> — indexed into ${plural(chunks, "chunk")} in ${dur}s.`;
      const failed = Object.keys(r.failed || {});
      if (failed.length) msg += ` Failed: ${escapeHtml(failed.join(", "))}`;
      setMsg("uploadMsg", "ok", msg);
    } catch (e) { setMsg("uploadMsg", "err", `Upload ${escapeHtml(f.name)} failed: ` + escapeHtml(e.message)); }
  }
  await loadList();
}

function setMsg(id, kind, html) { const el = $(id); el.className = "msg " + kind; el.innerHTML = html; el.classList.remove("hidden"); }
function escapeHtml(s) { const Q = String.fromCharCode(34); return String(s).replace(/[&<>]/g, c => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;"
  }[c])).split(Q).join("&quot;"); }

function selectedNames() { return Array.from(document.querySelectorAll(".pickbox")).filter(cb => cb.checked).map(cb => decodeURIComponent(cb.dataset.name)); }
function updateBulkBar() {
  const picks = document.querySelectorAll(".pickbox");
  const sel = Array.from(picks).filter(cb => cb.checked);
  $("selCount").textContent = sel.length ? `${sel.length} selected` : "";
  $("bulkDel").disabled = sel.length === 0;
  const all = $("selectAll");
  all.checked = picks.length > 0 && sel.length === picks.length;
  all.indeterminate = sel.length > 0 && sel.length < picks.length;
}
$("selectAll").addEventListener("change", (e) => {
  document.querySelectorAll(".pickbox").forEach(cb => cb.checked = e.target.checked);
  updateBulkBar();
});
$("bulkDel").addEventListener("click", async () => {
  const names = selectedNames();
  if (!names.length) return;
  const title = `Delete ${names.length} file${names.length === 1 ? "" : "s"}?`;
  const list = names.map(n => `<div><span class="fname">${escapeHtml(n)}</span></div>`).join("");
  const body = `This will remove the following ${names.length === 1 ? "file" : "files"} from the knowledge base and drop their chunks from the search index:<div class="file-list">${list}</div>`;
  if (!(await openModal(null, { title, bodyHtml: body }))) return;
  setMsg("uploadMsg", "ok", `<span class="spinner"></span> Deleting ${names.length} file${names.length === 1 ? "" : "s"}…`);
  const results = { ok: [], err: [] };
  for (const name of names) {
    try { await api("/upload/kb/" + encodeURIComponent(name), { method: "DELETE" }); results.ok.push(name); }
    catch (e) { results.err.push(name + ": " + e.message); }
  }
  if (results.err.length) { setMsg("uploadMsg", "err", `Deleted ${results.ok.length}; failed ${results.err.length}: ${escapeHtml(results.err.join("; "))}`); }
  else { setMsg("uploadMsg", "ok", `Deleted ${results.ok.length} file${results.ok.length === 1 ? "" : "s"}.`); }
  await loadList();
});

$("refresh").onclick = loadList;
$("enter").onclick = async () => {
  TOKEN = $("tok").value.trim();
  if (!TOKEN) return;
  try {
    await api("/upload/kb");
    sessionStorage.setItem("mari_admin_token", TOKEN);
    $("login").classList.add("hidden");
    $("app").classList.remove("hidden");
    loadList();
  } catch (e) {
    setMsg("loginMsg", "err", escapeHtml(e.message));
    TOKEN = "";
  }
};
$("tok").addEventListener("keydown", e => { if (e.key === "Enter") $("enter").click(); });
$("fileInput").addEventListener("change", e => uploadFiles(e.target.files));

const drop = $("drop");
["dragenter","dragover"].forEach(ev => drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.add("hover"); }));
["dragleave","drop"].forEach(ev => drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.remove("hover"); }));
drop.addEventListener("drop", e => { if (e.dataTransfer?.files?.length) uploadFiles(e.dataTransfer.files); });

if (TOKEN) {
  api("/upload/kb").then(() => { $("login").classList.add("hidden"); $("app").classList.remove("hidden"); loadList(); })
    .catch(() => { TOKEN = ""; sessionStorage.removeItem("mari_admin_token"); });
}
</script>
</body>
</html>
"""
