"""Structure-aware chunking — the guarantees the old word-window chunker broke.

These are unit tests with an injected token counter, so they run without downloading a
600 MB embedding model. That is deliberate: chunking is the component most likely to be
edited, and a test suite that needs a model download is a test suite nobody runs.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.services.chunking import (  # noqa: E402
    approx_token_count,
    chunk_markdown,
    chunk_text,
    strip_frontmatter,
)

KB = Path(__file__).resolve().parent.parent / "server" / "data" / "mari_energies_knowledge_base.md"

TABLE_DOC = """# Doc

## Financials

Some lead-in prose about the numbers below.

| Year | Sales | Profit |
|------|-------|--------|
| 2021 | 100   | 40     |
| 2022 | 120   | 45     |
| 2023 | 150   | 55     |
| 2024 | 177   | 65     |

Trailing prose after the table.
"""


def _count(text: str) -> int:
    return approx_token_count(text)


def test_heading_path_is_inside_every_chunk() -> None:
    """The fix for the failure that motivated this: a chunk must carry its own context.

    "Bhitai-6" appears in this corpus only in a heading. If the heading is not in the
    chunk text, no question about Bhitai-6 can ever retrieve it.
    """
    chunks = chunk_markdown(KB.read_text(encoding="utf-8"), "kb.md", count_tokens=_count)
    assert chunks
    for chunk in chunks:
        if chunk.heading_path:
            assert chunk.text.startswith(chunk.heading_path)


def test_bhitai_is_reachable_by_text() -> None:
    chunks = chunk_markdown(KB.read_text(encoding="utf-8"), "kb.md", count_tokens=_count)
    assert any("Bhitai" in c.text for c in chunks)


def test_tables_are_never_split() -> None:
    """Half a table still looks authoritative, which makes it worse than no table."""
    chunks = chunk_markdown(TABLE_DOC, "t.md", chunk_tokens=40, min_tokens=1, count_tokens=_count)
    holders = [c for c in chunks if "| 2021 |" in c.text]
    assert len(holders) == 1, "the table was split across chunks"
    body = holders[0].text
    for year in ("2021", "2022", "2023", "2024"):
        assert f"| {year} |" in body
    assert "| Year | Sales | Profit |" in body


def test_oversized_table_is_emitted_whole() -> None:
    rows = "\n".join(f"| {i} | {i*10} | {i*3} |" for i in range(200))
    doc = f"# D\n\n## T\n\n| a | b | c |\n|---|---|---|\n{rows}\n"
    chunks = chunk_markdown(doc, "t.md", chunk_tokens=50, min_tokens=1, count_tokens=_count)
    holders = [c for c in chunks if "| 199 |" in c.text]
    assert len(holders) == 1
    assert "| 0 |" in holders[0].text


def test_code_fences_are_not_split_and_headings_inside_them_are_ignored() -> None:
    doc = "# D\n\n## S\n\n```bash\n# not a heading\necho one\necho two\n```\n\ntail text\n"
    chunks = chunk_markdown(doc, "c.md", chunk_tokens=12, min_tokens=1, count_tokens=_count)
    holders = [c for c in chunks if "echo one" in c.text]
    assert len(holders) == 1
    assert "echo two" in holders[0].text
    assert not any(c.heading_path.endswith("not a heading") for c in chunks)


def test_frontmatter_is_stripped() -> None:
    doc = "---\ntitle: X\nauthor: Y\n---\n\n# D\n\n## S\n\nbody text here\n"
    assert "author" not in strip_frontmatter(doc)
    assert all("author: Y" not in c.text for c in chunk_markdown(doc, "f.md", count_tokens=_count))


def test_chunks_respect_the_token_budget() -> None:
    chunks = chunk_markdown(
        KB.read_text(encoding="utf-8"), "kb.md", chunk_tokens=320, count_tokens=_count
    )
    # Atomic blocks (whole tables) are allowed to exceed the budget by design; nothing
    # else may. Splitting a table is the worse failure.
    for chunk in chunks:
        if "|---" not in chunk.text.replace(" ", ""):
            assert chunk.token_count <= 320 * 1.6, chunk.heading_path


def test_no_runt_chunks() -> None:
    """Sub-30-token chunks embed as noise and score deceptively high on short queries."""
    chunks = chunk_markdown(
        KB.read_text(encoding="utf-8"), "kb.md", min_tokens=30, count_tokens=_count
    )
    assert all(c.token_count >= 30 for c in chunks)


def test_short_sections_survive_rather_than_being_dropped() -> None:
    """A two-line section is legitimate content; the min-token rule must not delete it."""
    doc = "# D\n\n## Only Section\n\nShort.\n"
    chunks = chunk_markdown(doc, "s.md", min_tokens=30, count_tokens=_count)
    assert len(chunks) == 1
    assert "Short." in chunks[0].text


def test_single_h1_title_is_dropped_from_the_path() -> None:
    doc = "# The Title\n\n## One\n\nbody one here\n\n## Two\n\nbody two here\n"
    chunks = chunk_markdown(doc, "d.md", min_tokens=1, count_tokens=_count)
    assert all(not c.heading_path.startswith("The Title") for c in chunks)
    assert {c.heading_path for c in chunks} == {"One", "Two"}


def test_multiple_h1s_are_kept_as_real_sections() -> None:
    doc = "# Alpha\n\nbody alpha\n\n# Beta\n\nbody beta\n"
    chunks = chunk_markdown(doc, "d.md", min_tokens=1, count_tokens=_count)
    assert {c.heading_path for c in chunks} == {"Alpha", "Beta"}


def test_plain_text_splits_on_paragraphs() -> None:
    doc = "\n\n".join(f"Paragraph number {i} with a little content in it." for i in range(30))
    chunks = chunk_text(doc, "p.txt", chunk_tokens=40, min_tokens=1, count_tokens=_count)
    assert len(chunks) > 1
    # No chunk may begin mid-sentence — that is what the word-window chunker did.
    assert all(c.text.lstrip().startswith("Paragraph") for c in chunks)
