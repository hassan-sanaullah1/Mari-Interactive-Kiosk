"""Admin KB endpoints: list / upload / download / delete files in the RAG corpus.

The UI is the Next.js page at /admin (frontend/app/admin/); this module is the JSON
API behind it. The routes keep their /upload/* paths so older bookmarks and clients
still reach them, and /upload itself redirects to the new page.

LAN-only by convention — the frontend container is on 0.0.0.0:3000 and this backend
is on 0.0.0.0:8010, both reachable from any PC on the Wi-Fi. A username and password
(X-Admin-User / X-Admin-Token) gate every route; see server/admin_credentials.py for
where they are stored and how they are changed. With none configured the endpoints
return 503: nothing set → closed, rather than open.

Uploaded files land in the corpus directory and are ingested in-process, reusing the
same QdrantStore + EmbeddingService the running retriever already warmed. No restart.
"""

from __future__ import annotations

import logging
import os
import uuid
from pathlib import Path

from fastapi import APIRouter, Header, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel

from . import admin_credentials
# Mirrors the RAG layer, so the portal and the ingester can never disagree.
from .rag.documents import SUPPORTED_SUFFIXES as _ALLOWED_SUFFIXES
from . import config
from .rag.ingestion import IngestionService
from .rag.retriever import get_retriever
from .rag.settings import get_settings

logger = logging.getLogger(__name__)

router = APIRouter()

# Set by MARI_ADMIN_MAX_UPLOAD_MB; see server/config.py for why bytes are only a
# rough proxy for what a large upload actually costs.
_MAX_BYTES = config.ADMIN_MAX_UPLOAD_MB * 1024 * 1024


def _check_token(provided: str | None, user: str | None = None) -> None:
    """Both credentials, or 401. 503 when none are configured at all.

    The username falls back to the stored one when the caller sends no X-Admin-User
    header, so a token-only client still works.
    """
    if not admin_credentials.is_configured():
        raise HTTPException(status_code=503, detail={"error": {"code": "admin_disabled", "message": "MARI_ADMIN_TOKEN is not set on the server"}})
    candidate_user = user if user is not None else admin_credentials.current_user()
    if not admin_credentials.verify(candidate_user, provided):
        raise HTTPException(status_code=401, detail={"error": {"code": "unauthorized", "message": "bad or missing admin credentials"}})


def _safe_target(filename: str, corpus_dir: Path) -> Path:
    name = Path(filename).name  # strip any path components
    if not name or name.startswith(".") or name in {"README.md", "sky47_knowledge_base.md"}:
        raise HTTPException(status_code=400, detail={"error": {"code": "bad_name", "message": f"filename {name!r} not allowed"}})
    if Path(name).suffix.lower() not in _ALLOWED_SUFFIXES:
        raise HTTPException(status_code=400, detail={"error": {"code": "bad_type", "message": f"unsupported file type; accepted: {', '.join(sorted(_ALLOWED_SUFFIXES))}"}})
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


@router.get("/upload/kb")
async def admin_list(x_admin_token: str | None = Header(default=None), x_admin_user: str | None = Header(default=None)) -> JSONResponse:
    _check_token(x_admin_token, x_admin_user)
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
async def admin_get(name: str, x_admin_token: str | None = Header(default=None), x_admin_user: str | None = Header(default=None)) -> FileResponse:
    _check_token(x_admin_token, x_admin_user)
    settings = get_settings()
    target = _safe_target(name, settings.corpus_dir)
    if not target.exists():
        raise HTTPException(status_code=404, detail={"error": {"code": "not_found", "message": f"{name} not in corpus"}})
    return FileResponse(target, media_type="text/markdown", filename=target.name)


