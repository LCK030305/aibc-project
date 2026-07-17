# RAGAS Evaluation Report

- **Framework**: RAGAS v0.4.3 (industry-standard RAG eval)
- **Judge LLM**: `gpt-4.1-mini @ temperature=0`
- **Judge embeddings**: `text-embedding-3-small`
- **Run time**: 2026-06-14T08:57:22
- **Scenarios evaluated**: 10 of 10

## Aggregate scores

| Metric | Score | Range | Interpretation |
|---|---:|---|---|
| `faithfulness` | 0.467 | 0.0 – 1.0 | Higher = fewer hallucinations vs. retrieved context. |
| `answer_relevancy` | 0.755 | 0.0 – 1.0 | Higher = answer is more on-topic for the question. |
| `llm_context_precision_with_reference` | 0.788 | 0.0 – 1.0 | Higher = relevant chunks ranked above irrelevant ones. |
| `context_recall` | 0.500 | 0.0 – 1.0 | Higher = ground-truth coverage in retrieved contexts. |
| `factual_correctness(mode=f1)` | 0.318 | 0.0 – 1.0 | F1 between answer claims and reference claims. |

## Per-scenario scores

| ID | Scenario | `faithfulness` | `answer_relevancy` | `llm_context_precision_with_reference` | `context_recall` | `factual_correctness(mode=f1)` |
|---|---|---:|---:|---:|---:|---:|
| S01 | Simple financial help — ComCare | 0.593 | 0.780 | 0.849 | 0.667 | 0.310 |
| S02 | Healthcare subsidies — CHAS / MediFund | 0.650 | 0.791 | 0.600 | 0.333 | 0.210 |
| S03 | Caregiver of dementia parent | 0.560 | 0.782 | 0.716 | 0.833 | 0.620 |
| S04 | Disability — assistive technology | 0.615 | 0.793 | 0.457 | 0.500 | 0.300 |
| S05 | Teen suicide warning signs | 0.118 | 0.689 | 0.826 | 0.333 | 0.240 |
| S06 | Family in crisis — FSC + counselling | 0.733 | 0.731 | 0.821 | 0.333 | 0.470 |
| S07 | Low-income family with young child — KidSTART | 0.647 | 0.741 | 0.854 | 0.833 | 0.620 |
| S08 | Housing — rental + grant for young couple | 0.273 | 0.836 | 1.000 | 0.667 | 0.100 |
| S09 | Senior — silver care continuum | 0.214 | 0.628 | 0.928 | 0.333 | 0.150 |
| S10 | Complex multi-need (Least-to-Most stress test) | 0.267 | 0.780 | 0.833 | 0.167 | 0.160 |

## How to read these scores

- **Faithfulness** is the most important — it directly measures whether the LLM hallucinates eligibility details that aren't in the retrieved SupportGoWhere text. For a public-sector tool this is the single hardest constraint.
- **Context Recall** measures whether the retriever surfaced the evidence the answer needed. Low recall ⇒ either the reference is broader than what's actually relevant for that case, or our retriever missed a record.
- **Factual Correctness** uses F1 over claims; ~0.3–0.5 is normal when the reference and answer use different vocabularies for the same facts.
- All RAGAS scores are LLM-judged and **approximate**. Use them alongside the deterministic retrieval@k metrics in `eval_report.{json,md}` for a complete picture.
