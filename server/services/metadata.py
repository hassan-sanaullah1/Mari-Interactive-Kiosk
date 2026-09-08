"""SQLite record of what has been ingested.

The index in Qdrant cannot answer "is this file already in here, unchanged?" cheaply or
reliably — counting points by source tells you something is there, not that it matches
the bytes on disk. This table holds the content hash, so startup ingestion can skip
files that have not changed, which is the difference between a container that boots in
two seconds and one that re-embeds the whole corpus on every deploy.

It is also the only place a *failed* ingest is recorded. Without it, a file that failed
to parse is simply absent from the index, and absent looks exactly like "not added yet".
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    filename     TEXT PRIMARY KEY,
    content_hash TEXT NOT NULL,
    file_type    TEXT NOT NULL,
    size_bytes   INTEGER NOT NULL,
    status       TEXT NOT NULL,          -- processing | ready | failed
    chunk_count  INTEGER NOT NULL DEFAULT 0,
    error        TEXT,
    ingested_at  REAL NOT NULL,
    extra        TEXT                    -- JSON, for anything added later
);
CREATE INDEX IF NOT EXISTS documents_status ON documents(status);
"""


@dataclass
class DocumentRecord:
    filename: str
    content_hash: str
    file_type: str
    size_bytes: int
    status: str
    chunk_count: int
    error: str | None
    ingested_at: float
    extra: dict


class MetadataService:
    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        # Ingestion runs on a worker thread while the API serves reads on the loop
        # thread, so connections cannot be shared; one per thread, created on demand.
        self._local = threading.local()
        with self._connect() as conn:
            conn.executescript(SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self.db_path, timeout=10.0)
            conn.row_factory = sqlite3.Row
            # WAL so a read during ingest is not blocked by the write transaction.
            conn.execute("PRAGMA journal_mode=WAL")
            self._local.conn = conn
        return conn

    def get(self, filename: str) -> DocumentRecord | None:
        row = self._connect().execute(
            "SELECT * FROM documents WHERE filename = ?", (filename,)
        ).fetchone()
        return self._to_record(row) if row else None

    def all(self) -> list[DocumentRecord]:
        rows = self._connect().execute(
            "SELECT * FROM documents ORDER BY filename"
        ).fetchall()
        return [self._to_record(r) for r in rows]

    def mark_processing(self, filename: str, content_hash: str, file_type: str, size: int) -> None:
        self._upsert(filename, content_hash, file_type, size, "processing", 0, None, {})

    def mark_ready(self, filename: str, content_hash: str, file_type: str, size: int,
                   chunk_count: int, extra: dict | None = None) -> None:
        self._upsert(filename, content_hash, file_type, size, "ready", chunk_count, None, extra or {})

    def mark_failed(self, filename: str, content_hash: str, file_type: str, size: int,
                    error: str) -> None:
        # The hash of the file that failed is stored deliberately. Re-running ingest
        # should retry a file that failed (its content may now parse against a fixed
        # parser) but must not silently treat the failure as success.
        self._upsert(filename, content_hash, file_type, size, "failed", 0, error[:2000], {})

    def _upsert(self, filename: str, content_hash: str, file_type: str, size: int,
                status: str, chunk_count: int, error: str | None, extra: dict) -> None:
        conn = self._connect()
        with conn:
            conn.execute(
                """
                INSERT INTO documents
                    (filename, content_hash, file_type, size_bytes, status,
                     chunk_count, error, ingested_at, extra)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(filename) DO UPDATE SET
                    content_hash = excluded.content_hash,
                    file_type    = excluded.file_type,
                    size_bytes   = excluded.size_bytes,
                    status       = excluded.status,
                    chunk_count  = excluded.chunk_count,
                    error        = excluded.error,
                    ingested_at  = excluded.ingested_at,
                    extra        = excluded.extra
                """,
                (filename, content_hash, file_type, size, status, chunk_count,
                 error, time.time(), json.dumps(extra)),
            )

    def delete(self, filename: str) -> None:
        conn = self._connect()
        with conn:
            conn.execute("DELETE FROM documents WHERE filename = ?", (filename,))

    def is_unchanged(self, filename: str, content_hash: str) -> bool:
        """True only for a file that is byte-identical AND was ingested successfully.

        The `status == ready` half is what makes a retry after a failed ingest work: a
        file that failed has a stored hash, and a hash-only check would skip it forever.
        """
        record = self.get(filename)
        return bool(record and record.content_hash == content_hash and record.status == "ready")

    @staticmethod
    def _to_record(row: sqlite3.Row) -> DocumentRecord:
        return DocumentRecord(
            filename=row["filename"],
            content_hash=row["content_hash"],
            file_type=row["file_type"],
            size_bytes=row["size_bytes"],
            status=row["status"],
            chunk_count=row["chunk_count"],
            error=row["error"],
            ingested_at=row["ingested_at"],
            extra=json.loads(row["extra"] or "{}"),
        )

    def summary(self) -> dict:
        records = self.all()
        return {
            "documents": len(records),
            "ready": sum(1 for r in records if r.status == "ready"),
            "failed": sum(1 for r in records if r.status == "failed"),
            "chunks": sum(r.chunk_count for r in records),
            "files": [
                {"filename": r.filename, "status": r.status, "chunks": r.chunk_count,
                 "error": r.error}
                for r in records
            ],
        }