@router.post("/upload/kb")
async def admin_upload(file: UploadFile, x_admin_token: str | None = Header(default=None), x_admin_user: str | None = Header(default=None)) -> JSONResponse:
    _check_token(x_admin_token, x_admin_user)
    settings = get_settings()
    corpus_dir: Path = settings.corpus_dir
    corpus_dir.mkdir(parents=True, exist_ok=True)

    if not file.filename:
        raise HTTPException(status_code=400, detail={"error": {"code": "bad_name", "message": "missing filename"}})
    target = _safe_target(file.filename, corpus_dir)

    # Stream to a sibling temp file, then atomically rename. Avoids a half-written file
    # being discovered mid-ingest.
    suffix = Path(file.filename).suffix.lower()
    tmp = corpus_dir / f".incoming-{uuid.uuid4().hex}{suffix}"
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
    if (reason := report.get("failed", {}).get(target.name)) is not None:
        # Remove it again: a file in the corpus that cannot be parsed will be retried
        # on every ingest and never answer anything.
        target.unlink(missing_ok=True)
        await _reingest()
        raise HTTPException(
            status_code=422,
            detail={"error": {"code": "conversion_failed", "message": reason}},
        )
    return JSONResponse({"saved": target.name, "size": size, "ingest": report})


@router.delete("/upload/kb/{name}")
async def admin_delete(name: str, x_admin_token: str | None = Header(default=None), x_admin_user: str | None = Header(default=None)) -> JSONResponse:
    _check_token(x_admin_token, x_admin_user)
    settings = get_settings()
    target = _safe_target(name, settings.corpus_dir)
    if not target.exists():
        raise HTTPException(status_code=404, detail={"error": {"code": "not_found", "message": f"{name} not in corpus"}})
    target.unlink()
    logger.info("admin: deleted %s", name)
    report = await _reingest()
    return JSONResponse({"deleted": name, "ingest": report})


class CredentialsIn(BaseModel):
    """A request to change the sign-in credentials."""

    current_password: str
    new_user: str
    new_password: str


# Where the panel now lives, for the redirect below. The backend serves no page of
# its own any more, so a relative /admin would point at this port, where nothing
# answers; the UI is on the frontend container's port.
_PANEL_URL = os.environ.get("MARI_ADMIN_PANEL_URL", "http://{host}:3000/admin")


@router.get("/upload", include_in_schema=False)
async def admin_page_moved(request: Request) -> RedirectResponse:
    """The panel used to be served here as one HTML page; it is now the Next route at
    /admin on the frontend. Kept so existing bookmarks and the printed kiosk URL
    still land somewhere.

    307, not 308: a permanent redirect is cached by the browser, which would strand
    anyone who had the old URL open if the panel ever moved again.
    """
    # Whatever name the visitor used to reach this backend - an IP, mari-MS-7E44.local
    # or localhost - is the name that will also resolve for the frontend.
    host = request.url.hostname or "localhost"
    return RedirectResponse(url=_PANEL_URL.format(host=host), status_code=307)


@router.get("/upload/whoami")
async def admin_whoami(
    x_admin_token: str | None = Header(default=None), x_admin_user: str | None = Header(default=None)
) -> JSONResponse:
    """The signed-in username, so the panel can show it without trusting the client."""
    _check_token(x_admin_token, x_admin_user)
    return JSONResponse({"user": admin_credentials.current_user()})


@router.post("/upload/credentials")
async def admin_set_credentials(
    body: CredentialsIn,
    x_admin_token: str | None = Header(default=None),
    x_admin_user: str | None = Header(default=None),
) -> JSONResponse:
    """Change the username and password.

    The current password is required even though the caller is already authenticated:
    a browser left signed in on the kiosk must not be enough to lock the owner out.
    """
    _check_token(x_admin_token, x_admin_user)
    if not admin_credentials.verify(admin_credentials.current_user(), body.current_password):
        raise HTTPException(
            status_code=401,
            detail={"error": {"code": "wrong_password", "message": "the current password is incorrect"}},
        )
    user = body.new_user.strip()
    try:
        admin_credentials.validate(user, body.new_password)
    except admin_credentials.CredentialError as exc:
        raise HTTPException(
            status_code=400, detail={"error": {"code": "weak_credentials", "message": str(exc)}}
        ) from exc
    admin_credentials.save(user, body.new_password)
    return JSONResponse({"user": user})
