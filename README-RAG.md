# Retrieval layer

Hybrid (dense + sparse) retrieval over Qdrant for the MARI kiosk. It replaced a
stdlib BM25 index that used to live in `server/knowledge.py`; that code has since been
removed, and this is now the only retrieval path in the system.

This document exists because every number in `server/services/settings.py` is a trade,
and a parameter whose reason is not written down is a parameter nobody dares change.
Where a value here contradicts the design it was built from, the measurement that caused
the change is given.

---

## 1. What it does, in order

```
STT transcript
  │
  ├─ 1. transcript correction   regex map over domain vocabulary        <1 ms
  ├─ 2. query rewrite           conditional, timeout-guarded, usually skipped
  ├─ 3. embed                   dense + sparse, concurrently         ~35 ms  (~0 ms pre-started)
  ├─ 4. hybrid search           Qdrant prefetch ×2 + server-side RRF  ~10 ms
  ├─ 5. rerank                  cross-encoder (OFF by default)      ~450 ms
  ├─ 6. relevance gate          on the best chunk, not each chunk       <1 ms
  ├─ 7. section expansion       complete the sections that ranked       ~3 ms
  ├─ 8. glossary injection      deterministic abbreviation override      <1 ms
  └─ 9. context assembly        dedupe, cap, join                       <1 ms
  │
system prompt → LLM → TTS
```

Measured end to end: **10–12 ms per turn warm with the embedding pre-started, 44 ms
without**, against a 120 ms budget. (Measured on a contended developer laptop with cores
pinned — re-measure on the real target.)

### Files

| File | Responsibility |
|---|---|
| `server/services/settings.py` | every tunable, each with its rationale |
| `server/services/chunking.py` | structure-aware markdown/PDF chunking with heading paths |
| `server/services/documents.py` | parsing (md / txt / pdf) and content hashing |
| `server/services/embedding.py` | FastEmbed dense + sparse + reranker, async-offloaded |
| `server/services/store.py` | Qdrant collection management and the hybrid RRF query |
| `server/services/ingestion.py` | idempotent hash-based ingest |
| `server/services/metadata.py` | SQLite record of what is indexed |
| `server/services/transcript.py` | STT domain-term correction |
| `server/services/expansion.py` | Urdu → English expansion for the lexical channel |
| `server/services/rewriter.py` | conditional, timeout-guarded query rewriting |
| `server/services/retriever.py` | **the single shared retrieve path** |
| `server/services/generation.py` | prompt assembly, sync + SSE streaming |
| `server/rag.py` | bridge to `server/app.py`, and the degradation policy |
| `eval/` | question set, scoring harness, threshold calibration |

Both the HTTP API and the voice path call `Retriever.retrieve`. The voice path may pass
a smaller `top_k`; the logic does not fork. The previous system had retrieval
implemented twice and the two copies drifted.

---

## 1a. Retrieving the right section is not the same as answering the question

Two changes came out of scoring the retriever against the 342-question evaluation the
kiosk's tester actually ran (`Ref #` in that sheet labels the section each question is
answered from, so it is ground truth somebody else wrote). They are recorded together
because they are the two halves of the same finding: **hit@k was not measuring what was
going wrong.**

**The sparse channel had no IDF.** FastEmbed's `Qdrant/bm25` emits only the
term-frequency half of BM25 — query vectors are literally all `1.0` — and expects Qdrant
to supply inverse document frequency from the sparse index's `modifier=IDF`. That
modifier was never set. Nothing errored; BM25 silently became "sum of term frequencies",
which on a single-subject corpus ranks by how often a chunk repeats the words every
query contains. The top lexical hit for *"How does Mari Energies use artificial
intelligence?"* was §1.1, which does not mention AI, winning on the count of "Mari",
"Energies" and "company"; §9.2, **titled** "Artificial Intelligence", was not in the top
ten. Setting the modifier moves it to rank 1 and the fused result from rank 7 to rank 1.
Worth **+4.1 hit@1 / +3.0 hit@5** on the tester's set. `ensure_collection` detects a
collection built without the modifier and recreates it, which re-ingests on that boot.

