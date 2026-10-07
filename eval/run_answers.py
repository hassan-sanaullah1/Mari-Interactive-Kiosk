#!/usr/bin/env python
"""Answer-level evaluation: does the kiosk's reply actually carry the facts it needs?

eval/run_eval.py scores *retrieval* — whether the right section reached the model. This
scores what the visitor hears. They fail differently: the tester's evaluation is full of
replies that retrieved the right section and then left half of it out, and no retrieval
metric can see that.

Each case in eval/answers.yaml carries the facts the reply must contain, the tester's
grade, and the reply they graded. So a run says three things:

  grade        Matched / Partial / Not Matched, on the tester's own scale.
  cause        for every MISSING fact, whether it was absent from the retrieved context
               (`retrieval`), present in the context and dropped by the model
               (`generation`), or lost to the reply token cap (`cap`). This is what
               decides whether a failure is a chunking problem or a prompt problem.
  FIXED/WORSE  the same case against the tester's verdict, so a regression is visible.

    python eval/run_answers.py --score-only          # no LLM: scores the tester's replies
    python eval/run_answers.py --repeat 3            # the graded run
    python eval/run_answers.py --system-prompt OLD.md   # A/B one prompt against another
    python eval/run_answers.py --baseline run-a.jsonl   # one run against another

``--score-only`` is the first thing to run and needs no services: it scores the replies
already in the fixture and prints the derived grade beside the tester's. Until those
agree, nothing a live run reports about a regression can be trusted.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import statistics
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from eval.factcheck import score  # noqa: E402

CASES = ROOT / "eval" / "answers.yaml"
GRADE_ORDER = {"Not Matched": 0, "Partial": 1, "Matched": 2}


@dataclass
class AnswerCase:
    id: str
    question: str
    lang: str = "en"
    depth: str = ""
    section: str = ""
    expected_answer: str = ""
    baseline_grade: str | None = None
    baseline_reply: str = ""
    baseline_notes: str = ""
    require: list = field(default_factory=list)
    optional: list = field(default_factory=list)


def load_cases(path: Path = CASES, ids: str | None = None,
               statuses: str | None = None) -> list[AnswerCase]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    cases = [AnswerCase(**c) for c in data["cases"]]
    if ids:
        want = {i.strip() for i in ids.split(",")}
        cases = [c for c in cases if c.id in want]
    if statuses and statuses != "all":
        keep = {s.strip().casefold() for s in statuses.split(",")}
        cases = [c for c in cases if (c.baseline_grade or "").casefold() in keep]
    return cases


# ── the live path ───────────────────────────────────────────────────
# NOTE: this reproduces server.agent.responder.respond() rather than calling it, because
# complete() throws away the `usage` and `finish_reason` that cap detection needs. If
# respond() grows a step, this has to grow with it.


async def complete_verbose(messages: list[dict], max_tokens: int) -> tuple[str, dict, str]:
    """One non-streamed reply, keeping the usage and finish_reason that complete() drops."""
    import httpx

    from server.providers import llm

    payload = llm._payload(messages, max_tokens, stream=False)
    async with httpx.AsyncClient(timeout=llm.COMPLETE_TIMEOUT) as client:
        r = await client.post(f"{__import__('server.config', fromlist=['x']).LLM_BASE}"
                              "/chat/completions", headers=llm._headers(), json=payload)
        r.raise_for_status()
        body = r.json()
    choice = body["choices"][0]
    return (choice["message"]["content"].strip(),
            body.get("usage") or {},
            choice.get("finish_reason") or "")


class LiveRunner:
    """Drives one case through production retrieval, prompt assembly and the LLM."""

    def __init__(self, avatar: str = "female") -> None:
        self.avatar = avatar
        self._captured = None

    async def start(self, ingest: bool = False) -> None:
        from server import rag

        await rag.startup(ingest=ingest)
        health = await rag.health()
        if not rag.enabled() or health.get("state") != "ready":
            raise SystemExit(f"RAG is not ready: {health}. Start qdrant and ingest first.")
        self._rag = rag
        self._real_retrieve = rag.retrieve

        async def capturing(text, lang="en", history=None):
            result = await self._real_retrieve(text, lang, history)
            self._captured = result
            return result

        rag.retrieve = capturing  # rag.system_prompt looks this up on the module

    async def stop(self) -> None:
        self._rag.retrieve = self._real_retrieve
        await self._rag.shutdown()

    async def run(self, case: AnswerCase) -> dict:
        from server.agent import responder
        from server.agent.reply_fixes import gender_agreement
        from server.agent.script_fixes import latin_terms

        self._captured = None
        t0 = time.perf_counter()
        messages, reply_tokens = await responder._messages(
            case.question, case.lang, None, self.avatar
        )
        retrieve_ms = (time.perf_counter() - t0) * 1000

        t1 = time.perf_counter()
        reply, usage, finish = await complete_verbose(messages, reply_tokens)
        llm_ms = (time.perf_counter() - t1) * 1000
        reply = gender_agreement(latin_terms(reply, case.lang), case.lang, self.avatar)

        res = self._captured
        context = res.context if res is not None else ""
        completion = int(usage.get("completion_tokens") or 0)
        cap_hit = finish == "length" or (completion and completion >= reply_tokens - 2)

        return {
            "reply": reply,
            "context": context,
            "prompt_sha": hashlib.sha256(messages[0]["content"].encode()).hexdigest()[:12],
            "prompt_tokens": int(usage.get("prompt_tokens") or 0),
            "completion_tokens": completion,
            "max_tokens": reply_tokens,
            "finish_reason": finish,
            "cap_hit": bool(cap_hit),
            "headings": [c.heading_path for c in res.chunks] if res else [],
            "rewritten": bool(res.rewritten) if res else False,
            "query": res.query if res else "",
            "cached": bool(res.cached) if res else False,
            "degraded": res.degraded if res else "no-retrieval",
            "section_expanded": res.section_expanded if res else 0,
            "timings_ms": dict(res.timings_ms) if res else {},
            "retrieve_ms": retrieve_ms,
            "llm_ms": llm_ms,
        }


# ── scoring one run ─────────────────────────────────────────────────


def grade_record(case: AnswerCase, reply: str, context: str | None,
                 cap_hit: bool, extra: dict | None = None) -> dict:
    fs = score(case.require, case.optional, reply, context)
    rec = {"id": case.id, "depth": case.depth, "section": case.section,
           "baseline_grade": case.baseline_grade, "reply": reply, **fs.as_dict()}
    # A reply cut off at the cap did not "drop" the tail — it never got to write it.
    if cap_hit:
        for e in rec["entries"]:
            if e["cause"] == "generation":
                e["cause"] = "cap"
        rec["causes"] = _count_causes(rec["entries"])
    if extra:
        rec.update({k: v for k, v in extra.items() if k not in ("reply", "context")})
    if context is not None:
        rec["section_hit"] = _section_hit(extra, case) if extra else None
    return rec


def _count_causes(entries: list[dict]) -> dict:
    out: dict[str, int] = {}
    for e in entries:
        if e.get("cause"):
            out[e["cause"]] = out.get(e["cause"], 0) + 1
    return out


def _section_hit(extra: dict, case: AnswerCase) -> bool | None:
    """Did the section that answers this question come back?

    The spreadsheet's Ref # names a leaf item ("1.4.8"), but headings only go two
    levels deep ("1. Overview ... > 1.4 Corporate Registration"), so the ref is cut
    back to the heading level before matching. Otherwise every leaf case reports a
    miss against a section that was in fact retrieved.
    """
    from eval.run_eval import heading_matches

    if not case.section:
        return None
    want = ".".join(case.section.split(".")[:2])
    return any(heading_matches(h, want) for h in extra.get("headings", []))


# ── reporting ───────────────────────────────────────────────────────


def _pct(n: int, d: int) -> str:
    return f"{(100.0 * n / d):.1f}%" if d else "n/a"


def summarise(records: list[dict], cases: list[AnswerCase], header: dict) -> dict:
    by_case: dict[str, list[dict]] = {}
    for r in records:
        by_case.setdefault(r["id"], []).append(r)

    grades, causes, caps, unstable = {}, {}, 0, []
    req_hit = req_total = 0
    for cid, runs in by_case.items():
        gs = [r["grade"] for r in runs]
        if len(set(gs)) > 1:
            unstable.append(cid)
        # The worst grade across repeats, so a flaky pass is never reported as a fix.
        worst = min(gs, key=lambda g: GRADE_ORDER[g])
        grades[cid] = worst
        pick = next(r for r in runs if r["grade"] == worst)
        req_hit += pick["hit"]
        req_total += pick["total"]
        for k, v in pick.get("causes", {}).items():
            causes[k] = causes.get(k, 0) + v
        if any(r.get("cap_hit") for r in runs):
            caps += 1

    counts = {g: sum(1 for v in grades.values() if v == g)
              for g in ("Matched", "Partial", "Not Matched")}
    moves = {"FIXED": [], "SAME": [], "WORSE": [], "NEW": []}
    for case in cases:
        if case.id not in grades:
            continue
        new, old = grades[case.id], case.baseline_grade
        if not old:
            moves["NEW"].append(case.id)
        elif GRADE_ORDER[new] > GRADE_ORDER[old]:
            moves["FIXED"].append(case.id)
        elif GRADE_ORDER[new] < GRADE_ORDER[old]:
            moves["WORSE"].append(case.id)
        else:
            moves["SAME"].append(case.id)

    comps = [r["completion_tokens"] for r in records if r.get("completion_tokens")]
    return {"header": header, "grades": grades, "counts": counts, "moves": moves,
            "causes": causes, "cap_cases": caps, "unstable": unstable,
            "fact_hit": req_hit, "fact_total": req_total,
            "completion_p50": statistics.median(comps) if comps else 0,
            "completion_max": max(comps) if comps else 0,
            "records": records}


def print_report(rep: dict, cases: list[AnswerCase], show: int) -> None:
    h, c, m = rep["header"], rep["counts"], rep["moves"]
    n = len(rep["grades"])
    print()
    print(f"╭─ answers ─ {n} cases × {h['repeat']} repeats ─ {h['branch']} @ {h['git_sha']} "
          f"─ temp {h['temperature']}")
    print(f"│  grade        Matched {c['Matched']:3}  Partial {c['Partial']:3}  "
          f"Not Matched {c['Not Matched']:3}")
    print(f"│  fact recall  {_pct(rep['fact_hit'], rep['fact_total'])}   "
          f"({rep['fact_hit']}/{rep['fact_total']} required facts)")
    if rep["causes"]:
        print("│  miss causes  " + "   ".join(f"{k} {v}" for k, v in sorted(rep["causes"].items())))
    if h["mode"] == "live":
        print(f"│  cap hits     {rep['cap_cases']}/{n}   (completion p50 "
              f"{rep['completion_p50']:.0f}, max {rep['completion_max']} of {h['max_tokens']})")
        hit = [r.get("section_hit") for r in rep["records"] if r.get("section_hit") is not None]
        if hit:
            print(f"│  section hit  {_pct(sum(1 for x in hit if x), len(hit))}")
    if h["repeat"] > 1:
        print(f"│  stability    {n - len(rep['unstable'])}/{n} cases identical across repeats")
    print("╰─")
    print()
    label = "baseline (tester)" if h["mode"] != "baseline-file" else "baseline run"
    print(f"{label} → current")
    for kind in ("FIXED", "SAME", "WORSE", "NEW"):
        if m[kind]:
            print(f"  {kind:6} {len(m[kind]):3}")
    byid = {case.id: case for case in cases}
    worst = m["WORSE"] + [i for i in rep["unstable"] if i not in m["WORSE"]]
    for cid in worst[:show]:
        case, g = byid[cid], rep["grades"][cid]
        tag = "WORSE" if cid in m["WORSE"] else "UNSTABLE"
        print(f"\n  [{tag}] {cid}  {case.baseline_grade} → {g}")
        rec = next(r for r in rep["records"] if r["id"] == cid and r["grade"] == g)
        miss = [e["variants"][0] for e in rec["entries"] if not e["hit"]]
        print(f"      missing: {miss}  causes={rec.get('causes', {})}")
    still = [cid for cid in m["SAME"] + m["WORSE"] if rep["grades"][cid] != "Matched"]
    if still:
        print(f"\nstill failing ({len(still)}):")
        for cid in still[:show]:
            rec = next(r for r in rep["records"]
                       if r["id"] == cid and r["grade"] == rep["grades"][cid])
            miss = [e["variants"][0] for e in rec["entries"] if not e["hit"]]
            print(f"  {cid:14} {rec['grade']:12} {rec['hit']}/{rec['total']}  "
                  f"causes={rec.get('causes', {})}")
            print(f"      missing: {miss}")


def print_calibration(records: list[dict], cases: list[AnswerCase]) -> None:
    """Derived grade beside the tester's, for the stored replies. Tunes the fixture."""
    byid = {c.id: c for c in cases}
    agree = 0
    print(f"\n{'case':16} {'tester':12} {'derived':12} facts  disagreement")
    for r in records:
        old = byid[r["id"]].baseline_grade or "-"
        ok = old == r["grade"]
        agree += ok
        note = "" if ok else "  <-- scorer disagrees with the human"
        print(f"{r['id']:16} {old:12} {r['grade']:12} {r['hit']}/{r['total']}{note}")
    print(f"\nagreement with the tester: {agree}/{len(records)} "
          f"({_pct(agree, len(records))})")
    off = [r for r in records if byid[r["id"]].baseline_grade != r["grade"]]
    for r in off[:12]:
        miss = [e["variants"][0] for e in r["entries"] if not e["hit"]]
        print(f"\n  {r['id']}: tester {byid[r['id']].baseline_grade}, derived {r['grade']}")
        print(f"    missing: {miss}")


