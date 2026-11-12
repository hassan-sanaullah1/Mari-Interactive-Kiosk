"""Document parsing — turns a file on disk into text plus the chunks for it.

Kept separate from chunking.py so the "what does this file format look like" problem and
the "where is it safe to cut" problem stay separable. Adding a format means adding a
parser here and nothing else.
"""

from __future__ import annotations

import hashlib
import logging
import re
from collections.abc import Iterator, Sequence
from pathlib import Path

from .chunking import Chunk, CountTokens, chunk_markdown, chunk_text, strip_frontmatter
from .converters import CONVERTERS, LEGACY_SUFFIXES, ConversionError

logger = logging.getLogger(__name__)

SUPPORTED_SUFFIXES = {".md", ".markdown", ".txt", ".pdf"} | set(CONVERTERS)

# Refuse a PDF longer than this rather than let it run the machine out of memory.
# Extraction is streamed page by page (see parse_pdf), so the ceiling is really about
# the chunk list and the embedding queue that follow: a 286-page report produces
# roughly 1,500 chunks. This is deliberately conservative for the kiosk's 15 GB box
# and can be raised once ingestion runs out of process.
# PDFs are read in batches of this many pages (see pdf_page_batches), so a long
# document costs no more memory than a short one. Measured on a real 286-page annual
# report: 295 MB peak for the whole file, against 2,121 MB before batching.
PDF_BATCH_PAGES = 25

# A ceiling even so, because the CHUNKS accumulate even though the text does not:
# 1,000 pages is roughly 1,700 chunks waiting to be embedded.
MAX_PDF_PAGES = 1000

# Everything that is not a PDF is read into memory whole before chunking, so the file
# size IS the memory cost. Office formats expand several times over once converted to
# markdown, which is why this is well below the upload cap.
MAX_TEXT_BYTES = 60 * 1024 * 1024

# Converted formats are emitted as markdown, so they are chunked by chunk_markdown
# rather than chunk_text. ".txt" and ".pdf" deliberately keep their original
# chunk_text path: they are already tuned against this corpus and the golden
# fixtures pin their output.
_MARKDOWN_SUFFIXES = {".md", ".markdown"} | set(CONVERTERS)


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
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "pdfplumber is required to ingest PDFs (pip install pdfplumber)"
        ) from exc

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
            # Release this page's parsed layout objects before moving on.
            #
            # pdfplumber caches them on the Page, and `pdf.pages` holds every Page for
            # the life of the document - so without this the parsed form of the WHOLE
            # file is resident at once. A real 286-page annual report reached 2.1 GB
            # here and the kernel's OOM killer took the backend down with it (measured:
            # 12.5 GB RSS before the kill). Closing each page as it is read holds the
            # same document at about 173 MB.
            page.close()
    return "\n\n".join(pages)


def pdf_page_batches(path: Path, batch_pages: int) -> Iterator[str]:
    """Yield the PDF's text `batch_pages` at a time, newest batch only in memory.

    A long report is chunked batch by batch rather than as one string, so peak memory
    depends on the BATCH size, not the document size: a 286-page report costs the same
    as a 40-page one. Paragraph chunking is local to a few lines, so splitting on a
    page boundary costs at most the one paragraph that straddles it.
    """
    import pdfplumber

    with pdfplumber.open(path) as pdf:
        batch: list[str] = []
        for page in pdf.pages:
            text = page.extract_text() or ""
            text = re.sub(r"(?<![.!?:;])\n(?=[a-z(])", " ", text)
            if text.strip():
                batch.append(text.strip())
            page.close()
            if len(batch) >= batch_pages:
                yield "\n\n".join(batch)
                batch = []
        if batch:
            yield "\n\n".join(batch)


def parse(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".md", ".markdown"}:
        return parse_markdown(path)
    if suffix == ".pdf":
        return parse_pdf(path)
    if (hint := LEGACY_SUFFIXES.get(suffix)) is not None:
        raise ConversionError(hint)
    if (convert := CONVERTERS.get(suffix)) is not None:
        return convert(path)
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
    metadata = {"doc_hash": doc_hash, "file_type": path.suffix.lower().lstrip(".")}
    kwargs = dict(
        chunk_tokens=chunk_tokens,
        overlap_tokens=overlap_tokens,
        min_tokens=min_tokens,
        count_tokens=count_tokens,
        metadata=metadata,
    )

    # A PDF is read in page batches so that peak memory follows the batch size rather
    # than the document: holding a 286-page report's text and chunks at once is what
    # once drove this process to 12.5 GB and had the kernel kill it.
    if path.suffix.lower() == ".pdf":
        chunks: list[Chunk] = []
        for batch_text in pdf_page_batches(path, PDF_BATCH_PAGES):
            if batch_text.strip():
                chunks.extend(chunk_text(batch_text, path.name, **kwargs))
        # chunk_text numbers from zero within each batch; renumber so the indices are
        # unique across the document, which the store uses as part of the point id.
        for index, chunk in enumerate(chunks):
            chunk.chunk_index = index
        return chunks

    text = parse(path)
    if not text.strip():
        return []
    if path.suffix.lower() in _MARKDOWN_SUFFIXES:
        return chunk_markdown(text, path.name, **kwargs)
    return chunk_text(text, path.name, **kwargs)


def discover(corpus_dir: Path, exclude: Sequence[str] = ()) -> list[Path]:
    """Every ingestable file under `corpus_dir`, sorted for deterministic ingest order.

    Dotfiles are skipped so the metadata SQLite database, which lives alongside the
    corpus, is never ingested as a document.
    """
    if not corpus_dir.exists():
        logger.warning("corpus dir %s does not exist — nothing to ingest", corpus_dir)
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

def chunks_for_preflight(path: Path) -> None:
    """Raise if this file cannot be ingested safely. Cheap checks only.

    Called by the admin upload before the corpus is re-indexed, so a file that would
    exhaust the machine is rejected while it can still simply be deleted. Parsing is
    the expensive half, so this does only what is needed to decide: page count for a
    PDF, byte size for everything else.
    """
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        import pdfplumber

        try:
            with pdfplumber.open(path) as pdf:
                pages = len(pdf.pages)
        except Exception as exc:
            # A truncated or damaged PDF: say so in one second rather than letting the
            # parser grind through a broken xref for minutes. A 30 MB upload once
            # arrived truncated at 10 MB and took seven minutes to fail.
            raise ValueError(
                "this PDF could not be read - it may be damaged or incompletely "
                f"uploaded ({type(exc).__name__}). Try uploading it again."
            ) from exc
        if pages > MAX_PDF_PAGES:
            raise ValueError(
                f"this PDF has {pages} pages and the limit is {MAX_PDF_PAGES}. "
                "Please split it and upload the parts separately."
            )
        return
    size = path.stat().st_size
    if size > MAX_TEXT_BYTES:
        raise ValueError(
            f"this file is {size // 1024 // 1024} MB and the limit for its type is "
            f"{MAX_TEXT_BYTES // 1024 // 1024} MB."
        )
