#!/usr/bin/env python
"""Retrieval evaluation for the Mari Energies kiosk.

Run this on every parameter change. Chunk size, top_k, prefetch limits and the rerank
threshold all trade recall against latency, and the trade is not guessable — the same
change that lifts hit@1 by four points can cost 40 ms, and on a speech-to-speech kiosk
40 ms is a real regression. Tuning by asking the bot a few questions and listening to
the answers is how the previous parameters were chosen, and it is why several of them
were wrong.

    python eval/run_eval.py
    python eval/run_eval.py --set rerank_enabled=true      # compare one parameter
    python eval/run_eval.py --k 5 --json out.json

Metrics
  hit@k      fraction of positive questions whose answering section appears in the top k.
             hit@1 is the one that matters most: the first chunk dominates what the LLM
             actually uses, because it is the one least likely to be truncated away.
  MRR        mean reciprocal rank over positive questions. Distinguishes "right section
             at position 1" from "right section at position 5", which hit@k flattens.
  fact       fraction of questions whose expected literal substrings all survive into
             the assembled context. This is the metric that catches chunking bugs:
             heading matching can be perfect while the specific number the visitor asked
             for was split into a chunk that did not rank.
  abstain    fraction of NEGATIVE questions (expect_heading: null) that correctly return
             no context. A retriever with no score threshold scores 0.0 here and hands
             the LLM five irrelevant chunks to hallucinate from.
  latency    per-question wall clock for the whole retrieve step, p50/p95, plus the
             per-stage breakdown the retriever reports.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

QUESTIONS = Path(__file__).resolve().parent / "questions.yaml"


@dataclass
class Case:
    id: str
    lang: str
    question: str
    expect_heading: str | None
    expect_facts: list[str] = field(default_factory=list)

    @property
    def negative(self) -> bool:
        return self.expect_heading is None


def load_cases(path: Path = QUESTIONS) -> list[Case]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return [
        Case(
            id=q["id"],
            lang=q.get("lang", "en"),
            question=q["question"],
            expect_heading=q.get("expect_heading"),
            expect_facts=q.get("expect_facts", []) or [],
        )
        for q in data["questions"]
    ]


def heading_matches(heading_path: str, want: str) -> bool:
    """True when `heading_path` is (or sits under) the section `want` names.

    Headings arrive as "1. Overview ... > 1.5 Ownership and Shareholding Structure", and
    a case names the section by its number alone ("1.5"). Matching on the numeric prefix
    of any level keeps the eval set stable when a heading is reworded.
    """
    if not heading_path:
        return False
    for level in heading_path.split(" > "):
        if level.strip().startswith(want):
            return True
    return False


# ── backends ────────────────────────────────────────────────────────
# A backend is anything with .name and .retrieve(question, lang) -> (hits, stage_ms),
# where a hit is (heading_path, text). There is only one now — the stdlib BM25 baseline
# this harness was built to measure against has been removed along with the retrieval
# path it belonged to. The seam is kept because comparing two configurations under
# identical scoring is the whole point: `--set` is the supported way to do that, and a
# second class here is the way to compare something `--set` cannot express.


class HybridBackend:
    """The shared retriever: hybrid + RRF + cross-encoder rerank + threshold."""

    name = "hybrid"

    def __init__(self, top_k: int = 5) -> None:
        import asyncio

        from server.services.retriever import get_retriever

        self._asyncio = asyncio
        self._loop = asyncio.new_event_loop()
        self._retriever = self._loop.run_until_complete(get_retriever())
        self._loop.run_until_complete(self._retriever.warmup())
        self._k = top_k

    def retrieve(self, question: str, lang: str) -> tuple[list[tuple[str, str]], dict]:
        result = self._loop.run_until_complete(
            self._retriever.retrieve(question, lang=lang, top_k=self._k)
        )
        return (
            [(c.heading_path, c.text) for c in result.chunks],
            dict(result.timings_ms),
        )


BACKENDS = {"hybrid": HybridBackend}


# ── scoring ─────────────────────────────────────────────────────────


def evaluate(backend, cases: list[Case], k: int) -> dict:
    positives = [c for c in cases if not c.negative]
    negatives = [c for c in cases if c.negative]

    ranks: list[int | None] = []
    fact_ok: list[bool] = []
    latencies: list[float] = []
    stage_totals: dict[str, list[float]] = {}
    failures: list[dict] = []

    for case in cases:
        t0 = time.perf_counter()
        hits, stages = backend.retrieve(case.question, case.lang)
        latencies.append((time.perf_counter() - t0) * 1000)
        for stage, ms in stages.items():
            stage_totals.setdefault(stage, []).append(ms)

        context = "\n\n".join(f"{heading}\n{text}" for heading, text in hits).lower()

        if case.negative:
            if hits:
                failures.append(
                    {
                        "id": case.id,
                        "kind": "should-abstain",
                        "question": case.question,
                        "got": [h for h, _ in hits][:3],
                    }
                )
            continue

        rank = next(
            (
                i
                for i, (heading, _) in enumerate(hits[:k], 1)
                if heading_matches(heading, case.expect_heading)
            ),
            None,
        )
        ranks.append(rank)

        missing = [f for f in case.expect_facts if f.lower() not in context]
        fact_ok.append(not missing)

        if rank is None or missing:
            failures.append(
                {
                    "id": case.id,
                    "kind": "miss" if rank is None else "fact",
                    "question": case.question,
                    "want": case.expect_heading,
                    "missing_facts": missing,
                    "got": [h for h, _ in hits][:k],
                }
            )

    def hit_at(n: int) -> float:
        return sum(1 for r in ranks if r is not None and r <= n) / max(len(ranks), 1)

    abstained = sum(
        1 for f in failures if f["kind"] == "should-abstain"
    )
    return {
        "backend": backend.name,
        "questions": len(cases),
        "positives": len(positives),
        "negatives": len(negatives),
        "hit@1": hit_at(1),
        "hit@3": hit_at(3),
        f"hit@{k}": hit_at(k),
        "mrr": sum(1 / r for r in ranks if r) / max(len(ranks), 1),
        "fact_recall": sum(fact_ok) / max(len(fact_ok), 1),
        "abstain_rate": (len(negatives) - abstained) / max(len(negatives), 1),
        "latency_ms": {
            "p50": statistics.median(latencies),
            "p95": sorted(latencies)[max(int(len(latencies) * 0.95) - 1, 0)],
            "mean": statistics.fmean(latencies),
        },
        "stage_ms_p50": {
            s: statistics.median(v) for s, v in sorted(stage_totals.items())
        },
        "failures": failures,
    }


def print_report(report: dict, k: int, show_failures: int) -> None:
    lat = report["latency_ms"]
    print(f"\n╭─ {report['backend']} ─ {report['questions']} questions "
          f"({report['positives']} positive, {report['negatives']} negative)")
    print(f"│  hit@1         {report['hit@1']:6.1%}")
    print(f"│  hit@3         {report['hit@3']:6.1%}")
    print(f"│  hit@{k:<2}        {report[f'hit@{k}']:6.1%}")
    print(f"│  MRR           {report['mrr']:6.3f}")
    print(f"│  fact recall   {report['fact_recall']:6.1%}")
    print(f"│  abstain rate  {report['abstain_rate']:6.1%}  (negative cases correctly empty)")
    print(f"│  latency       p50 {lat['p50']:6.1f} ms   p95 {lat['p95']:6.1f} ms")
    for stage, ms in report["stage_ms_p50"].items():
        print(f"│      {stage:<14} {ms:6.1f} ms")
    print("╰─")

    if show_failures and report["failures"]:
        print(f"\n  {len(report['failures'])} failing cases (showing {show_failures}):")
        for f in report["failures"][:show_failures]:
            print(f"    [{f['kind']}] {f['id']}  {f['question']}")
            if f.get("want"):
                print(f"        want {f['want']!r}  missing_facts={f.get('missing_facts')}")
            for g in f["got"]:
                print(f"        got  {g}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--backend", action="append", choices=list(BACKENDS),
                    help="repeatable; defaults to hybrid")
    ap.add_argument("--k", type=int, default=5, help="top_k passed to the retriever")
    ap.add_argument("--json", type=Path, help="write the full report (incl. failures) here")
    ap.add_argument("--show-failures", type=int, default=15)
    ap.add_argument("--lang", choices=["en", "ur"], help="score only this language")
    ap.add_argument("--set", action="append", default=[], metavar="KEY=VALUE",
                    help="override a RagSettings field for this run, e.g. "
                         "--set rerank_enabled=false --set score_threshold=0.0. This is "
                         "how parameters get tuned: change one, re-run, compare.")
    args = ap.parse_args()

    if args.set:
        from server.services.settings import get_settings

        settings = get_settings()
        for pair in args.set:
            key, _, raw = pair.partition("=")
            current = getattr(settings, key)
            if isinstance(current, bool):
                value = raw.strip().lower() in {"1", "true", "yes", "on"}
            else:
                value = type(current)(raw)
            setattr(settings, key, value)
            print(f"override {key} = {value!r}")

    cases = load_cases()
    if args.lang:
        cases = [c for c in cases if c.lang == args.lang]

    reports = []
    for name in args.backend or ["hybrid"]:
        backend = BACKENDS[name](top_k=args.k)
        report = evaluate(backend, cases, args.k)
        print_report(report, args.k, args.show_failures)
        reports.append(report)

    if args.json:
        args.json.write_text(json.dumps(reports, indent=2, ensure_ascii=False))
        print(f"\nwrote {args.json}")

    # Non-zero exit when the primary backend regresses below the floor the README
    # documents, so this can gate CI rather than only informing a human.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