def _header(args, mode: str, max_tokens: int = 0) -> dict:
    def git(*a):
        try:
            return subprocess.run(["git", *a], cwd=ROOT, capture_output=True,
                                  text=True, check=True).stdout.strip()
        except Exception:  # noqa: BLE001
            return "?"

    return {"mode": mode, "repeat": args.repeat, "temperature": args.temperature,
            "branch": git("rev-parse", "--abbrev-ref", "HEAD"),
            "git_sha": git("rev-parse", "--short", "HEAD"),
            "avatar": args.avatar, "max_tokens": max_tokens,
            "system_prompt": str(args.system_prompt or ""),
            "when": time.strftime("%Y-%m-%dT%H:%M:%S")}


def _swap_prompt(path: Path, lang: str, avatar: str) -> None:
    """Replace one (avatar, lang) system prompt, for prompt A/B runs."""
    import dataclasses

    from server import rag
    from server.prompts import get_prompts

    base = get_prompts()
    lib = dataclasses.replace(
        base, system={**base.system, (avatar, lang): path.read_text(encoding="utf-8").strip()}
    )
    rag._generator().load_templates(lib)
    print(f"system prompt for ({avatar}, {lang}) ← {path}")


async def _live(args, cases: list[AnswerCase]) -> list[dict]:
    runner = LiveRunner(args.avatar)
    await runner.start(ingest=args.ingest)
    if args.system_prompt:
        _swap_prompt(args.system_prompt, args.lang, args.avatar)
    records = []
    try:
        for rep in range(args.repeat):
            for i, case in enumerate(cases, 1):
                try:
                    out = await runner.run(case)
                except Exception as exc:  # noqa: BLE001
                    print(f"  [{rep}] {case.id}: ERROR {type(exc).__name__}: {exc}",
                          flush=True)
                    continue
                rec = grade_record(case, out["reply"], out["context"],
                                   out["cap_hit"], out)
                rec["repeat"] = rep
                records.append(rec)
                # flushed: a run takes minutes, and redirected stdout is block
                # buffered, which makes a working run look like a hung one.
                print(f"  [{rep}] {i:3}/{len(cases)} {case.id:16} {rec['grade']:12} "
                      f"{rec['hit']}/{rec['total']}  {out['completion_tokens']:4}tok"
                      f"{'  CAP' if out['cap_hit'] else ''}", flush=True)
    finally:
        await runner.stop()
    return records


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cases", type=Path, default=CASES)
    ap.add_argument("--ids")
    ap.add_argument("--status", default="all",
                    help='keep only these baseline grades; default all')
    ap.add_argument("--lang", choices=["en", "ur"], default="en")
    ap.add_argument("--avatar", choices=["female", "male"], default="female")
    ap.add_argument("--repeat", type=int, default=1)
    ap.add_argument("--temperature", type=float, default=0.0,
                    help="0.0 for a graded run; 0.3 mirrors production")
    ap.add_argument("--set", action="append", default=[], metavar="KEY=VALUE",
                    help="override a RagSettings field, as in eval/run_eval.py")
    ap.add_argument("--system-prompt", type=Path,
                    help="swap the (avatar, lang) system prompt — prompt A/B")
    ap.add_argument("--ingest", action="store_true",
                    help="re-ingest the corpus on startup (needed after a KB edit)")
    ap.add_argument("--jsonl", type=Path, help="append one record per (case, repeat)")
    ap.add_argument("--json", type=Path, help="write the summary report here")
    ap.add_argument("--baseline", type=Path,
                    help="compare against a previous --jsonl instead of the tester's grades")
    ap.add_argument("--score-only", action="store_true",
                    help="no LLM: score the replies stored in the fixture")
    ap.add_argument("--show", type=int, default=20)
    args = ap.parse_args()

    cases = load_cases(args.cases, args.ids, args.status)
    if not cases:
        print("no cases selected")
        return 1

    if args.set:
        from server.services.settings import get_settings

        settings = get_settings()
        for pair in args.set:
            key, _, raw = pair.partition("=")
            current = getattr(settings, key)
            value = (raw.strip().lower() in {"1", "true", "yes", "on"}
                     if isinstance(current, bool) else type(current)(raw))
            setattr(settings, key, value)
            print(f"override {key} = {value!r}")

    if args.score_only:
        records = [grade_record(c, c.baseline_reply, None, False) for c in cases]
        print_calibration(records, cases)
        if args.jsonl:
            args.jsonl.write_text("\n".join(json.dumps(r, ensure_ascii=False)
                                            for r in records) + "\n")
        return 0

    from server import config as C

    C.LLM_TEMPERATURE = args.temperature
    if not C.llm_ready():
        print(f"LLM is not configured (provider {C.LLM_PROVIDER}, base {C.LLM_BASE!r})")
        return 1

    if args.baseline and args.baseline.exists():
        prior = {}
        for line in args.baseline.read_text().splitlines():
            if line.strip():
                r = json.loads(line)
                prior.setdefault(r["id"], r["grade"])
        for case in cases:
            case.baseline_grade = prior.get(case.id, case.baseline_grade)

    records = asyncio.run(_live(args, cases))
    if not records:
        print("every case errored")
        return 1

    header = _header(args, "baseline-file" if args.baseline else "live",
                     max_tokens=records[0].get("max_tokens", 0))
    rep = summarise(records, cases, header)
    print_report(rep, cases, args.show)

    if args.jsonl:
        args.jsonl.parent.mkdir(parents=True, exist_ok=True)
        with args.jsonl.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"_header": header}, ensure_ascii=False) + "\n")
            for r in records:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
        print(f"\nwrote {args.jsonl}")
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps({k: v for k, v in rep.items() if k != "records"},
                                        indent=2, ensure_ascii=False))
        print(f"wrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