**The remaining failures were complete-section failures, and hit@k cannot see them.**
Every question the tester marked *Partial* or *Not Matched* retrieved the right section
— and got a partial answer, because only part of that section reached the model. Ten of
eighteen sections are enumerations (eleven discoveries, five field developments,
seventeen sustainability milestones). Asked *"what discoveries have you made?"*, every
chunk of §6 is equally on-topic, so which two of them top-k returns is decided by
wording noise, and the kiosk names two discoveries out of ten with total confidence.
Section expansion completes the sections that ranked, inside the existing context cap.

| | before | after |
|---|---|---|
| hit@1 / hit@3 / hit@5 (tester set) | 74.6% / 92.1% / 94.4% | **78.4% / 95.0% / 97.4%** |
| mean section recall | 79.7% | **92.0%** |
| questions whose section arrives **complete** | 62.6% | **84.2%** |
| context at p50 | 4,204 ch | 5,795 ch |
| retrieve p50 | 60 ms | 73 ms |

Two things to note about that table. Ranking metrics are unchanged by expansion to three
decimal places — it appends, never reorders, so it *cannot* cost hit@k. And the reason
it is scored on section recall at all is that this failure is invisible to hit@k: every
row of the "before" column already had the right section at rank 1.

---

## 2. Results

150 questions (`eval/questions.yaml`), 134 answerable + 16 deliberately unanswerable,
scored by `eval/run_eval.py`.

The BM25 column is a **historical record and is no longer reproducible** — that retriever
has been deleted, along with the `--backend bm25` flag that scored it. It is kept because
it is the only evidence for why several parameters are set the way they are; the numbers
were measured on this same question set before the switch.

| Metric | BM25 (removed) | **This** | |
|---|---|---|---|
| hit@1 | 64.2% | **74.6%** | +10.4 |
| hit@3 | 90.3% | **92.5%** | +2.2 |
| hit@5 | 93.3% | **94.0%** | +0.7 |
| MRR | 0.772 | **0.833** | +0.061 |
| fact recall | 98.5% | **99.3%** | +0.8 |
| abstain rate | **25.0%** | 0.0% | −25.0 |
| latency p50 | ~0.1 ms | 51.6 ms | budget 120 ms |

Per language:

| | hit@1 | hit@5 | MRR |
|---|---|---|---|
| BM25 — English | 64.2% | 86.8% | 0.736 |
| **This — English** | **75.5%** | **92.5%** | **0.829** |
| BM25 — Urdu | 64.2% | **97.5%** | 0.796 |
| **This — Urdu** | **74.1%** | 95.1% | **0.836** |

**Two caveats on hit@1, both about ties.** Until RRF ties were broken deterministically
(`Retriever._order`), these numbers were not reproducible: the same code scored anywhere
from 70.9% to 72.4% hit@1 across runs, because 47 of the 150 questions have a tied pair
inside the top 5 and Qdrant returned ties in scan order. Any earlier comparison in this
document that turns on ~2 points of hit@1 was partly reading that noise.

Second, the tie-break itself is arbitrary by design — document order, chosen for
stability, not for relevance. Ordering those same ties by descending dense similarity
scores 70.9%; ascending scores 74.6%. That 3.7-point spread is not a quality difference,
it is the assignment of ~33 coin flips (the higher-dense chunk is the correct one 17
times out of 33, the lower-dense one 16). Treat hit@1 here as roughly ±2, and do not
tune the tie-break against this set.

