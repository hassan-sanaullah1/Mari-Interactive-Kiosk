"""Tunable configuration for the retrieval layer.

Everything that was ever guessed at lives here, with the reason for its value written
next to it. The rule this module exists to enforce: no retrieval parameter is a literal
buried in the code, because every one of them is something eval/run_eval.py has an
opinion about, and a number you cannot change from the environment is a number nobody
re-measures.

Environment prefix is ``MARI_RAG_`` — e.g. ``MARI_RAG_TOP_K=4``,
``MARI_RAG_QDRANT_HOST=qdrant``.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent.parent


class RagSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="MARI_RAG_",
        env_file=ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── models ──────────────────────────────────────────────────────
    # FastEmbed (ONNX Runtime) rather than sentence-transformers: no torch in the
    # serving image, quantized weights, and 2-5x faster CPU inference. The kiosk's
    # deploy target is a CPU container, so this is not a marginal difference.
    #
    # NOTE on the dense model. The obvious pick would be BAAI/bge-m3 — multilingual,
    # 8k context, dense+sparse from one pass. FastEmbed 0.8 does not ship it (nor
    # intfloat/multilingual-e5-small), so the multilingual options that actually exist
    # here are e5-large and paraphrase-multilingual-mpnet. e5-large wins on quality and
    # is the default; jina-embeddings-v3 is excluded despite being a good model because
    # it is CC-BY-NC and this is a commercial deployment.
    #
    # Multilingual is not optional for this corpus. The knowledge base is entirely in
    # English and roughly half the questions arrive in Urdu, so cross-lingual alignment
    # in the embedding space is doing the single most important job in the system. A
    # faster English-only model (bge-small-en-v1.5) is a legitimate choice ONLY if the
    # kiosk is put into English-only mode; set it here and re-run the eval if so.
    dense_model: str = "intfloat/multilingual-e5-large"
    dense_dim: int = 1024

    # BM25 as a sparse vector, fused server-side. The dense channel is what handles
    # Urdu; this channel is what handles the things dense embeddings are consistently
    # bad at — "NTN 1414673", "Bhitai-6", "PSX", "Sky47". Those are exactly the kiosk's
    # most-asked specifics, and a purely dense retriever misses them.
    sparse_model: str = "Qdrant/bm25"

    # Cross-encoder over the fused candidates. bge-reranker-v2-m3 (the first choice) is
    # not in FastEmbed 0.8; jina-reranker-v2-base-multilingual is, and multilingual is
    # required here for the same reason the dense model is.
    # MEASURED on this corpus with eval/run_eval.py. English half of the eval set,
    # top_k=5, 10 candidates capped at 128 tokens, 6 pinned cores:
    #
    #   reranker                                    hit@1  hit@5    MRR  abstain    p50
    #   (none — hybrid + RRF only)                  69.8%  92.5%  0.800     10%   44 ms
    #   Xenova/ms-marco-MiniLM-L-6-v2               56.6%  73.6%  0.635     60%  109 ms
    #   jinaai/jina-reranker-v2-base-multilingual   73.6%  94.3%  0.821     50%  494 ms
    #
    # Two findings, both counter to the plan this was built from:
    #
    # 1. The small English cross-encoder makes ranking WORSE — thirteen points of hit@1.
    #    ms-marco rerankers are trained on web passages; this corpus is annual-report
    #    bullet lists and financial tables under numbered headings, which is far out of
    #    that distribution. A reranker is not automatically an improvement, and this one
    #    would have been shipped as an upgrade on the strength of the architecture
    #    diagram alone if it had not been measured.
    #
    # 2. The multilingual cross-encoder genuinely is better — the best ranking available
    #    here, and by far the best relevance gate (it is what makes "I don't know" work
    #    reliably). It also costs 450 ms, which is roughly four times the entire
    #    retrieval budget for a speech-to-speech turn.
    #
    # So the default is OFF, and the configured model is the good one, ready for the
    # single flag that turns it on. See "Quality profile" in README-RAG.md.
    reranker_model: str = "jinaai/jina-reranker-v2-base-multilingual"
    # Cross-encoder cost is linear in total tokens, and this is the single most effective
    # latency lever available: capping candidates at 128 tokens takes 20-candidate
    # reranking from 700 ms to 125 ms. The relevance signal a cross-encoder needs is
    # overwhelmingly in the heading path and opening sentences, which chunking.py puts
    # first. Verify against the eval set before lowering it further.
    rerank_doc_tokens: int = 128
    # Only meaningful with an English-only reranker; the configured model is
    # multilingual, so Urdu queries are reranked too when reranking is on.
    rerank_skip_for_urdu: bool = False
    # ONNX Runtime execution providers for the reranker, most-preferred first. On a GPU
    # host, ["CUDAExecutionProvider"] is what makes the quality profile affordable —
    # this is the configuration to reach for before giving up on reranking.
    rerank_providers: list[str] = []
    # OFF by default, on measurement rather than on principle — see the table above.
    # Reranking is the only stage that cannot fit the latency budget, and the default
    # configuration has to hold that budget. Turn it on (with a GPU, or with a budget
    # that tolerates ~500 ms) for the best ranking and a genuinely reliable "I don't
    # know"; re-run eval/calibrate.py afterwards, because score_threshold applies to
    # rerank probabilities and dense_score_threshold applies without them.
    rerank_enabled: bool = False

    # BGE and E5 are asymmetric models: they were trained with different prefixes on
    # queries and passages, and omitting them costs several points of recall silently —
    # nothing errors, results are just quietly worse. Resolved from the model name in
    # `prefixes` below rather than hard-coded, so swapping the model cannot desync them.
    query_prefix: str = ""
    passage_prefix: str = ""

    # ── chunking ────────────────────────────────────────────────────
    # Measured in TOKENS via the embedding model's own tokenizer, not str.split().
    # Word counts and token counts diverge badly on this corpus — it is dense with
    # numbers, units and proper nouns that tokenize to three or four pieces each — so a
    # "300 word" chunk was really 450+ tokens and was being silently truncated at the
    # model's 512-token input limit. The tail of every long chunk was not being embedded
    # at all.
    #
    # 320/15% is the middle of the range the reference system converged on. The reason
    # smaller beat larger: in a 500-token chunk a topic mentioned once is diluted by
    # unrelated surrounding text, embeds weakly against a short spoken query, and loses
    # top-k ranking non-deterministically — the same question retrieves the right
    # section on one turn and misses on the next.
    chunk_tokens: int = 320
    chunk_overlap_ratio: float = 0.15
    # Chunks below this are heading stubs and table fragments. They embed as near-noise
    # and, because they are short, score deceptively high on cosine similarity against
    # short spoken queries — actively harmful, not merely useless.
    min_chunk_tokens: int = 30

    # ── retrieval ───────────────────────────────────────────────────
    # Each channel proposes this many candidates before fusion. Wider than the final k
    # by a lot: RRF can only promote a chunk that at least one channel surfaced, so the
    # prefetch limit is the real recall ceiling of the whole system.
    prefetch_limit: int = 30
    # Survivors of RRF that get shown to the cross-encoder. 20 is where rerank cost
    # (~2.5 ms per candidate on CPU) stops buying measurable accuracy.
    # Lowered from the spec's 20 to 10 on measurement: 20 candidates cost 125 ms against
    # 58 ms for 10, and the eval set shows the correct chunk is essentially never ranked
    # 11th-20th by RRF when it was not already in the top 10.
    rerank_candidates: int = 10
    # Chunks finally passed to the LLM. Raised from the reference system's 3 because
    # structure-aware chunking splits a topic across 2-3 chunks instead of one.
    top_k: int = 5
    # Reranker scores are logits through a sigmoid, so this is calibrated, not arbitrary:
    # tune it against the negative cases in eval/questions.yaml, not by intuition. Its
    # entire job is the empty-index / off-topic case — without it, five irrelevant chunks
    # are injected as if authoritative, which does not merely fail to help, it actively
    # induces confident hallucination. An honest "I don't have that" is a better kiosk
    # experience than a fluent wrong answer.
    # CALIBRATED, not guessed — see eval/calibrate.py. The reference value of 0.3 keeps
    # only 66% of answerable questions, which is what collapsed hit@5 from 92% to 62%
    # when this was first measured. Unanswerable questions score ~1e-13 here, so 0.01
    # sits ten orders of magnitude above them while keeping ~88% of answerable ones.
    # Measured against the 16 negative cases in eval/questions.yaml: 0.02 keeps 83% of
    # answerable questions and blocks 78% of unanswerable ones. The overlap that stops
    # it being cleaner is real and instructive — a question like "What is OGDCL's annual
    # profit?" legitimately retrieves the shareholding section, because OGDCL genuinely
    # is in the corpus as a 20% shareholder. No retrieval threshold can catch that; it
    # is the system prompt's "answer only from the knowledge below" that must. Retrieval
    # gating handles OFF-TOPIC; prompt gating handles ON-TOPIC BUT UNANSWERABLE. Both
    # are needed, and tightening this one to compensate for the other costs real recall.
    score_threshold: float = 0.02
    # Gate for the path where the cross-encoder is not run (Urdu, or rerank disabled).
    # Applied to dense COSINE SIMILARITY, not to the RRF score: calibration showed RRF
    # scores separate answerable from unanswerable questions not at all, because rank 1
    # exists however irrelevant the candidates are.
    #
    # Set deliberately low, and this is the weakest point in the system — say so rather
    # than hide it. Cross-lingual cosine similarities compress into a narrow band
    # (0.72-0.84 on this corpus), so no value separates answerable Urdu questions from
    # unanswerable ones well: 0.75 keeps 94% and blocks 14%; 0.774 blocks 43% but
    # (set to 0.72, not 0.75, after a live miss: "What is the NTN number?" — a
    # perfectly answerable question — scored 0.746 and was blocked, while the same
    # question naming the company scored 0.833. Short queries with no subject sit low
    # in this compressed band, and blocking a real question is a far worse kiosk
    # failure than answering an off-topic one. Lowest correct top-1 is 0.7305.)
    # throws away 26% of answerable questions. Recall is the better trade here because
    # the system prompt still refuses to answer from irrelevant context.
    #
    # The real fix is the multilingual cross-encoder, which gates Urdu at 91% kept /
    # 83% blocked — but costs ~340 ms. See the "quality profile" section of
    # README-RAG.md; it is a deployment decision, not a default.
    dense_score_threshold: float = 0.72
    # Secondary, RELATIVE floor: once the top chunk has cleared the absolute threshold,
    # drop supporting chunks scoring below this fraction of it. Absolute thresholds
    # cannot do this job — chunk 3 of a genuinely well-answered question scores far
    # below chunk 1 of it, and far above chunk 1 of a poorly-answered one. Set to 0 to
    # always return the full top_k.
    relative_score_floor: float = 0.10

    # Hard ceiling on assembled context. Time-to-first-token on the voice path scales
    # with prompt length, and past this the LLM starts ignoring the middle anyway.
    max_context_chars: int = 6000

    # ── query rewriting ─────────────────────────────────────────────
    # Spoken follow-ups are elliptical ("what about their pricing?"), and embedding one
    # verbatim retrieves against the pronoun. Rewriting fixes that, but it is an LLM
    # call in the middle of the latency budget, so it is conditional AND timeout-guarded:
    # on timeout the raw transcript is used and the turn proceeds. Never blocking.
    rewrite_enabled: bool = True
    rewrite_timeout_ms: int = 150
    # Below this many content words a query is treated as too thin to retrieve on its
    # own, which together with the pronoun trigger is what keeps rewriting rare.
    rewrite_min_content_words: int = 4
    rewrite_history_turns: int = 3
    rewrite_model: str = ""  # defaults to the main LLM model when empty

    # Feed server/knowledge.py's curated Urdu->English expansion into the sparse/BM25
    # channel. Measured worth: without it the hybrid retriever loses 15 points of hit@5
    # against the old BM25 retriever on Urdu questions, while beating it by 6 on English
    # ones. See server/services/expansion.py for why a multilingual embedding does not
    # make this redundant.
    expand_urdu_lexical: bool = True

    # ── caching ─────────────────────────────────────────────────────
    # Kiosk visitors repeat themselves, and several people ask the same question in a
    # row at a public terminal. Both caches are per-process and cleared on ingest.
    embed_cache_size: int = 512
    result_cache_size: int = 256
    result_cache_ttl_s: float = 300.0

    # ── qdrant ──────────────────────────────────────────────────────
    qdrant_host: str = "127.0.0.1"
    qdrant_port: int = 6333
    qdrant_api_key: str = ""
    qdrant_collection: str = "mari_knowledge"
    qdrant_timeout_s: float = 5.0
    # qdrant-client silently switches to HTTPS the moment an api_key is set. Inside a
    # compose/Coolify network Qdrant speaks plaintext, so that flip turns into a TLS
    # handshake against an HTTP port and surfaces as an unrelated-looking connection
    # error. Passing https=False explicitly is the fix; this flag exists so a genuinely
    # TLS-terminated deployment can still turn it back on.
    qdrant_https: bool = False

    # ── ingestion ───────────────────────────────────────────────────
    corpus_dir: Path = ROOT / "server" / "data"
    # Filenames to skip inside the corpus directory. README.md there documents the
    # corpus rather than being part of it, and ingesting it puts a chunk about file
    # layout and environment variables into the index — which then legitimately matches
    # questions about "the knowledge base" and displaces real content.
    corpus_exclude: list[str] = ["README.md"]
    metadata_db: Path = ROOT / "server" / "data" / ".rag_metadata.sqlite"
    force_reingest: bool = False
    # Ingest embeds in batches; larger is faster but holds more memory. Only touched at
    # startup, so it trades against boot time, not turn latency.
    ingest_batch_size: int = 32

    # ── behaviour ───────────────────────────────────────────────────
    # Force-inject abbreviation definitions matched in the query regardless of what
    # retrieval returned. A corpus can use "MSPC" fifty times and define it once; top-k
    # will happily return only the chunks that use it, and the model then invents the
    # expansion. Deterministic guardrail over a probabilistic retriever.
    glossary_injection: bool = True
    log_stage_timings: bool = True

    @model_validator(mode="after")
    def _resolve_prefixes(self) -> "RagSettings":
        """Fill in the asymmetric-model prefixes from the model name, unless overridden.

        Doing this by lookup rather than by configuration means a model swap cannot
        leave a stale prefix behind — the failure mode that makes this worth automating
        is that a wrong prefix degrades recall without ever raising anything.
        """
        if not self.query_prefix and not self.passage_prefix:
            name = self.dense_model.lower()
            if "e5" in name:
                # E5 family: "query: " / "passage: ", both required.
                self.query_prefix, self.passage_prefix = "query: ", "passage: "
            elif "bge" in name and "-v1.5" in name and name.endswith("-en-v1.5"):
                # BGE v1.5 English: query side only; passages are embedded bare.
                self.query_prefix = "Represent this sentence for searching relevant passages: "
            # bge-m3, mxbai, nomic, arctic and the paraphrase-* models are symmetric —
            # no prefix, and adding one would hurt.
        return self

    @property
    def chunk_overlap_tokens(self) -> int:
        return max(0, int(self.chunk_tokens * self.chunk_overlap_ratio))


@lru_cache(maxsize=1)
def get_settings() -> RagSettings:
    return RagSettings()
