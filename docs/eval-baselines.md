# Recorded baselines

What the kiosk measured **before** the architecture refactor, so every step of it can
be checked against the behaviour it is supposed to preserve. A refactor that changes
structure must leave all of these alone.

Recorded on `develop` at `02fb7c9`, 2026-10-08. The data files live in `eval/baselines/`.

| File | What it pins | How to compare |
|---|---|---|
| `retrieval.json` | Hybrid retrieval over the 150 questions in `eval/questions.yaml` | `python eval/run_eval.py --k 5 --baseline eval/baselines/retrieval.json` — exits non-zero on a regression |
| `answers.json` / `.jsonl` | What the kiosk actually says: 32 English cases, 2 repeats, graded fact by fact | `python eval/run_answers.py --repeat 2 --baseline eval/baselines/answers.jsonl` |

Two more guards live with the tests, because they need no services and run in `make check`:

| Guard | What it pins |
|---|---|
| `tests/fixtures/golden.json` | TTS text, prompts, LLM payloads and socket frames, byte for byte |
| `tests/fixtures/ws_golden.json` | The `/ws` endpoint and every lipsync frame, including the per-persona A2F tuning |
| `tests/test_turn_timing.py` | That sentence synthesis still overlaps instead of running one at a time |
| `frontend/test/fixtures/avatar-profiles.json` | Every resolved per-presenter look value |

## Retrieval, 2026-10-08

| Metric | Value |
|---|---|
| hit@1 | 78.4% |
| hit@3 | 93.3% |
| hit@5 | 95.5% |
| MRR | 0.856 |
| fact recall | 100.0% |
| retrieve p50 / p95 | 56 ms / 103 ms |

Tolerances are in `eval/run_eval.py` (`TOLERANCE`): hit@1 gets 2 points of slack because
near-tied chunks swap places between runs, the rest get 1 point, and retrieval latency
may drift 10%. `tests/test_eval_gate.py` tests that arithmetic.

## Answers, 2026-10-08

| Metric | Value |
|---|---|
| grades | Matched 21, Partial 11, **Not Matched 0** |
| fact recall | 91.3% (179/196 required facts) |
| miss causes | generation 15, retrieval 2 |
| cap hits | 0/32 (completion p50 122 tokens, max 268 of 400) |
| section hit | 87.5% |
| stability | 32/32 identical across repeats |
| vs the tester's own grades | 23 fixed, 9 the same, 0 worse |

**Not Matched must stay at 0** and fact recall must not fall more than ~2 points.
Cap hits at 0 is the evidence that the reply cap is not what limits answers — misses are
the model dropping facts it was given, so raising the cap is not the lever.

## Re-running these

Both need the stack up and Qdrant reachable from the host. Qdrant's port is deliberately
not published, so pass its container address:

```bash
docker compose up -d
set -a && . ./.env && set +a
export MARI_RAG_QDRANT_HOST=$(docker network inspect mari-interactive-kiosk-main_default \
  --format '{{range .Containers}}{{if eq .Name "mari-interactive-kiosk-main-qdrant-1"}}{{.IPv4Address}}{{end}}{{end}}' \
  | cut -d/ -f1)

python eval/run_eval.py --k 5 --baseline eval/baselines/retrieval.json
python eval/run_answers.py --repeat 2 --baseline eval/baselines/answers.jsonl
```

Run them from the host, not inside the backend container: the container has an image copy
of the code, so it would grade whatever was built last rather than the working tree.

The answer eval calls the live LLM, so it costs tokens and a few minutes. `--score-only`
re-grades the stored replies offline and needs nothing running.

## Replacing a baseline

Only with a measured, deliberate behaviour change, in the same commit as that change, and
with the reason in the commit message. A baseline quietly refreshed to make a gate pass is
the gate removed.