The headline gain is **ranking quality**: +5.2 hit@1 overall, +7.5 on each language
separately (the overall figure is lower than both halves because the language mix
differs — Simpson's paradox, not an error). What the visitor hears is built from the
top one or two chunks, so hit@1 and MRR matter more here than hit@5.

**Read the regressions honestly.** Two are real:

- **Urdu hit@5 is 2.4 points below the old retriever** (95.1% vs 97.5%), though hit@1 and
  MRR are both far better. The old one has a hand-built Urdu layer tuned against this
  exact corpus. Most of that is now reused (§5), but not all of it survives the trip
  through a vector index.
- **Abstain rate went to zero** — from 25%. Retrieval never returns empty now, so
  nothing is refused at the retrieval layer; refusal happens at the prompt layer instead,
  which is verified working but is the weaker of the two places to do it. This is the
  system's weakest point. §6 covers it and what fixes it.

Reproduce:

```bash
docker compose up -d qdrant
python scripts/rag_ingest.py --recreate
python eval/run_eval.py --k 5
python eval/run_eval.py --lang ur --show-failures 20
python eval/calibrate.py                     # threshold sweep
```

---

## 3. Models

FastEmbed (ONNX Runtime) rather than sentence-transformers: no torch in the serving
image (~2 GB smaller), quantized weights, 2–5× faster CPU inference, and it produces the
sparse vectors Qdrant's hybrid query needs from the same library.

| Role | Model | Dim | Why |
|---|---|---|---|
| Dense | `intfloat/multilingual-e5-large` | 1024 | multilingual is non-negotiable here |
| Sparse | `Qdrant/bm25` | — | exact identifiers, well names, tickers, NTN numbers |
| Reranker | `jinaai/jina-reranker-v2-base-multilingual` | — | configured, **off by default** (§6) |

### Two deviations from the original plan

**`BAAI/bge-m3` is not available in FastEmbed 0.8** (nor is `intfloat/multilingual-e5-small`).
The multilingual dense models that do exist are `multilingual-e5-large`,
`paraphrase-multilingual-mpnet-base-v2` and `jina-embeddings-v3`. The last is CC-BY-NC
and this is a commercial deployment, so it is excluded on licensing regardless of
quality. e5-large is the pick.

**`BAAI/bge-reranker-v2-m3` is not available either.** See §6.

### Prefixes

E5 and BGE are asymmetric — trained with different prefixes on queries and passages.
Omitting them costs several points of recall and raises nothing. They are resolved from
the model name in `RagSettings._resolve_prefixes` rather than configured, so a model
swap cannot leave a stale prefix behind.

### Multilingual is not optional

The corpus is entirely English; roughly half the questions arrive in Urdu. Cross-lingual
alignment in the embedding space is doing the single most important job in the system.
Switching to `BAAI/bge-small-en-v1.5` is only valid if the kiosk is put in English-only
mode — and re-run the eval if you do.

---

## 4. Chunking

Structure-aware, replacing a sliding word window. Sized in **tokens via the embedding
model's own tokenizer**, not `str.split()`.

| Parameter | Value | Why |
|---|---|---|
| `chunk_tokens` | 320 | In a 500-token chunk a topic mentioned once is diluted by unrelated text, embeds weakly against a short spoken query, and loses top-k ranking *non-deterministically* — the same question retrieves the right section on one turn and misses on the next. |
| `chunk_overlap_ratio` | 0.15 | So a fact on a chunk boundary is retrievable from either side. Cut at a sentence boundary, never mid-sentence. |
| `min_chunk_tokens` | 30 | Sub-30-token chunks are heading stubs and table fragments. They embed as near-noise and, being short, score *deceptively high* against short spoken queries. |
| `top_k` | 5 | Raised from 3: smaller chunks mean a topic now spans 2–3 chunks instead of one. |

Word counts and token counts diverge badly on this corpus — it is dense with numbers,
units and proper nouns that tokenize to three or four pieces each — so a "300 word"
chunk was really 450+ tokens and its tail was being silently truncated at the model's
512-token limit. **The tail of every long chunk was not being embedded at all.**

Guarantees, each with a test in `tests/test_chunking.py`:

- **Every chunk carries its full heading path in its own text.** "Bhitai-6" appears in
  this corpus exactly once — in a heading. Without this, no question about Bhitai-6 can
  retrieve it.
- **Tables and code fences are atomic.** This corpus is an annual-report export: the
  shareholding split, the five-year financial summary and the quick-reference figures
  are all tables. Half a table is worse than none, because the surviving rows still look
  authoritative. A table over the size limit is emitted whole.
- **Headings inside code fences are code, not headings.**
- **A single H1 is dropped from the path** — it is the document title, already carried by
  `source`, and repeating it in all 89 chunks costs tokens while discriminating nothing.
- **Runt tails are folded into their predecessor, not dropped.** Several sections here
  are two lines long; a blanket "drop under 30 tokens" deletes them from the index.

Payload per point: `text, source, heading_path, chunk_index, token_count, doc_hash,
ingested_at, file_type`.

---

## 5. Hybrid search, and the Urdu finding

Named vectors on one point, fused **server-side** by Reciprocal Rank Fusion in a single
round trip (`prefetch` × 2 + `FusionQuery`). Fusing in Python would mean two network
round trips inside a 120 ms budget plus a second RRF implementation to drift.

RRF rather than a weighted blend because the channels' scores are not comparable —
cosine is bounded and dense, BM25 unbounded and sparse. Rank is the only common
currency, and RRF needs no per-corpus weight to tune.

| Parameter | Value | Why |
|---|---|---|
| `prefetch_limit` | 30 | Per channel, before fusion. RRF can only promote what a channel surfaced, so this is the **real recall ceiling** of the whole system. |
| `rerank_candidates` | 10 | Lowered from 20 on measurement: 20 costs 125 ms vs 58 ms, and the correct chunk is essentially never ranked 11–20 by RRF when it was not already in the top 10. |
| `max_context_chars` | 6000 | Time-to-first-token scales with prompt length; past this the LLM ignores the middle anyway. |

### The Urdu finding

**The dense model beats the old BM25 retriever on English by 6 points of hit@5 and loses
to it on Urdu by 15.**

`server/knowledge.py` carries a hand-built, corpus-specific Urdu layer that no
general-purpose multilingual embedding reproduces: a curated topic glossary, phrase maps
for acronyms Urdu spells out letter by letter (`پی ایس ایکس` = P-S-X, three tokens that
individually mean nothing), and a phonetic index matching proper nouns across scripts on
a consonant skeleton (which is how `آیلہ مجید` finds "Ayla Majid" and `کارپلنک` finds
"Corplink").

Deleting that in favour of a multilingual embedding would have been a fifteen-point
regression on half the kiosk's traffic, **and nothing except the eval set would have
revealed it** — the English half looked like a clean win.

So it is kept and pointed at the channel it helps most. The **sparse** channel gets the
Urdu-expanded query — BM25 is purely lexical, so an Urdu query against an English corpus
contributes nothing to it, and the expansion is what makes that channel exist at all for
half the traffic. The **dense** channel gets the query as spoken, where the model's own
cross-lingual alignment beats a bag of translated keywords. See
`server/services/expansion.py`.

This closed most of the gap: Urdu hit@5 went 82.7% → 95.1%, MRR 0.651 → 0.836.

---

## 6. Reranking, and why it is off

Measured on the English half of the eval set — top_k 5, 10 candidates capped at 128
tokens, 6 pinned cores:

These were measured before RRF ties were broken deterministically (see §2), so the
absolute hit@1 values carry roughly ±2 points of tie-assignment noise. The gaps below are
far larger than that and the conclusions hold; do not read the last decimal.

| Reranker | hit@1 | hit@5 | MRR | abstain | p50 |
|---|---|---|---|---|---|
| **none** (hybrid + RRF) | 69.8% | 92.5% | 0.800 | 10% | **44 ms** |
| `Xenova/ms-marco-MiniLM-L-6-v2` | 56.6% | 73.6% | 0.635 | 60% | 109 ms |
| `jinaai/jina-reranker-v2-base-multilingual` | **73.6%** | **94.3%** | **0.821** | 50% | 494 ms |

Two findings, both counter to the plan:

**1. The small English cross-encoder makes ranking *worse* — thirteen points of hit@1.**
ms-marco rerankers are trained on web passages; this corpus is annual-report bullet
lists and financial tables under numbered headings, far out of that distribution. It
would have shipped as an upgrade on the strength of the architecture diagram alone if it
had not been measured.

**2. The multilingual cross-encoder genuinely is better** — the best ranking available
here, and by far the best relevance gate. It also costs ~450 ms, roughly four times the
entire retrieval budget for a speech-to-speech turn.

The original plan budgets 30–60 ms to rerank 20 candidates. **That is not achievable
with any cross-encoder in FastEmbed on a CPU of this class.** The numbers above are what
is actually on offer.

So the default is **off**, with the good model pre-configured behind one flag.

`rerank_doc_tokens = 128` is the single most effective latency lever: capping candidates
at 128 tokens takes 20-candidate reranking from 700 ms to 125 ms, and costs little
accuracy because the signal a cross-encoder needs is in the heading path and opening
sentences, which the chunker puts first.

### Quality profile

If ~500 ms of retrieval is acceptable, or there is a GPU:

```bash
MARI_RAG_RERANK_ENABLED=true
MARI_RAG_SCORE_THRESHOLD=0.11          # recalibrate: this gates rerank probabilities
MARI_RAG_RERANK_PROVIDERS='["CUDAExecutionProvider"]'   # GPU hosts only
```

This is the recommended configuration **if abstention matters more than latency** — it
is what makes "I don't have that information" reliable. On Urdu it gates at 91% of
answerable questions kept / 83% of unanswerable blocked, against 94% / 14% for the
default. Re-run `eval/calibrate.py` after switching: `score_threshold` applies to rerank
probabilities, `dense_score_threshold` applies without them.

---

## 7. The relevance gate

The only parameter whose job is to make retrieval return *nothing*, and therefore the
only one that cannot be tuned by looking at hit@k — raising it can only lower hit@k,
while what it buys is invisible to that metric. Calibrated directly by
`eval/calibrate.py`.

| Parameter | Value | Why |
|---|---|---|
| `score_threshold` | 0.02 | Rerank probability. Keeps 83% of answerable, blocks 78% of unanswerable. The plan's 0.3 keeps only **66%** — that is what collapsed hit@5 from 92% to 62% when first measured. |
| `dense_score_threshold` | 0.72 | Cosine similarity, used when the reranker is off. Deliberately loose — see below. |
| `relative_score_floor` | 0.10 | Secondary: once the best chunk clears the bar, drop supporting chunks below this fraction of it. |

### Two mistakes worth recording

**The gate applies to the result, not to each chunk.** Filtering every chunk against the
same bar looks equivalent and is not: chunks 2–5 legitimately score lower than the best
one, they are supporting context, and a topic here routinely spans two or three chunks.
Getting this wrong cost **23 points of hit@5** and made hit@3 and hit@5 collapse into
hit@1.

**The bar is cleared by the best chunk, not the top-ranked one.** RRF ranks by fused
rank, so the rank-1 chunk is frequently a sparse-channel winner with a mediocre dense
score. Gating on it discarded entire correct retrievals — an Urdu question about
`آیلہ مجید` whose top three hits were all the right board-members section returned
nothing at all, because the one that happened to rank first scored 0.743 against a 0.75
floor.

### The honest limitation

**Abstention on the default profile is zero** — no unanswerable question is refused at
the retrieval layer at all, against 25% for the retriever this replaces. It was 6.2%
until `dense_score_threshold` was lowered 0.75 → 0.72 to fix a live miss ("What is the
NTN number?" scored 0.746 and returned nothing). That recovered the recall and gave up
the last of the retrieval-layer abstention.

Two independent reasons:

1. **English and Urdu questions sit in different similarity bands, and neither
   separates.** Re-calibrated per language (`eval/calibrate.py --lang en|ur`), the two
   overlap on both sides, and a single global threshold has to straddle them:

   | | answerable range | best trade available |
   |---|---|---|
   | English | correct top-1 down to 0.735; unanswerable up to 0.887 | 0.782 keeps 92.5%, blocks 40% |
   | Urdu | correct top-1 down to 0.731; unanswerable up to 0.796 | 0.743 keeps 96.3%, blocks 33% |

   Per-language thresholds would buy roughly 40%/33% abstention for 7.5%/3.7% of
   answerable questions. That was measured and **not** adopted: refusing an answerable
   question is what a tester scores as a failure, while the off-topic questions this
   would block are already declined by the persona's own on-topic guardrail. It is
   written down so the trade is a decision rather than an oversight — if abstention
   ever matters more than recall here, those are the numbers.
2. **Some "unanswerable" questions legitimately retrieve relevant chunks.** "What is
   OGDCL's annual profit?" pulls the shareholding section because OGDCL genuinely is in
   the corpus as a 20% shareholder. No retrieval threshold can catch that.

That second point generalises: **retrieval gating handles OFF-TOPIC; prompt gating
handles ON-TOPIC BUT UNANSWERABLE.** Both are needed, and tightening the threshold to
compensate for the prompt costs real recall. `generation.py` appends an explicit
"do not answer from your own knowledge" instruction whenever context is empty, because
without it the model treats an empty context as licence to answer from memory — the
exact failure the threshold exists to prevent.

**If abstention matters for your deployment, use the quality profile in §6.** It is the
real fix.

---

## 8. Voice-path latency

| Stage | Budget | Measured |
|---|---|---|
| Query rewrite | ≤150 ms, usually skipped | 0 ms (skipped) |
| Embed query | 5–15 ms | ~35 ms, **~0 ms pre-started** |
| Qdrant hybrid + RRF | 10–30 ms | ~10 ms |
| Rerank | 30–60 ms | off (450 ms if on) |
| **Total** | **<120 ms** | **10–12 ms warm** |

**Pre-started embedding** is the cheapest win available, because it removes a stage from
the critical path rather than making it faster. `rag.prestart(transcript)` is called the
moment STT finalises, at all three entry points in `server/app.py`. By the time
endpointing settles and the turn handler runs, the embedding is already done and
`retrieve` claims the finished vector. Safe to call repeatedly with interim transcripts;
unclaimed tasks are reaped.

Everything model-bound has an `async` entry point that offloads via `asyncio.to_thread`.
This is not a nicety: ONNX inference is CPU-bound and holds the GIL in bursts, so a
synchronous encode inside the voice handler stalls the whole event loop — **including
the audio I/O streaming the previous sentence**. The symptom is a stutter in the
avatar's speech and it is very hard to trace back.

**Caching.** Query→vector (512 entries, FIFO) and normalised-query→result (256 entries,
300 s TTL). A kiosk gets the same handful of questions all day. Both cleared on ingest.

---

## 9. Ingestion

Idempotent and safe to run on every boot — the container restarts on every deploy,
health-check failure and config change, and an ingest that is not idempotent either
duplicates the corpus or spends 40 s re-embedding it on each one.

SHA-256 **of the file's bytes**, not mtime: a fresh image checks out every file with a
new mtime, so an mtime check would re-embed everything on every deploy.

- unchanged → skip
- changed → `delete_by_source` then re-ingest (delete **before** insert: an empty slot is
  recoverable on next boot, a duplicated document is not detectable at all)
- deleted from disk → removed from the index, so retired content cannot be answered from
- failed → recorded as `failed`, and retried next run (a hash-only check would skip it
  forever)

The KEYWORD payload index on `source` is what makes the filtered delete and per-document
count cheap rather than a full scan.

```bash
python scripts/rag_ingest.py              # changed files only
python scripts/rag_ingest.py --force      # every document
python scripts/rag_ingest.py --recreate   # after a model or dimension change
```

`--recreate` also resets the metadata DB. Dropping one without the other leaves every
file looking "already ingested" against an empty index, and the kiosk then answers from
nothing with no error anywhere.

---

## 10. Deployment

```bash
export MARI_RAG_QDRANT_API_KEY=$(openssl rand -hex 24)
docker compose up -d
```

Qdrant is **not** published to the host — the backend reaches it by service name on the
compose network. Qdrant ships with **no authentication** and its REST API includes
"delete collection", so the compose file makes `MARI_RAG_QDRANT_API_KEY` a hard
requirement rather than defaulting it.

### The HTTPS trap

`qdrant-client` silently switches to HTTPS the moment `api_key` is set. Inside a compose
or Coolify network Qdrant speaks plaintext on 6333, so that flip attempts a TLS handshake
against an HTTP port and surfaces as a generic connection error pointing nowhere near
the real cause. `QdrantStore` passes `https=False` explicitly; set
`MARI_RAG_QDRANT_HTTPS=true` only behind real TLS termination.

### Volumes

- `qdrant_storage` — the index. Derived data, but rebuilding costs ~40 s of embedding on
  every container recreate.
- `fastembed_cache` — ~3 GB of ONNX weights. Without it the download repeats on every
  recreate, and until it finishes the kiosk answers ungrounded.

### Degradation

Nothing here is allowed to take the kiosk down. It is a physical device in a lobby: it
must answer, or visibly say it cannot, but it must never fail to speak.

- `rag.startup()` runs as a **background task** — a cold container spends minutes
  downloading weights, and turns are answered meanwhile from the persona and the
  always-on core brief rather than being refused.
- Retrieval failure is caught, logged with `exc_info`, and returns **empty context**.
  The prompt still carries persona, rules and core brief, and the "say you do not have
  that information" branch fires.
- There is deliberately **no second retriever**. A shadow BM25 index used to sit behind
  this, on the theory that a fallback should not fail for the same reason as the thing
  it backs up. In practice it made outages invisible: the kiosk kept answering fluently
  from a separately-chunked copy of the corpus that no eval run ever scored, so a broken
  Qdrant degraded answer quality silently instead of surfacing. Empty context is the
  honest signal, and it is the one the prompt layer is built to handle.
- Prompt assembly needs no models and no Qdrant, so it stays available on the degraded
  path; one code path builds every prompt the kiosk speaks.
- `GET /healthz` reports `rag.state` (`warming` / `ready` / `failed`), Qdrant
  reachability, point count, which models are loaded, and the live parameters — so a
  degraded kiosk is visible rather than silently ungrounded.

---

## 11. Evaluation

```
eval/questions.yaml   150 questions: 134 answerable, 16 deliberately unanswerable
eval/run_eval.py      hit@k, MRR, fact recall, abstain rate, latency p50/p95 + per stage
eval/calibrate.py     threshold sweep — the recall/abstention trade, explicitly
```

Two independent expectations per question, because they fail differently:

- `expect_heading` — the section that answers it. Catches topic-level drift.
- `expect_facts` — literal substrings that must survive into the assembled context.
  Catches what heading matching misses entirely: the right section retrieved, but the
  specific number the visitor asked for cut out by chunking.

`expect_heading: null` marks a negative case. Without these, a retriever that returns
five chunks for literally any input scores perfectly on hit@k.

Override any parameter without editing code, then re-run and compare:

```bash
python eval/run_eval.py
python eval/run_eval.py --set rerank_enabled=true --set score_threshold=0.11
python eval/run_eval.py --lang ur --show-failures 20
```

**Run it on every parameter change.** Everything in §4–§7 that contradicts the original
design was found this way, and none of it was visible by asking the bot a few questions
and listening to the answers.

### Known gaps

- **16 negative cases is thin** for calibrating abstention. Add more before tightening
  any threshold.
- **No end-to-end answer quality metric.** This measures retrieval, not what the LLM
  says with it.
- Latency was measured on a contended laptop with cores pinned; re-measure on the real
  target before trusting the absolute numbers.
