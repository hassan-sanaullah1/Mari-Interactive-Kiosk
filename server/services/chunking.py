"""Structure-aware chunking.

    * Every chunk carries its full heading path, so an isolated chunk still says what
      it is about ("Bhitai-6" appears only in a heading).
    * Tables are atomic: half a table still looks authoritative.
    * Oversized paragraphs are split at sentence ends, not mid-sentence.

Sizes are in tokens from the embedding model's tokenizer, injected as ``count_tokens`` so
chunking is testable without downloading the model.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable

CountTokens = Callable[[str], int]


@dataclass
class Chunk:
    """One retrievable unit. `text` is what gets embedded and what the LLM sees."""

    text: str
    source: str
    heading_path: str
    chunk_index: int
    token_count: int
    metadata: dict = field(default_factory=dict)


def approx_token_count(text: str) -> int:
    """Fallback token estimate used only when no real tokenizer is supplied.

    Deliberately over-estimates (~1.35 tokens per whitespace word). Under-estimating
    silently produces chunks that exceed the model's input limit and get truncated,
    which is invisible; over-estimating only makes chunks slightly smaller than target.
    """
    return max(1, int(len(text.split()) * 1.35))


# ── block-level markdown parsing ────────────────────────────────────
# Only needs to know where it is unsafe to cut: headings, fences, tables, paragraphs.

_FRONTMATTER_RE = re.compile(r"\A---\s*\n.*?\n---\s*\n", re.DOTALL)
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
_FENCE_RE = re.compile(r"^\s*(```|~~~)")
_TABLE_ROW_RE = re.compile(r"^\s*\|")
_TABLE_SEP_RE = re.compile(r"^\s*\|?[\s:|-]*-{2,}[\s:|-]*\|?\s*$")
# Abbreviations whose period is not a sentence end ("Lt. Gen. Anwar Ali Hyder"). Matched
# as a group-less first branch, since `re` lookbehind must be fixed-width; only the second
# branch (the real boundary, including ۔ and ؟) splits.
_ABBREV = (
    r"Lt|Gen|Col|Brig|Maj|Capt|Sgt|Hon|Dr|Mr|Mrs|Ms|Prof|St"
    r"|No|Nos|Rs|approx|est|etc|vs|viz"
    r"|Inc|Ltd|Pvt|Co|Corp|Bros|Jr|Sr"
    r"|e\.g|i\.e|cf|Fig|Sec|Vol|Ch|pp"
)
_SENTENCE_SPLIT_RE = re.compile(rf"(?:\b(?:{_ABBREV})\.\s+)|(?<=[.!?۔؟])(\s+)")


def split_sentences(text: str) -> list[str]:
    """Split on sentence ends, treating a known abbreviation's period as internal."""
    parts: list[str] = []
    last = 0
    for m in _SENTENCE_SPLIT_RE.finditer(text):
        if m.group(1) is None:
            continue  # an abbreviation, not a boundary
        parts.append(text[last:m.start(1)])
        last = m.end(1)
    parts.append(text[last:])
    return [p for p in parts if p]


_TOP_HEADING_RE = re.compile(r"^#\s+.+$", re.MULTILINE)


@dataclass
class _Block:
    text: str
    atomic: bool = False  # never split this block internally


def strip_frontmatter(md: str) -> str:
    return _FRONTMATTER_RE.sub("", md, count=1)


