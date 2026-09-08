"""Document parsing — turns a file on disk into text plus the chunks for it.

Kept separate from chunking.py so the "what does this file format look like" problem and
the "where is it safe to cut" problem stay separable. Adding a format means adding a
parser here and nothing else.
"""

from __future__ import annotations

import hashlib
import logging
import re
from pathlib import Path
from typing import Sequence

from .chunking import Chunk, CountTokens, chunk_markdown, chunk_text, strip_frontmatter

log = logging.getLogger(__name__)

SUPPORTED_SUFFIXES = {".md", ".markdown", ".txt", ".pdf"}


def file_hash(path: Path) -> str:
    """SHA-256 of the file's bytes — the identity used to decide whether to re-ingest.

    Hashing bytes rather than trusting mtime is what makes ingestion idempotent across
    container rebuilds: a fresh image checks out every file with a new mtime, and an
    mtime-based check would re-embed the whole corpus on every deploy.
    """
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def parse_markdown(path: Path) -> str:
    """Read markdown, dropping YAML frontmatter.

    Frontmatter is metadata about the document, not content. Left in, it embeds as a
    chunk of key-value noise that matches any query mentioning a date or an author.
    """
    return strip_frontmatter(path.read_text(encoding="utf-8"))


def parse_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def parse_pdf(path: Path) -> str:
    """Extract text from a PDF, one blank-line-separated block per paragraph.

    pdfplumber rather than PyPDF2 because it keeps layout information, which is what
    makes it possible to tell a paragraph break from a line wrap. Without that, every
    line of the PDF becomes its own "paragraph" and paragraph-boundary chunking degrades
    back into the arbitrary word-window it was meant to replace.
    """
    try:
        import pdfplumber
    except ImportError:  # pragma: no cover
        raise RuntimeError("pdfplumber is required to ingest PDFs (pip install pdfplumber)")

    pages: list[str] = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            # Re-join lines that are wrapped mid-sentence, but keep real breaks. A line
            # not ending in sentence punctuation, followed by a lowercase continuation,
            # is a wrap.
            text = re.sub(r"(?<![.!?:;])\n(?=[a-z(])", " ", text)
            if text.strip():
                pages.append(text.strip())
    return "\n\n".join(pages)


def parse(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".md", ".markdown"}:
        return parse_markdown(path)
    if suffix == ".pdf":
        return parse_pdf(path)
    return parse_text(path)


def chunks_for(
    path: Path,
    *,
    chunk_tokens: int,
    overlap_tokens: int,
    min_tokens: int,
    count_tokens: CountTokens | None = None,
    doc_hash: str = "",
) -> list[Chunk]:
    """Parse and chunk one file, choosing the chunker that fits its structure."""
    text = parse(path)
    if not text.strip():
        return []

    metadata = {"doc_hash": doc_hash, "file_type": path.suffix.lower().lstrip(".")}
    kwargs = dict(
        chunk_tokens=chunk_tokens,
        overlap_tokens=overlap_tokens,
        min_tokens=min_tokens,
        count_tokens=count_tokens,
        metadata=metadata,
    )
    if path.suffix.lower() in {".md", ".markdown"}:
        return chunk_markdown(text, path.name, **kwargs)
    return chunk_text(text, path.name, **kwargs)


def discover(corpus_dir: Path, exclude: Sequence[str] = ()) -> list[Path]:
    """Every ingestable file under `corpus_dir`, sorted for deterministic ingest order.

    Dotfiles are skipped so the metadata SQLite database, which lives alongside the
    corpus, is never ingested as a document.
    """
    if not corpus_dir.exists():
        log.warning("corpus dir %s does not exist — nothing to ingest", corpus_dir)
        return []
    skip = {name.lower() for name in exclude}
    return sorted(
        p
        for p in corpus_dir.rglob("*")
        if p.is_file()
        and p.suffix.lower() in SUPPORTED_SUFFIXES
        and not p.name.startswith(".")
        and p.name.lower() not in skip
    )
