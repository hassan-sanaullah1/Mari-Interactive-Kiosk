#!/usr/bin/env python
"""Ingest the corpus into Qdrant. Idempotent — safe to run any time.

    python scripts/rag_ingest.py            # only changed files
    python scripts/rag_ingest.py --force    # rebuild every document
    python scripts/rag_ingest.py --recreate # drop the collection first (schema changes)

The app also ingests on startup; this exists so ingest can be run and inspected without
booting the server, which is what you want when tuning chunking.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.services.ingestion import IngestionService  # noqa: E402
from server.services.settings import get_settings  # noqa: E402
from server.services.store import QdrantStore  # noqa: E402


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="re-ingest even unchanged files")
    ap.add_argument("--recreate", action="store_true",
                    help="delete and recreate the collection (needed after a dense-model "
                         "or dimension change, which the existing vectors are incompatible with)")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    settings = get_settings()
    store = QdrantStore(settings)
    try:
        if args.recreate:
            await store.recreate_collection()
            # The metadata DB records what is in the collection; dropping one without
            # the other leaves every file looking "already ingested" against an empty
            # index, and the kiosk then answers from nothing with no error anywhere.
            settings.metadata_db.unlink(missing_ok=True)
            print(f"recreated collection {settings.qdrant_collection} and reset metadata")

        service = IngestionService(store, settings=settings)
        report = await service.ingest_all(force=args.force or args.recreate)
        print(json.dumps(report.as_dict(), indent=2))
        print(json.dumps(service.metadata.summary(), indent=2))
        print(f"points in collection: {await store.count()}")
        return 1 if report.failed else 0
    finally:
        await store.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