def _blocks(body: str) -> list[_Block]:
    """Split a section body into paragraph / table / fenced-code blocks.

    Tables and fences come back marked atomic. Everything else is a paragraph that may
    be split further at sentence boundaries if it is over the limit on its own.
    """
    out: list[_Block] = []
    lines = body.splitlines()
    buf: list[str] = []

    def flush_paragraph() -> None:
        if text := "\n".join(buf).strip():
            out.append(_Block(text))
        buf.clear()

    i = 0
    while i < len(lines):
        line = lines[i]

        if _FENCE_RE.match(line):
            flush_paragraph()
            fence = _FENCE_RE.match(line).group(1)
            block = [line]
            i += 1
            while i < len(lines):
                block.append(lines[i])
                if lines[i].strip().startswith(fence):
                    i += 1
                    break
                i += 1
            else:
                # Unterminated fence: treat what we have as the block rather than
                # dropping it. Malformed markdown must not lose content.
                pass
            out.append(_Block("\n".join(block), atomic=True))
            continue

        # A table is a run of pipe rows. Require the second line to be the separator so
        # a stray sentence containing "|" is not mistaken for one.
        if _TABLE_ROW_RE.match(line) and i + 1 < len(lines) and _TABLE_SEP_RE.match(lines[i + 1]):
            flush_paragraph()
            block = []
            while i < len(lines) and (_TABLE_ROW_RE.match(lines[i]) or _TABLE_SEP_RE.match(lines[i])):
                block.append(lines[i])
                i += 1
            out.append(_Block("\n".join(block), atomic=True))
            continue

        if not line.strip():
            flush_paragraph()
        else:
            buf.append(line)
        i += 1

    flush_paragraph()
    return out


def _sections(md: str) -> list[tuple[str, str]]:
    """Markdown -> [(heading path, body)], one entry per heading.

    The heading path is the full ancestry joined with " > " ("1. Overview > 1.5
    Ownership and Shareholding Structure"), which is what makes an isolated chunk
    self-describing. Content appearing before the first heading is kept under the
    document's own name rather than discarded.
    """
    sections: list[tuple[str, str]] = []
    stack: list[tuple[int, str]] = []
    heading_path = ""
    body: list[str] = []
    # A single H1 is the document title, already in every chunk's `source`.
    drop_h1 = len(_TOP_HEADING_RE.findall(strip_frontmatter(md))) == 1

    def flush() -> None:
        if "".join(body).strip():
            sections.append((heading_path, "\n".join(body).strip()))

    in_fence = False
    fence_marker = ""
    for line in strip_frontmatter(md).splitlines():
        # Headings inside a fenced code block are code, not headings. Missing this
        # turns every "# comment" in a shell example into a section boundary.
        if m := _FENCE_RE.match(line):
            if not in_fence:
                in_fence, fence_marker = True, m.group(1)
            elif line.strip().startswith(fence_marker):
                in_fence = False
            body.append(line)
            continue

        m = _HEADING_RE.match(line) if not in_fence else None
        if not m:
            body.append(line)
            continue

        flush()
        body = []
        level, title = len(m.group(1)), m.group(2).strip()
        while stack and stack[-1][0] >= level:
            stack.pop()
        stack.append((level, title))
        path = [t for lvl, t in stack if not (drop_h1 and lvl == 1)]
        heading_path = " > ".join(path)

    flush()
    return sections


# ── chunk assembly ──────────────────────────────────────────────────


def _split_oversized(text: str, limit: int, count: CountTokens) -> list[str]:
    """Break a single over-limit paragraph at sentence boundaries, never mid-sentence."""
    sentences = split_sentences(text)
    parts: list[str] = []
    buf: list[str] = []
    size = 0
    for sentence in sentences:
        n = count(sentence)
        if buf and size + n > limit:
            parts.append(" ".join(buf))
            buf, size = [], 0
        buf.append(sentence)
        size += n
    if buf:
        parts.append(" ".join(buf))
    # A single sentence longer than the limit is left intact. Cutting it would produce
    # exactly the mid-sentence fragment this function exists to avoid, and the embedding
    # model truncating its tail is the lesser harm.
    return parts or [text]


def _overlap_tail(text: str, overlap: int, count: CountTokens) -> str:
    """The last ~`overlap` tokens of `text`, cut at a sentence boundary.

    Overlap exists so a fact sitting on a chunk boundary is retrievable from either
    side. Cutting it mid-sentence would defeat that — the carried fragment reads as
    noise and drags the next chunk's embedding toward nothing in particular.
    """
    if overlap <= 0:
        return ""
    sentences = split_sentences(text)
    tail: list[str] = []
    size = 0
    for sentence in reversed(sentences):
        n = count(sentence)
        if tail and size + n > overlap:
            break
        tail.insert(0, sentence)
        size += n
    return " ".join(tail)


