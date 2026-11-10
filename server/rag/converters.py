"""Document converters — turn a non-markdown file into markdown text.

Why markdown rather than plain text: chunking.py's ``chunk_markdown`` is structure
aware. It gives every chunk the heading path it sits under, keeps tables atomic, and
cuts at section boundaries. ``chunk_text`` has none of that, so a converted table row
("| Bhitai-6 | 1,200 | 2021 |") would reach the index with nothing saying what the
columns mean or what the table is about. Emitting markdown lets a converted .docx or
.xlsx retrieve as well as a hand-written .md.

Each converter is independent and imported lazily, so a missing optional dependency
disables one format instead of breaking ingestion for all of them.
"""

from __future__ import annotations

import csv
import io
import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

# A sheet or flat file wider than this is almost certainly a data dump rather than a
# document; its rows are emitted as definition lists instead of an unreadable table.
MAX_TABLE_COLUMNS = 12

# Rows per emitted markdown table. chunk_markdown treats a table as atomic, so one
# 10,000-row sheet would become a single chunk far over the 320-token budget and be
# dropped or truncated. Splitting into groups, each repeating the header, keeps every
# chunk self-describing and inside the budget.
ROWS_PER_TABLE_GROUP = 25


class ConversionError(RuntimeError):
    """Raised when a file cannot be converted; ingestion records it and moves on."""


# ── helpers ─────────────────────────────────────────────────────────


def _clean_cell(value: object) -> str:
    """One cell as a single-line markdown-table-safe string."""
    if value is None:
        return ""
    text = str(value).strip()
    # A newline or an unescaped pipe would break the table row it sits in.
    text = text.replace("|", "\\|")
    text = re.sub(r"\s*\n\s*", " ", text)
    return text


def _is_blank_row(row: list[str]) -> bool:
    return all(not cell for cell in row)


def _trim_trailing_blanks(rows: list[list[str]]) -> list[list[str]]:
    while rows and _is_blank_row(rows[-1]):
        rows.pop()
    return rows


def _find_header(rows: list[list[str]]) -> int:
    """Index of the header row, skipping title/blank rows above it.

    Spreadsheets routinely open with a merged title and a blank line before the real
    header. Taking row 0 blindly labels every column after a title cell, which makes
    the whole table unretrievable.
    """
    for i, row in enumerate(rows[:10]):
        filled = [c for c in row if c]
        # A header has several filled cells and no cell that is obviously a number.
        if len(filled) >= 2 and not all(_looks_numeric(c) for c in filled):
            return i
    return 0


_NUMERIC_RE = re.compile(r"^[-+]?[\d,]*\.?\d+%?$")


def _looks_numeric(text: str) -> bool:
    return bool(_NUMERIC_RE.match(text.strip()))


def _dedupe_headers(header: list[str]) -> list[str]:
    """Make every column label non-empty and unique, so no column is anonymous."""
    seen: dict[str, int] = {}
    out: list[str] = []
    for i, name in enumerate(header):
        label = name or f"Column {i + 1}"
        if label in seen:
            seen[label] += 1
            label = f"{label} ({seen[label]})"
        else:
            seen[label] = 1
        out.append(label)
    return out


def _rows_to_markdown(rows: list[list[str]], title: str, heading_level: int = 2) -> str:
    """Rows as one or more markdown tables under ``title``.

    Wide tables become definition lists: a 30-column markdown table is unreadable to the
    model and wastes the chunk budget on pipes. Long tables are split into row groups,
    each with its own heading and a repeated header row, so a chunk from the middle of a
    sheet still carries its column names.
    """
    rows = _trim_trailing_blanks([r for r in rows])
    if not rows:
        return ""

    hdr_idx = _find_header(rows)
    header = _dedupe_headers(rows[hdr_idx])
    body = [r for r in rows[hdr_idx + 1 :] if not _is_blank_row(r)]
    if not body:
        return ""

    hashes = "#" * heading_level
    width = len(header)

    if width > MAX_TABLE_COLUMNS:
        return _rows_to_definition_lists(header, body, title, heading_level)

    parts: list[str] = []
    total_groups = (len(body) + ROWS_PER_TABLE_GROUP - 1) // ROWS_PER_TABLE_GROUP

    for g in range(total_groups):
        group = body[g * ROWS_PER_TABLE_GROUP : (g + 1) * ROWS_PER_TABLE_GROUP]
        if total_groups > 1:
            first = g * ROWS_PER_TABLE_GROUP + 1
            last = first + len(group) - 1
            parts.append(f"{hashes} {title} (rows {first}–{last})")
        else:
            parts.append(f"{hashes} {title}")
        parts.append("")
        parts.append("| " + " | ".join(header) + " |")
        parts.append("|" + "|".join(["---"] * width) + "|")
        for row in group:
            padded = (row + [""] * width)[:width]
            parts.append("| " + " | ".join(padded) + " |")
        parts.append("")

    return "\n".join(parts)


def _rows_to_definition_lists(
    header: list[str], body: list[list[str]], title: str, heading_level: int
) -> str:
    """Very wide rows as "Label: value" blocks, one block per row.

    Keeps every value next to its column name, which is the part that has to survive
    for retrieval to work at all.
    """
    hashes = "#" * heading_level
    parts = [f"{hashes} {title}", ""]
    width = len(header)
    for row in body:
        padded = (row + [""] * width)[:width]
        pairs = [f"**{h}**: {v}" for h, v in zip(header, padded) if v]
        if pairs:
            parts.append("- " + "; ".join(pairs))
    parts.append("")
    return "\n".join(parts)


