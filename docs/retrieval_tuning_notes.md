# Retrieval tuning notes

The measurements behind the defaults in `server/services/settings.py`. Every value was
set with `eval/run_eval.py` / `eval/calibrate.py`; re-measure before changing one.

## Models

- **FastEmbed (ONNX Runtime)** rather than sentence-transformers: no torch in the serving
  image, quantized weights, 2-5x faster CPU inference on the CPU deploy target.
- **Dense model `intfloat/multilingual-e5-large`.** `BAAI/bge-m3` and
  `multilingual-e5-small` are not shipped by FastEmbed 0.8; `jina-embeddings-v3` is
  CC-BY-NC. Multilingual is required: the corpus is English and about half the questions
  are Urdu. An English-only model (bge-small-en-v1.5) only makes sense in English-only mode.
- **Sparse `Qdrant/bm25`** handles what dense embeddings miss: "NTN 1414673",
  "Bhitai-6", "PSX", "Sky47".
- **E5/BGE prefixes** are resolved from the model name, because a missing prefix costs
  recall without raising anything.

## Reranker

English half of the eval set, top_k=5, 10 candidates capped at 128 tokens, 6 pinned cores:

| reranker | hit@1 | hit@5 | MRR | abstain | p50 |
|---|---|---|---|---|---|
| none (hybrid + RRF only) | 69.8% | 92.5% | 0.800 | 10% | 44 ms |
| Xenova/ms-marco-MiniLM-L-6-v2 | 56.6% | 73.6% | 0.635 | 60% | 109 ms |
| jinaai/jina-reranker-v2-base-multilingual | 73.6% | 94.3% | 0.821 | 50% | 494 ms |

- The small English cross-encoder makes ranking **worse** (-13 points of hit@1): it is
  trained on web passages, and this corpus is report bullets and tables.
- The multilingual cross-encoder is the best ranker and the best relevance gate (91% kept
  / 83% blocked), but costs ~450 ms, about four times the retrieval budget of a voice
  turn. So reranking is **off** by default, with the good model configured.
- Capping candidates at 128 tokens takes 20-candidate reranking from 700 ms to 125 ms.
  10 candidates cost 58 ms against 125 ms for 20, and the correct chunk is essentially
  never ranked 11th-20th by RRF when it was not already in the top 10.
- After turning reranking on, re-run `eval/calibrate.py`: `score_threshold` applies to
  rerank probabilities, `dense_score_threshold` applies without them.

## Chunking

- Sizes are in **tokens** from the embedding tokenizer. On this corpus a "300 word"
  chunk was 450+ tokens and silently truncated at the model's 512-token limit.
- 320 tokens / 15% overlap. In a 500-token chunk a topic mentioned once is diluted and
  retrieval of it becomes non-deterministic.
- Chunks under 30 tokens are heading stubs that score deceptively high against short
  spoken queries.

## Gating

**`score_threshold` = 0.02** (rerank probability). The reference value 0.3 kept only 66%
of answerable questions and collapsed hit@5 from 92% to 62%. Unanswerable questions score
~1e-13. Against the 16 negative cases: 0.02 keeps 83% of answerable questions and blocks
78% of unanswerable ones. "What is OGDCL's annual profit?" legitimately retrieves the
shareholding section, so on-topic-but-unanswerable is the prompt's job, not retrieval's.

**`dense_score_threshold` = 0.72** (dense cosine; RRF scores do not separate answerable
from unanswerable at all). At 0.72 it blocks 0 of 16 unanswerable questions; this is the
weakest point in the system. It is not 0.75 because "What is the NTN number?" scored 0.746
and was blocked. Per-language calibration:

| lang | correct top-1 down to | unanswerable up to | best trade |
|---|---|---|---|
| en | 0.735 | 0.887 | 0.782 keeps 92.5%, blocks 40% |
| ur | 0.731 | 0.796 | 0.743 keeps 96.3%, blocks 33% |

Per-language thresholds were not adopted: the persona prompt already declines off-topic
questions, while the answerable questions they lose are what testers record.

**`relative_score_floor` = 0.10**: supporting chunks below 10% of the top chunk's score
are dropped; an absolute threshold cannot do this.

## Context size

**`max_context_chars` = 8000.** At 6000, "give me all their names" after a Board question
listed eight of eleven directors (section 4 is 9,431 chars over ten chunks). At 8000 all
eleven survive and the section saturates. Cost: +820 chars of context at p50, with
hit@k, MRR, section recall and context precision identical.

## Section expansion

The top chunk's section is completed with its remaining chunks. Retrieval often finds
the right section but only two of its eleven bullets ("what discoveries has Mari Energies
made?"). A wider top_k instead padded answers with unrelated sections.

342-question tester set: section recall 79.7% → 91.0%; questions whose section arrives
complete 62.6% → 82.7%; hit@k and MRR unchanged; +1,400 chars at p50, ~3 ms.

`section_expansion_chars` = 3500 is the knee: 5,000 chars and 8 chunks moved full coverage
only 82.7% → 85.4%, because `max_context_chars` binds first. Completing more than the
rank-1 section trades context precision for recall and makes answers worse.

## Query rewriting

Measured against the deployed LLM: 12 rewrites of elliptical follow-ups took min 547 ms,
p50 829 ms, p90 923 ms. The old 150 ms timeout meant every rewrite timed out silently, so
"Give me all their names" retrieved the company overview instead of the Board.
`rewrite_timeout_ms` = 1200 clears p90; a rewrite that always times out is worse than
none.

## Query expansion and subject stripping

- **Urdu lexical expansion:** without it the hybrid retriever loses 15 points of hit@5
  on Urdu questions against the old BM25 retriever, while beating it by 6 on English.
- **Stripping "Mari Energies" from the dense query:** hit@1 78.4% → 84.5%, context
  precision 27.5% → 29.9% on the 342-question set; English internal set unchanged at
  81.1% hit@1 with hit@3/@5 up; Urdu measured identical.

| question (dense rank of the answering section) | as asked | subject stripped |
|---|---|---|
| "What discoveries has [X] made recently?" | 18 | 2 |
| "What are [X]'s production ... figures?" | 20 | 1 |
| "Who is [X]'s CEO?" | 11 | 1 |
| "What is [X]'s corporate group structure?" | 2 | 1 |

## Qdrant

qdrant-client switches to HTTPS as soon as an api_key is set. Inside a compose network
Qdrant speaks plaintext, so that shows up as an unrelated-looking connection error; hence
`qdrant_https` = False.

## Corpus

`server/data/README.md` is excluded (it matched questions about "the knowledge base").
`sky47_knowledge_base.md` is excluded: the persona may only state what the Mari corpus
contains, and ingesting both would duplicate every Sky47 fact across two sources.
