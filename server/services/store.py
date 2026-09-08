"""Qdrant collection management and the hybrid query itself.

Split out from the retriever so that ingestion and retrieval talk to the index through
exactly one piece of code. When the write path and the read path each own their own
client, they drift — different collection names, different vector names, one of them
missing the payload index — and the failure is silent until a query returns nothing.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Any, Sequence

import numpy as np
from qdrant_client import AsyncQdrantClient, models

from .settings import RagSettings, get_settings

log = logging.getLogger(__name__)

DENSE = "dense"
SPARSE = "sparse"


def _cosine(query_vector: np.ndarray, point_vector) -> float:
    """Cosine similarity, tolerating however qdrant-client hands back a named vector.

    Both sides are already L2-normalized at encode time, so this is a dot product — but
    it is computed rather than assumed, because a future model swap that stops
    normalizing would otherwise silently miscalibrate the relevance gate.
    """
    if isinstance(point_vector, dict):
        point_vector = point_vector.get(DENSE)
    if point_vector is None:
        return 0.0
    other = np.asarray(point_vector, dtype=np.float32)
    denom = float(np.linalg.norm(query_vector) * np.linalg.norm(other))
    return float(np.dot(query_vector, other) / denom) if denom else 0.0


@dataclass
class Hit:
    text: str
    source: str
    heading_path: str
    chunk_index: int
    score: float          # the fused RRF score
    payload: dict
    # Cosine similarity between the query and this chunk's dense vector. RRF scores are
    # rank-based, so they say nothing about whether the top result is any good — rank 1
    # exists no matter how irrelevant everything is. This is the calibrated number the
    # relevance gate needs when the cross-encoder is not run (see retriever.py).
    dense_similarity: float = 0.0


class QdrantStore:
    def __init__(self, settings: RagSettings | None = None) -> None:
        self.settings = settings or get_settings()
        self._client: AsyncQdrantClient | None = None

    @property
    def client(self) -> AsyncQdrantClient:
        if self._client is None:
            s = self.settings
            self._client = AsyncQdrantClient(
                host=s.qdrant_host,
                port=s.qdrant_port,
                api_key=s.qdrant_api_key or None,
                timeout=s.qdrant_timeout_s,
                # qdrant-client flips to HTTPS the moment api_key is set. Inside a
                # compose or Coolify network Qdrant speaks plaintext on 6333, so that
                # flip attempts a TLS handshake against an HTTP port and surfaces as a
                # generic connection error that points nowhere near the real cause.
                # Passing it explicitly is the whole fix, and it costs nothing when the
                # deployment genuinely is behind TLS (set MARI_RAG_QDRANT_HTTPS=true).
                https=s.qdrant_https,
            )
        return self._client

    async def close(self) -> None:
        if self._client is not None:
            await self._client.close()
            self._client = None

    # ── collection ──────────────────────────────────────────────────

    async def ensure_collection(self) -> None:
        """Create the collection and its indexes if missing. Safe to call every boot."""
        name = self.settings.qdrant_collection
        if not await self.client.collection_exists(name):
            await self.client.create_collection(
                collection_name=name,
                # Named vectors: dense and sparse live on the same point, which is what
                # lets Qdrant fuse them server-side in one round trip instead of two
                # queries fused in Python.
                vectors_config={
                    DENSE: models.VectorParams(
                        size=self.settings.dense_dim,
                        distance=models.Distance.COSINE,
                    )
                },
                sparse_vectors_config={SPARSE: models.SparseVectorParams()},
            )
            log.info("created Qdrant collection %s", name)

        # KEYWORD index on `source`. Without it, the filtered delete that re-ingest
        # performs is a full scan of every point, and so is counting a document's
        # chunks. On this corpus that is survivable; on any real one it is not, and the
        # cost of the index is negligible either way.
        try:
            await self.client.create_payload_index(
                collection_name=name,
                field_name="source",
                field_schema=models.PayloadSchemaType.KEYWORD,
            )
        except Exception as exc:  # noqa: BLE001 - already-exists is the common case
            log.debug("payload index on `source` not created: %s", exc)

    async def recreate_collection(self) -> None:
        name = self.settings.qdrant_collection
        if await self.client.collection_exists(name):
            await self.client.delete_collection(name)
        await self.ensure_collection()

    # ── writes ──────────────────────────────────────────────────────

    async def upsert_chunks(
        self,
        texts: Sequence[str],
        dense_vectors: Any,
        sparse_vectors: Sequence[Any],
        payloads: Sequence[dict],
    ) -> int:
        points = [
            models.PointStruct(
                # A random UUID rather than a content hash: two identical chunks in
                # different documents are two legitimate points, and hashing would make
                # the second silently overwrite the first.
                id=str(uuid.uuid4()),
                vector={
                    DENSE: dense_vectors[i].tolist(),
                    SPARSE: models.SparseVector(
                        indices=sparse_vectors[i].indices.tolist(),
                        values=sparse_vectors[i].values.tolist(),
                    ),
                },
                payload=payloads[i],
            )
            for i in range(len(texts))
        ]
        if points:
            await self.client.upsert(
                collection_name=self.settings.qdrant_collection,
                points=points,
                wait=True,
            )
        return len(points)

    async def delete_by_source(self, source: str) -> None:
        """Remove every chunk of one document, so re-ingest replaces rather than duplicates.

        The failure this prevents: without it, editing a document adds a second copy of
        every chunk. Retrieval then returns the same text twice, which wastes two of the
        five context slots and makes a stale chunk look corroborated by a fresh one.
        """
        await self.client.delete(
            collection_name=self.settings.qdrant_collection,
            points_selector=models.FilterSelector(
                filter=models.Filter(
                    must=[models.FieldCondition(key="source", match=models.MatchValue(value=source))]
                )
            ),
            wait=True,
        )

    async def count_by_source(self, source: str) -> int:
        result = await self.client.count(
            collection_name=self.settings.qdrant_collection,
            count_filter=models.Filter(
                must=[models.FieldCondition(key="source", match=models.MatchValue(value=source))]
            ),
            exact=True,
        )
        return result.count

    async def count(self) -> int:
        return (await self.client.count(self.settings.qdrant_collection, exact=True)).count

    async def scroll_all(self, batch: int = 256):
        """Every payload in the collection. Used once at warmup to mine the glossary."""
        offset = None
        while True:
            points, offset = await self.client.scroll(
                collection_name=self.settings.qdrant_collection,
                limit=batch,
                offset=offset,
                with_payload=True,
                with_vectors=False,
            )
            for point in points:
                yield point.payload or {}
            if offset is None:
                return

    # ── the hybrid query ────────────────────────────────────────────

    async def hybrid_search(
        self,
        dense_vector: Any,
        sparse_vector: Any,
        *,
        limit: int,
        prefetch_limit: int,
    ) -> list[Hit]:
        """Dense + sparse candidates, fused server-side by Reciprocal Rank Fusion.

        One round trip. Fusing in Python would mean two queries (two network round trips
        inside a 120 ms budget) and re-implementing RRF, and the Python version would
        then be the thing that drifts from what Qdrant does.

        RRF rather than a weighted score blend because the two channels' scores are not
        comparable — cosine similarity is bounded and dense, BM25 is unbounded and
        sparse. Rank is the only common currency, and RRF needs no per-corpus weight to
        tune (one fewer number nobody would ever re-measure).
        """
        response = await self.client.query_points(
            collection_name=self.settings.qdrant_collection,
            prefetch=[
                models.Prefetch(query=dense_vector.tolist(), using=DENSE, limit=prefetch_limit),
                models.Prefetch(
                    query=models.SparseVector(
                        indices=sparse_vector.indices.tolist(),
                        values=sparse_vector.values.tolist(),
                    ),
                    using=SPARSE,
                    limit=prefetch_limit,
                ),
            ],
            query=models.FusionQuery(fusion=models.Fusion.RRF),
            limit=limit,
            with_payload=True,
            # Dense vectors come back so the caller can compute a real similarity for
            # each hit. ~10 x 1024 float32 is ~40 KB over a loopback/compose network —
            # measurably free next to the alternative, which is a second query.
            with_vectors=[DENSE],
        )

        query_vector = np.asarray(dense_vector, dtype=np.float32)
        hits: list[Hit] = []
        for p in response.points:
            payload = p.payload or {}
            hits.append(
                Hit(
                    text=payload.get("text", ""),
                    source=payload.get("source", ""),
                    heading_path=payload.get("heading_path", ""),
                    chunk_index=payload.get("chunk_index", -1),
                    score=float(p.score),
                    payload=payload,
                    dense_similarity=_cosine(query_vector, p.vector),
                )
            )
        return hits

    async def health(self) -> dict:
        try:
            name = self.settings.qdrant_collection
            exists = await self.client.collection_exists(name)
            return {
                "reachable": True,
                "collection": name,
                "exists": exists,
                "points": await self.count() if exists else 0,
            }
        except Exception as exc:  # noqa: BLE001
            return {"reachable": False, "collection": self.settings.qdrant_collection,
                    "error": f"{type(exc).__name__}: {exc}"}
