# RAGAS Evaluation Report

- **Framework**: RAGAS v0.4.3 (industry-standard RAG eval)
- **Judge LLM**: `gpt-4.1-mini @ temperature=0`
- **Judge embeddings**: `text-embedding-3-small`
- **Run time**: 2026-06-16T10:55:58
- **Scenarios evaluated**: 9 of 10

## Aggregate scores

| Metric | Score | Range | Interpretation |
|---|---:|---|---|
| `faithfulness` | 0.652 | 0.0 – 1.0 | Higher = fewer hallucinations vs. retrieved context. |
| `answer_relevancy` | 0.729 | 0.0 – 1.0 | Higher = answer is more on-topic for the question. |
| `llm_context_precision_with_reference` | 0.582 | 0.0 – 1.0 | Higher = relevant chunks ranked above irrelevant ones. |
| `context_recall` | 0.574 | 0.0 – 1.0 | Higher = ground-truth coverage in retrieved contexts. |
| `factual_correctness(mode=f1)` | 0.358 | 0.0 – 1.0 | F1 between answer claims and reference claims. |

## Per-scenario scores

| ID | Scenario | `faithfulness` | `answer_relevancy` | `llm_context_precision_with_reference` | `context_recall` | `factual_correctness(mode=f1)` |
|---|---|---:|---:|---:|---:|---:|
| S01 | Simple financial help — ComCare | 0.750 | 0.780 | 1.000 | 0.667 | 0.230 |
| S02 | Healthcare subsidies — CHAS / MediFund | 0.421 | 0.777 | 0.200 | 0.000 | 0.320 |
| S03 | Caregiver of dementia parent | 0.826 | 0.782 | 0.849 | 0.833 | 0.340 |
| S04 | Disability — assistive technology | 0.636 | 0.793 | 0.525 | 1.000 | 0.240 |
| S05 | Teen suicide warning signs | 0.474 | 0.727 | 0.243 | 0.500 | 0.480 |
| S06 | Family in crisis — FSC + counselling | 0.750 | 0.730 | 0.333 | 0.500 | 0.450 |
| S07 | Low-income family with young child — KidSTART | 1.000 | 0.616 | 0.685 | 0.500 | 0.670 |
| S09 | Senior — silver care continuum | 0.556 | 0.608 | 0.567 | 0.500 | 0.310 |
| S10 | Complex multi-need (Least-to-Most stress test) | 0.458 | 0.746 | 0.833 | 0.667 | 0.180 |

## How to read these scores

- **Faithfulness** is the most important — it directly measures whether the LLM hallucinates eligibility details that aren't in the retrieved SupportGoWhere text. For a public-sector tool this is the single hardest constraint.
- **Context Recall** measures whether the retriever surfaced the evidence the answer needed. Low recall ⇒ either the reference is broader than what's actually relevant for that case, or our retriever missed a record.
- **Factual Correctness** uses F1 over claims; ~0.3–0.5 is normal when the reference and answer use different vocabularies for the same facts.
- All RAGAS scores are LLM-judged and **approximate**. Use them alongside the deterministic retrieval@k metrics in `eval_report.{json,md}` for a complete picture.
