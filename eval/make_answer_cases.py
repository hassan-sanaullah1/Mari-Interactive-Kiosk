#!/usr/bin/env python
"""Drafts eval/answers.yaml from the tester's evaluation spreadsheet.

The tester graded 342 English questions in "MARI kiosk Evaluation - Sheet1 (1).csv"
against branch refactor/modular-monolith-architecture. This turns the graded rows into
answer-eval cases, carrying their verdict and their reply across so a new run can be
compared with the human one case by case.

It prints YAML to stdout and never writes a file. The `require` lists it emits are a
*draft*: for 24 of the 32 failures the Tester Notes name the missing fact outright
("Fellow Chartered Accountant - Not mentioned") and mine cleanly, but the rest need a
human, and every draft needs reviewing before a number from it means anything. Printing
to stdout is what keeps a second run from overwriting that review.

    python eval/make_answer_cases.py > eval/answers.yaml            # the 32 failures
    python eval/make_answer_cases.py --only-graded > /tmp/128.yaml  # + the 96 Matched
    python eval/make_answer_cases.py --all > /tmp/342.yaml          # every row
"""

from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CSV_PATH = ROOT / "MARI kiosk Evaluation - Sheet1 (1).csv"

# The tester logged speech complaints in the same column as missing facts. Content is
# the only thing scored here, so a fragment about how a word sounded is not a
# requirement — mining it would fail every case on a fact nobody asked the model for.
_SPEECH = re.compile(r"pronounc|pronounce|spoke|spoken|said to be|accent|urdu", re.I)
# "Fellow Chartered Accountant  -  Not mentioned" / "35+ years at KPMG - Not Menioned"
_NOT_MENTIONED = re.compile(r"[\s\-–—]*not\s*men[it]?ioned\s*$", re.I)
_SPLIT = re.compile(r"[\n\r]+|\t+|\s{4,}")

_QUOTED = re.compile(r"[\"“”']([^\"“”']{3,60})[\"“”']")
_NUMBERS = re.compile(r"\b\d[\d,.]*\s*(?:%|percent|bn|billion|million)?\b")
_PROPER = re.compile(r"\b(?:[A-Z][\w&.\-]*(?:\s+(?:of|and|&|the)\s+)?){2,}")


def mine_notes(notes: str) -> list[str]:
    """The facts the tester said were missing, as required-fact drafts."""
    out = []
    for frag in _SPLIT.split(notes or ""):
        frag = _NOT_MENTIONED.sub("", frag.strip(" \t-–—:")).strip()
        if len(frag) < 3 or _SPEECH.search(frag):
            continue
        if frag.lower() in {"not mentioned", "not menioned", "missing"}:
            continue
        out.append(frag)
    return out


def atoms(expected: str) -> list[str]:
    """Candidate required facts pulled out of the Expected Answer, for review."""
    found = []
    for pat in (_QUOTED, _NUMBERS, _PROPER):
        for m in pat.finditer(expected or ""):
            frag = m.group(1 if pat is _QUOTED else 0).strip(" .,;:")
            if len(frag) > 2 and frag.lower() not in {"the", "and"}:
                found.append(frag)
    seen, out = set(), []
    for f in found:
        if f.lower() not in seen:
            seen.add(f.lower())
            out.append(f)
    return out[:14]


def _q(text: str) -> str:
    """A YAML double-quoted scalar."""
    return '"' + (text or "").replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ") + '"'


def draft_case(row: dict) -> str:
    status = (row["Status"] or "").strip()
    notes = (row["Tester Notes"] or "").strip()
    mined = mine_notes(notes)
    ref = (row["Ref #"] or "").strip().lstrip("§")

    lines = [
        f"  - id: {row['Test Case ID'].strip()}",
        "    lang: en",
        f"    depth: {_q((row['Depth Level'] or '').strip())}",
        f"    section: {_q(ref)}",
        f"    question: {_q((row['Test Question'] or '').strip())}",
        f"    expected_answer: {_q((row['Expected Answer'] or '').strip())}",
        f"    baseline_grade: {status or 'null'}",
        f"    baseline_reply: {_q((row['Actual Answer'] or '').strip())}",
    ]
    if notes:
        lines.append(f"    baseline_notes: {_q(notes)}")
    lines.append("    require:")
    for fact in mined:
        lines.append(f"      - [{_q(fact)}]")
    if not mined:
        lines.append("      []  # REVIEW: no usable tester notes — author from expected_answer")
    cands = [c for c in atoms(row["Expected Answer"]) if c not in mined]
    if cands:
        lines.append("    # candidates (review): " + " | ".join(cands))
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--csv", type=Path, default=CSV_PATH)
    ap.add_argument("--status", default="Partial,Not Matched",
                    help='comma-separated Status values to keep; "all" keeps every row')
    ap.add_argument("--only-graded", action="store_true",
                    help="every row the tester graded, including Matched")
    ap.add_argument("--all", action="store_true", help="every row, graded or not")
    ap.add_argument("--ids", help="comma-separated Test Case IDs")
    args = ap.parse_args()

    rows = list(csv.DictReader(args.csv.read_text(encoding="utf-8-sig").splitlines()))
    if args.ids:
        want = {i.strip() for i in args.ids.split(",")}
        rows = [r for r in rows if r["Test Case ID"].strip() in want]
    elif args.all:
        pass
    elif args.only_graded:
        rows = [r for r in rows if (r["Status"] or "").strip()]
    elif args.status != "all":
        keep = {s.strip().casefold() for s in args.status.split(",")}
        rows = [r for r in rows if (r["Status"] or "").strip().casefold() in keep]

    print("# Answer-level eval cases, drafted from the tester's spreadsheet by")
    print("# eval/make_answer_cases.py. `require` entries are reviewed by hand: each is a")
    print("# list of accepted surface forms of ONE required fact (OR within an entry, AND")
    print("# across entries). See eval/factcheck.py for how they are matched.")
    print(f"# {len(rows)} cases.")
    print("cases:")
    for row in rows:
        print(draft_case(row))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
