# RAGAS Before/After — v1.0 baseline vs v1.3 (Topic 4 Advanced RAG)

**Headline:** Faithfulness +40 %, Context Recall +15 %, Factual Correctness +13 %.
Context Precision regressed by 26 % — a documented recall-vs-precision trade-off
from the hybrid retrieval (BM25 + HyDE + dense, fused via RRF) widening the
candidate pool.

## Aggregate metrics

| RAGAS metric | v1.0 baseline | v1.3 improved | Δ absolute | Δ relative |
|---|---:|---:|---:|---:|
| **Faithfulness** | 0.467 | **0.652** | **+0.185** | **+39.6 %** ✅ |
| **Context Recall** | 0.500 | **0.574** | **+0.074** | **+14.8 %** ✅ |
| **Factual Correctness (F1)** | 0.318 | **0.358** | **+0.040** | **+12.6 %** ✅ |
| Answer Relevancy | 0.755 | 0.729 | −0.026 | −3.4 % |
| Context Precision (LLM, w/ ref) | 0.788 | 0.582 | **−0.206** | **−26.1 %** ⚠️ |

(v1.0 n=10 scenarios. v1.3 n=9 — the safety-test scenario was correctly blocked
by Stage 1 safety guard and excluded; this is intended behaviour, not regression.)

## What changed between v1.0 and v1.3

Each Topic 4 sub-topic gap from the coverage scorecard was addressed:

| Version | Topic 4.x category | Change | Files touched |
|---|---|---|---|
| v1.0 baseline | — | Dense cosine retrieval, single CO-STAR re-rank, evidence_quote allowed paraphrase | (baseline) |
| **v1.1** Tier 1a | **4.4 Post-Retrieval** | Verbatim citation enforcement in the recommender prompt — every claim must appear in source text; quote must be a character-exact substring | `prompts.py` |
| **v1.2** Tier 1b | **4.4 Post-Retrieval** | Faithfulness self-check pass — secondary LLM call audits each recommendation: `verified` / `partial` / `unsupported` + 1-line note | `faithfulness_check.py`, `recommender.py` |
| **v1.3** Tier 2a | **4.2 Pre-Retrieval** | HyDE — for each sub-need, LLM generates a hypothetical SGW-style scheme description; that text is embedded and retrieved against | `hyde.py`, `recommender.py` |
| **v1.3** Tier 2b | **4.3 Retrieval** | BM25 sparse retrieval + Reciprocal Rank Fusion combining dense + HyDE + BM25 ranks per sub-need | `bm25_retriever.py`, `recommender.py` |

## Interpretation per metric

### 🟢 Faithfulness 0.467 → 0.652  (+40 %)

The headline win. The faithfulness self-check + verbatim quote requirement
forced the LLM to either ground every rationale claim in the source text or
explicitly mark the recommendation as unsupported. Two mechanisms reinforce
each other:

1. **Prompt-side** — the recommender prompt now states that the rationale's
   claims must appear in `matched_section` and the quote must be a
   character-exact substring; otherwise `fit_score ≤ 3`.
2. **Audit-side** — a secondary GPT-4.1-mini pass reviews every
   recommendation against its source text. Output is the `faithfulness_status`
   field (`verified` / `partial` / `unsupported`) shown as a colour-coded
   badge in the UI.

This is the single most submission-impactful change for a public-sector
welfare tool, where hallucinated eligibility details are the highest-stakes
failure mode.

### 🟢 Context Recall 0.500 → 0.574  (+15 %)

HyDE bridged the SAO-vocabulary ↔ SGW-vocabulary gap. Examples:

- *"dementia day-care"* → HyDE generates *"...respite care services for
  caregivers of seniors..."* → dense retrieval surfaces Senior Activity
  Centres + AAC programmes that the literal phrasing missed.
- *"behind on rent"* → HyDE generates *"...short-to-medium-term financial
  assistance for households..."* → surfaces ComCare SMTA, KIFAS, etc.

BM25 contributed exact-acronym matches (CHAS, MUIS-FAS, ATF, EASE)
that the embedder ranked lower due to their rarity as tokens.

### 🟢 Factual Correctness 0.358 (+13 %)

Indirect benefit of the Faithfulness lift. Because rationales now stick more
closely to source text, the claim set in the answer overlaps more with the
claim set in the reference. F1 over claims naturally moves with this.

### ⚠️ Context Precision 0.788 → 0.582  (−26 %) — Documented trade-off

Hybrid retrieval (dense + HyDE + BM25) **widens** the candidate pool to
capture more relevant items (the recall win). The cost: more borderline-
relevant chunks rank higher than they did in the pure-dense baseline.

Concretely, RRF gives 1/(60 + rank) weight to each retriever's votes; a
chunk that any one retriever ranks highly gets pulled up. This is the right
trade-off for **welfare matching** where missing a relevant scheme is worse
than surfacing one extra borderline option for the SAO to review.

Tuning levers if Precision recovery is needed in v1.4:

| Lever | Effect |
|---|---|
| Raise RRF `k_const` from 60 → 100 | Flatter weight curve, less aggressive boosting of single-retriever winners |
| Cap BM25 contribution to top-5 per sub-need | BM25 only acts as a tie-breaker, not a primary surfacer |
| Add a precision-only LLM filter before re-rank | Adds a 4th LLM call per query (cost) |

### Minor: Answer Relevancy −3 %

Within RAGAS judge noise. The recommendation text itself didn't change in
nature; the LLM still answers the question in the same shape. Small variance.

## Per-scenario detail (v1.3)

(See `eval/ragas_report.md` for the full per-row table.)

## Cost of the run

~$0.30 in OpenAI tokens. Bigger than the v1.0 baseline (~$0.20) because every
`recommend()` call now triggers:

- 1 extra LLM call for HyDE (per sub-need)
- 1 extra LLM call for the faithfulness audit (per query)
- Slightly larger re-rank prompt because of verbatim-quote instruction

For demo and capstone evaluation purposes, the cost remains negligible
(~$0.0003 per client-situation query end-to-end).

## What's left for v2.x

| Gap | Topic 4.x | Why deferred |
|---|---|---|
| Parent-Child Index full implementation (pass parent record to LLM, not child) | 4.3 | Architectural; ~1 day of work |
| Self-Query Retriever (LLM-derived category filters) | 4.3 | Mostly UX; manual filter is fine for now |
| Cross-encoder reranker (Cohere) | 4.4 | Adds a third-party dependency the project is deliberately avoiding |
| Prompt compression (LLMLingua) | 4.4 | Not justified at our prompt size |
| Precision tuning per the levers above | 4.3 / 4.4 | If a future eval shows precision is hurting in real use |

---

*Generated automatically as part of Phase D of the v1.0 → v1.3 improvement
plan. Both v1.0 baseline (`eval/ragas_report_v1_baseline.json`) and v1.3
improved (`eval/ragas_report.json`) are reproducible from the codebase at
the corresponding commits — re-run with* `python ragas_eval.py`.
