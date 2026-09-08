#!/usr/bin/env python
"""Calibrate the relevance threshold against the eval set.

The threshold is the only parameter in the system whose job is to make retrieval return
*nothing*, and it is therefore the only one that cannot be tuned by looking at hit@k —
raising it can only ever lower hit@k, while the thing it buys (not answering questions
the corpus does not cover) is invisible to that metric.

So it is calibrated directly: run every question once, record the top chunk's score and
whether the question is answerable, then sweep the threshold over the recorded scores.
No model re-runs per candidate threshold, and the trade is explicit — for each value,
how many answerable questions go unanswered, and how many unanswerable ones get answered
anyway.

    python eval/calibrate.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from eval.run_eval import heading_matches, load_cases  # noqa: E402
from server.services.retriever import get_retriever  # noqa: E402
from server.services.settings import get_settings  # noqa: E402


async def main() -> int:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--set", action="append", default=[], metavar="KEY=VALUE",
                    help="override a RagSettings field, e.g. --set rerank_skip_for_urdu=false")
    ap.add_argument("--lang", choices=["en", "ur"])
    args = ap.parse_args()

    settings = get_settings()
    for pair in args.set:
        key, _, raw = pair.partition("=")
        current = getattr(settings, key)
        value = (raw.strip().lower() in {"1", "true", "yes", "on"}) if isinstance(current, bool) \
            else type(current)(raw)
        setattr(settings, key, value)
        print(f"override {key} = {value!r}")
    # Collect scores with the gates wide open — a gated-away chunk has no score to
    # record, which would make every threshold look equally good.
    settings.score_threshold = 0.0
    settings.dense_score_threshold = 0.0

    retriever = await get_retriever()
    await retriever.warmup()
    cases = load_cases()
    if args.lang:
        cases = [c for c in cases if c.lang == args.lang]

    rows = []
    for case in cases:
        result = await retriever.retrieve(case.question, lang=case.lang, use_cache=False)
        top = result.chunks[0] if result.chunks else None
        rows.append({
            "lang": case.lang,
            "negative": case.negative,
            "score": top.score if top else 0.0,
            "reranked": top.reranked if top else False,
            "correct": bool(
                top and not case.negative
                and heading_matches(top.heading_path, case.expect_heading)
            ),
        })

    for reranked in (True, False):
        subset = [r for r in rows if r["reranked"] == reranked]
        if not subset:
            continue
        name = "rerank probability (score_threshold)" if reranked else "dense cosine similarity (dense_score_threshold)"
        positives = [r for r in subset if not r["negative"]]
        negatives = [r for r in subset if r["negative"]]
        print(f"\n╭─ {name} — {len(positives)} answerable, {len(negatives)} unanswerable")
        print(f"│  {'thresh':>8s}  {'answerable kept':>16s}  {'unanswerable blocked':>21s}")
        candidates = sorted({round(r["score"], 4) for r in subset} | {0.0})
        # Show a readable ladder rather than every distinct score.
        step = max(1, len(candidates) // 14)
        for t in candidates[::step]:
            kept = sum(1 for r in positives if r["score"] >= t) / max(len(positives), 1)
            blocked = sum(1 for r in negatives if r["score"] < t) / max(len(negatives), 1)
            print(f"│  {t:8.4f}  {kept:15.1%}  {blocked:20.1%}")
        if positives:
            lo = min(r["score"] for r in positives if r["correct"]) if any(
                r["correct"] for r in positives) else 0.0
            print(f"│  lowest score among CORRECT top-1 hits: {lo:.4f}")
        if negatives:
            hi = max(r["score"] for r in negatives)
            print(f"│  highest score among unanswerable questions: {hi:.4f}")
            print(f"│  -> any threshold in ({hi:.4f}, {lo:.4f}) separates them cleanly"
                  if hi < lo else "│  -> the two overlap; no threshold separates them perfectly")
        print("╰─")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
