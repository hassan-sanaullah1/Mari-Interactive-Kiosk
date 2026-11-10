# Knowledge base file formats

The kiosk answers from the files in `server/data/`. Upload them through the admin
portal; they are converted, chunked and embedded in the same request, and the kiosk
uses them on the next question. No restart or rebuild is needed to add a file.

## Accepted formats

| Format | Extension | How it is read |
|---|---|---|
| Markdown | `.md`, `.markdown` | Natively. Headings drive chunking. |
| Plain text | `.txt` | Paragraph chunking. |
| PDF | `.pdf` | `pdfplumber`, layout-aware so wrapped lines rejoin. |
| Word | `.docx` | `python-docx`. Word heading styles become markdown headings; tables become markdown tables. |
| Excel | `.xlsx`, `.xlsm` | `openpyxl`. One section per sheet; long sheets split into row groups that each repeat the header. |
| Delimited | `.csv`, `.tsv` | Delimiter and encoding are sniffed; becomes a markdown table. |

`.doc`, `.xls` and PowerPoint are rejected with a message asking for the modern
equivalent. Reading them needs LibreOffice in the image (~400 MB) and has not been
judged worth it.

Maximum 25 MB per file.

## Why everything becomes markdown

`server/rag/chunking.py` is structure aware: it gives every chunk the heading path it
sits under, so an isolated chunk still says what it is about. A bare table row
(`| Bhitai-6 | 2,980 | Active |`) means nothing on its own — the column names and the
subject live in the heading above it.

So each converter emits markdown and `chunk_markdown` does the rest. A converted
`.docx` retrieves as well as a hand-written `.md`.

Two deliberate exceptions: `.txt` and `.pdf` keep their original `chunk_text` path.
They work today, their output is pinned by the golden fixtures, and changing them was
not worth the risk. Converting them to markdown with heading detection is a possible
future improvement.

## Spreadsheet handling

Three things that would otherwise lose information, and what is done instead:

- **A title row above the header.** `_find_header` scans the first ten rows for the
  first that has several filled, non-numeric cells. Taking row 0 blindly would label
  every column after a merged title cell.
- **Very long sheets.** A table is atomic to the chunker, so a 10,000-row sheet would
  be one chunk far over the 320-token budget. Sheets are split into groups of 25 rows,
  each with its own heading and a repeated header row.
- **Very wide sheets.** Above 12 columns the rows become `**Label**: value` lists
  instead of a table, so every value keeps its column name.

## Scaling: read this before adding large documents

The retrieval settings in `server/rag/settings.py` were measured with
`eval/calibrate.py` against a corpus of roughly 150 chunks. Measured here: a 260-page
Word document converts and chunks in under a second and produces about **540 chunks**.
Three or four books would be **1,600–2,200 chunks**, a 10–15x increase on what the
settings were tuned for.

The conversion and chunking handle that size without trouble. What needs attention is
retrieval:

- **`prefetch_limit: 30`** is the recall ceiling — its own comment says RRF can only
  promote what a channel surfaced. At 150 chunks that is 20% of the corpus; at 2,000
  it is 1.5%. A correct answer ranked 34th on both channels is invisible. Likely needs
  to be 100–150 at book scale. Costs Qdrant query time, not LLM time.
- **`rerank_enabled: false`** — off because of ~450 ms per turn. At book scale ranking
  quality matters much more than it does now. **The settings file warns that
  `eval/calibrate.py` must be re-run after enabling it, because the thresholds differ
  per path.**
- **`dense_score_threshold: 0.72`** is deliberately permissive. More documents means
  more near-misses clearing it.

**Known issue — section expansion across files.** `Retriever._sections_to_complete`
takes the top chunk's top-level heading and calls `store.fetch_section(name)`, which
matches on heading alone, not on source file. Two files with a chapter called
"Introduction" or "Safety" will have their chunks pulled into the same context. This
cannot happen with a single corpus file; it becomes likely as soon as there are
several. The fix is to match on `(source, heading_path)`. It was left alone here to
avoid changing tuned retrieval behaviour on a live kiosk.

**Recommended before loading books:** add the documents to a copy of the corpus
(`MARI_RAG_CORPUS_DIR` overrides the directory), re-run `eval/calibrate.py` and
`eval/run_answers.py` against it, then apply the resulting settings. Changing these
numbers without re-measuring is guesswork.

## Adding another format

Write a converter in `server/rag/converters.py` returning markdown, add it to
`CONVERTERS`, and add the dependency to `requirements.txt`. `SUPPORTED_SUFFIXES` and
the upload portal both derive from that registry, so nothing else needs editing.