def chunk_markdown(
    md: str,
    source: str,
    *,
    chunk_tokens: int = 320,
    overlap_tokens: int = 48,
    min_tokens: int = 30,
    count_tokens: CountTokens | None = None,
    metadata: dict | None = None,
) -> list[Chunk]:
    """Split markdown into retrievable chunks that respect its structure."""
    count = count_tokens or approx_token_count
    chunks: list[Chunk] = []

    for heading_path, body in _sections(md):
        prefix = f"{heading_path}\n\n" if heading_path else ""
        # The heading path is embedded too, so it counts against the budget.
        budget = max(min_tokens, chunk_tokens - count(prefix))

        pieces: list[str] = []
        for block in _blocks(body):
            if block.atomic or count(block.text) <= budget:
                pieces.append(block.text)
            else:
                pieces.extend(_split_oversized(block.text, budget, count))

        section_chunks: list[str] = []
        buf: list[str] = []
        size = 0
        for piece in pieces:
            n = count(piece)
            # An atomic block over budget gets its own chunk rather than being split or
            # dropped: a whole oversized table is useful, half a table is misleading.
            if buf and size + n > budget:
                section_chunks.append("\n\n".join(buf))
                carry = _overlap_tail(buf[-1], overlap_tokens, count)
                buf = [carry] if carry and n + count(carry) <= budget else []
                size = count(carry) if buf else 0
            buf.append(piece)
            size += n
        if buf:
            section_chunks.append("\n\n".join(buf))

        # Fold a runt tail into its predecessor instead of dropping it. Dropping would
        # lose real content — several sections in this corpus are two lines long, and a
        # blanket "drop under 30 tokens" rule deletes them from the index entirely.
        merged: list[str] = []
        for text in section_chunks:
            if merged and count(text) < min_tokens:
                merged[-1] = f"{merged[-1]}\n\n{text}"
            else:
                merged.append(text)

        for text in merged:
            full = f"{prefix}{text}".strip()
            n = count(full)
            # Only now, with the heading path attached, is it fair to call a chunk too
            # small: a two-line section plus its path is a legitimate retrieval target.
            if n < min_tokens and len(merged) > 1:
                continue
            chunks.append(
                Chunk(
                    text=full,
                    source=source,
                    heading_path=heading_path,
                    chunk_index=len(chunks),
                    token_count=n,
                    metadata=dict(metadata or {}),
                )
            )

    return chunks


def chunk_text(
    text: str,
    source: str,
    *,
    chunk_tokens: int = 320,
    overlap_tokens: int = 48,
    min_tokens: int = 30,
    count_tokens: CountTokens | None = None,
    metadata: dict | None = None,
) -> list[Chunk]:
    """Chunk unstructured text (and PDF output) on paragraph, then sentence, boundaries.

    PDF extraction gives blank-line-separated paragraphs and no reliable heading
    structure, so there is nothing to build a heading path from — but paragraph
    boundaries are still real, and splitting on them rather than on a word count is the
    whole of the improvement available here.
    """
    count = count_tokens or approx_token_count
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]

    pieces: list[str] = []
    for para in paragraphs:
        if count(para) <= chunk_tokens:
            pieces.append(para)
        else:
            pieces.extend(_split_oversized(para, chunk_tokens, count))

    chunks: list[Chunk] = []
    buf: list[str] = []
    size = 0

    def emit() -> None:
        body = "\n\n".join(buf).strip()
        if body and count(body) >= min_tokens:
            chunks.append(
                Chunk(
                    text=body,
                    source=source,
                    heading_path="",
                    chunk_index=len(chunks),
                    token_count=count(body),
                    metadata=dict(metadata or {}),
                )
            )

    for piece in pieces:
        n = count(piece)
        if buf and size + n > chunk_tokens:
            emit()
            carry = _overlap_tail(buf[-1], overlap_tokens, count)
            buf = [carry] if carry else []
            size = count(carry) if buf else 0
        buf.append(piece)
        size += n
    emit()
    return chunks