# ── Word ────────────────────────────────────────────────────────────

_WORD_HEADING_RE = re.compile(r"^Heading\s+(\d)$", re.IGNORECASE)


def convert_docx(path: Path) -> str:
    """Word document to markdown, mapping Word heading styles onto ``#`` levels.

    Word's built-in "Heading N" styles are the document's real structure, so they become
    markdown headings and chunk_markdown can use them. Tables become markdown tables.
    """
    try:
        import docx  # python-docx
    except ImportError as exc:
        raise ConversionError(
            "python-docx is required to ingest .docx files (pip install python-docx)"
        ) from exc

    try:
        document = docx.Document(str(path))
    except Exception as exc:
        raise ConversionError(f"could not open .docx: {type(exc).__name__}: {exc}") from exc

    parts: list[str] = [f"# {path.stem}", ""]
    has_explicit_heading = False
    # Tables belong under whichever heading precedes them, so a table in a deep
    # subsection is not promoted to a sibling of its own parent.
    current_level = 1

    # Walk body elements in document order so tables stay where the author put them,
    # under the heading they belong to.
    body = document.element.body
    para_map = {p._element: p for p in document.paragraphs}
    table_map = {t._element: t for t in document.tables}

    for child in body.iterchildren():
        if child in para_map:
            para = para_map[child]
            text = (para.text or "").strip()
            if not text:
                continue
            style = (para.style.name if para.style is not None else "") or ""
            m = _WORD_HEADING_RE.match(style.strip())
            if m:
                # Shift down one level: the filename already occupies "#".
                level = min(6, int(m.group(1)) + 1)
                parts.append(f"{'#' * level} {text}")
                parts.append("")
                current_level = level
                has_explicit_heading = True
            elif style.strip().lower() == "title":
                parts.append(f"## {text}")
                parts.append("")
                current_level = 2
                has_explicit_heading = True
            elif style.strip().lower().startswith("list"):
                parts.append(f"- {text}")
            else:
                parts.append(text)
                parts.append("")
        elif child in table_map:
            table = table_map[child]
            rows = [[_clean_cell(c.text) for c in r.cells] for r in table.rows]
            md = _rows_to_markdown(rows, "Table", heading_level=min(6, current_level + 1))
            if md:
                if parts and parts[-1] != "":
                    parts.append("")
                parts.append(md)

    if not has_explicit_heading:
        logger.info(
            "%s has no Word heading styles; chunks will carry the filename only", path.name
        )

    return "\n".join(parts)


# ── Excel ───────────────────────────────────────────────────────────


def convert_xlsx(path: Path) -> str:
    """Workbook to markdown: one ``##`` section per sheet, tables split into row groups.

    read_only + values_only keeps a large workbook from being held in memory as cell
    objects, and formulas arrive as their last computed value rather than as "=SUM(...)".
    """
    try:
        import openpyxl
    except ImportError as exc:
        raise ConversionError(
            "openpyxl is required to ingest .xlsx files (pip install openpyxl)"
        ) from exc

    try:
        workbook = openpyxl.load_workbook(str(path), read_only=True, data_only=True)
    except Exception as exc:
        raise ConversionError(f"could not open .xlsx: {type(exc).__name__}: {exc}") from exc

    parts: list[str] = [f"# {path.stem}", ""]
    try:
        for sheet in workbook.worksheets:
            rows = [
                [_clean_cell(v) for v in row]
                for row in sheet.iter_rows(values_only=True)
            ]
            md = _rows_to_markdown(rows, sheet.title, heading_level=2)
            if md:
                parts.append(md)
    finally:
        workbook.close()

    return "\n".join(parts)


# ── CSV and other flat files ────────────────────────────────────────


def _read_text_guessing_encoding(path: Path) -> str:
    """Flat files exported from Excel are routinely cp1252 or UTF-8 with a BOM."""
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def convert_csv(path: Path) -> str:
    """Delimited text to a markdown table, sniffing the delimiter.

    Covers .csv and .tsv; the sniffer handles semicolon and pipe exports too.
    """
    text = _read_text_guessing_encoding(path)
    if not text.strip():
        return ""

    sample = text[:8192]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
        if path.suffix.lower() == ".tsv":
            dialect = csv.excel_tab

    rows = [[_clean_cell(c) for c in row] for row in csv.reader(io.StringIO(text), dialect)]
    # The table sits at "##" under a "#" document title. chunk_markdown treats a lone
    # top-level "#" as the document title and strips it from the heading path, so a
    # table emitted at "#" would reach the index with no heading path at all.
    md = _rows_to_markdown(rows, path.stem, heading_level=2)
    return f"# {path.stem}\n\n{md}" if md else ""


# ── registry ────────────────────────────────────────────────────────

CONVERTERS = {
    ".docx": convert_docx,
    ".xlsx": convert_xlsx,
    ".xlsm": convert_xlsx,
    ".csv": convert_csv,
    ".tsv": convert_csv,
}

# Legacy binary formats need LibreOffice to read; rejected with a message that says what
# to do instead, rather than silently ingesting nothing.
LEGACY_SUFFIXES = {
    ".doc": "Save as .docx and upload again (.doc is the pre-2007 binary format).",
    ".xls": "Save as .xlsx and upload again (.xls is the pre-2007 binary format).",
    ".ppt": "PowerPoint is not supported.",
    ".pptx": "PowerPoint is not supported.",
}
