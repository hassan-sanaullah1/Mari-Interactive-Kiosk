"""Startup ingestion — idempotent, hash-based, and safe to run on every boot.

The contract: after this runs, the index contains exactly the chunks of exactly the
files currently in the corpus directory, and running it again changes nothing. That
matters more than it sounds. The container restarts on every deploy, health check
failure and config change; an ingest that is not idempotent either duplicates the corpus
or spends 40 seconds re-embedding it, on every one of those.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import documents
from .embedding import EmbeddingService, get_embedding_service
from .metadata import MetadataService
from .settings import RagSettings, get_settings
from .store import QdrantStore

log = logging.getLogger(__name__)


@dataclass
class IngestReport:
    ingested: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    failed: dict[str, str] = field(default_factory=dict)
    removed: list[str] = field(default_factory=list)
    chunks: int = 0
    duration_s: float = 0.0

    def as_dict(self) -> dict:
        return {
            "ingested": self.ingested,
            "skipped": self.skipped,
            "failed": self.failed,
            "removed": self.removed,
            "chunks": self.chunks,
            "duration_s": round(self.duration_s, 2),
        }


class IngestionService:
    def __init__(
        self,
        store: QdrantStore,
        embedding: EmbeddingService | None = None,
        metadata: MetadataService | None = None,
        settings: RagSettings | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.store = store
        self.embedding = embedding or get_embedding_service(self.settings)
        self.metadata = metadata or MetadataService(self.settings.metadata_db)

    async def ingest_all(self, force: bool | None = None) -> IngestReport:
        t0 = time.perf_counter()
        force = self.settings.force_reingest if force is None else force
        report = IngestReport()

        await self.store.ensure_collection()
        files = documents.discover(self.settings.corpus_dir, self.settings.corpus_exclude)
        present = {p.name for p in files}

        for path in files:
            digest = await asyncio.to_thread(documents.file_hash, path)
            # Two conditions, not one. The hash record says "this file was ingested";
            # the point count says "and it is still in the index". Trusting the record
            # alone means a metadata DB that outlives the index it describes silently
            # produces an empty, healthy-looking kiosk that answers everything
            # ungrounded — no error, no failed ingest, just no knowledge.
            #
            # That is not hypothetical. The DB defaults to a path inside the corpus
            # directory, the Dockerfile COPYs that directory into the image, and a
            # developer who had run the server on the host baked their own "ready, 89
            # chunks" record into the build. Every container from that image then
            # skipped ingestion against a fresh, empty Qdrant volume.
            if not force and self.metadata.is_unchanged(path.name, digest):
                if await self.store.count_by_source(path.name) > 0:
                    report.skipped.append(path.name)
                    continue
                log.warning(
                    "%s is recorded as ingested but has no chunks in the index; "
                    "re-ingesting", path.name,
                )
            try:
                count = await self._ingest_file(path, digest)
                report.ingested.append(path.name)
                report.chunks += count
            except Exception as exc:  # noqa: BLE001 - one bad file must not stop the rest
                log.exception("ingest failed for %s", path.name)
                self.metadata.mark_failed(
                    path.name, digest, path.suffix.lstrip("."),
                    path.stat().st_size, f"{type(exc).__name__}: {exc}",
                )
                report.failed[path.name] = f"{type(exc).__name__}: {exc}"

        # A file deleted from the corpus directory must leave the index too. Otherwise
        # retired content keeps being retrieved and answered from, with no file on disk
        # to explain where the answer came from — the worst kind of stale.
        for record in self.metadata.all():
            if record.filename not in present:
                await self.store.delete_by_source(record.filename)
                self.metadata.delete(record.filename)
                report.removed.append(record.filename)

        self.embedding.clear_caches()
        report.duration_s = time.perf_counter() - t0
        log.info("ingest complete: %s", report.as_dict())
        return report

    async def _ingest_file(self, path: Path, digest: str) -> int:
        size = path.stat().st_size
        file_type = path.suffix.lstrip(".").lower()
        self.metadata.mark_processing(path.name, digest, file_type, size)

        chunks = await asyncio.to_thread(
            documents.chunks_for,
            path,
            chunk_tokens=self.settings.chunk_tokens,
            overlap_tokens=self.settings.chunk_overlap_tokens,
            min_tokens=self.settings.min_chunk_tokens,
            count_tokens=self.embedding.count_tokens,
            doc_hash=digest,
        )
        if not chunks:
            self.metadata.mark_ready(path.name, digest, file_type, size, 0)
            return 0

        # Delete before insert, not after. If the process dies between the two, an empty
        # slot for this document is recoverable on the next boot (the hash check will
        # not match a `processing` row, so it re-ingests); a duplicated document is not
        # detectable at all.
        await self.store.delete_by_source(path.name)

        ingested_at = time.time()
        total = 0
        batch_size = self.settings.ingest_batch_size
        for start in range(0, len(chunks), batch_size):
            batch = chunks[start : start + batch_size]
            texts = [c.text for c in batch]
            dense = await self.embedding.embed_async(texts)
            sparse = await asyncio.to_thread(self.embedding.embed_sparse, texts)
            payloads = [
                {
                    "text": c.text,
                    "source": c.source,
                    "heading_path": c.heading_path,
                    "chunk_index": c.chunk_index,
                    "token_count": c.token_count,
                    "doc_hash": digest,
                    "ingested_at": ingested_at,
                    **c.metadata,
                }
                for c in batch
            ]
            total += await self.store.upsert_chunks(texts, dense, sparse, payloads)

        self.metadata.mark_ready(path.name, digest, file_type, size, total)
        log.info("ingested %s: %d chunks", path.name, total)
        return total

    async def delete_source(self, filename: str) -> None:
        await self.store.delete_by_source(filename)
        self.metadata.delete(filename)
