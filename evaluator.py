"""RAG evaluator for UC#1 — Topic 4.5 RAG Evaluation.

Two complementary metrics over a hand-curated set of client scenarios:

  1. **Retrieval@k**  — does the embedding retriever surface the expected
     schemes/services? Measured as recall@5, recall@10, MRR (mean
     reciprocal rank), and overall accuracy across all scenarios.
     This is the *retrieval-quality* signal — independent of the LLM
     re-ranker.

  2. **LLM-judge**    — for each scenario, take the recommender's final
     output and have a separate LLM grade it on a rubric (relevance,
     evidence quality, eligibility-flag usefulness). This is the
     *generation-quality* signal — captures whether the re-ranker is
     making good selections from the retrieved pool.

Bootcamp-principles cheat sheet
-------------------------------
- Topic 4.5 § RAG Evaluation — the exact lesson being implemented here.
- Topic 4.4 § Post-retrieval — eval results inform whether the re-ranker
  is improving over plain top-K retrieval.
- Topic 2.7 § Exception Handling — eval keeps going if one scenario
  errors; failures are logged not crashed.

Run
---
    python evaluator.py              # full retrieval@k eval + LLM judge
    python evaluator.py --no-llm     # retrieval@k only (faster, free)
    python evaluator.py --quick      # 3 scenarios only, retrieval@k only

Writes:
    eval/eval_report.json   — machine-readable full report
    eval/eval_report.md     — human-readable summary table
"""

from __future__ import annotations

import argparse
import io
import json
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from statistics import mean

# Force UTF-8 stdout (Windows PowerShell cp1252 defence).
try:
    if (
        hasattr(sys.stdout, "isatty")
        and sys.stdout.isatty()
        and sys.stdout.encoding
        and sys.stdout.encoding.lower() != "utf-8"
    ):
        sys.stdout = io.TextIOWrapper(
            sys.stdout.buffer, encoding="utf-8", line_buffering=True
        )
except (AttributeError, OSError, ValueError):
    pass

from llm import get_completion_from_messages
from recommender import recommend
from retriever import get_retriever

ROOT = Path(__file__).parent
EVAL_DIR = ROOT / "eval"
EVAL_DATA = EVAL_DIR / "eval_data.json"
REPORT_JSON = EVAL_DIR / "eval_report.json"
REPORT_MD = EVAL_DIR / "eval_report.md"

K_VALUES = (5, 10)  # measure recall@5 and recall@10


# ---------------------------------------------------------------------------
# Metric helpers
# ---------------------------------------------------------------------------

def recall_at_k(expected: set[str], retrieved: list[str], k: int) -> float:
    """Fraction of expected items present in the top-k retrieved list."""
    if not expected:
        return 0.0
    top_k = set(retrieved[:k])
    return len(expected & top_k) / len(expected)


def precision_at_k(expected: set[str], retrieved: list[str], k: int) -> float:
    """Fraction of top-k retrieved items that are in the expected set."""
    if k <= 0:
        return 0.0
    top_k = retrieved[:k]
    if not top_k:
        return 0.0
    return sum(1 for r in top_k if r in expected) / len(top_k)


def mrr(expected: set[str], retrieved: list[str]) -> float:
    """Mean reciprocal rank — 1 / rank of first expected hit; 0 if none."""
    for i, item in enumerate(retrieved, start=1):
        if item in expected:
            return 1.0 / i
    return 0.0


# ---------------------------------------------------------------------------
# Retrieval evaluation
# ---------------------------------------------------------------------------

@dataclass
class RetrievalResult:
    scenario_id: str
    label: str
    expected: list[str]
    retrieved_top10: list[str]
    recall_at_k: dict[int, float] = field(default_factory=dict)
    precision_at_k: dict[int, float] = field(default_factory=dict)
    mrr_score: float = 0.0
    error: str | None = None


def evaluate_retrieval(scenario: dict) -> RetrievalResult:
    """Run the retriever over a scenario and compute retrieval metrics."""
    expected = set(scenario["expected_parent_ids"])
    try:
        retriever = get_retriever()
        results = retriever.search(
            scenario["client_situation"], k=max(K_VALUES) + 5
        )
        retrieved_ids = [r.parent_id for r in results]
    except Exception as exc:  # noqa: BLE001
        return RetrievalResult(
            scenario_id=scenario["id"],
            label=scenario["label"],
            expected=list(expected),
            retrieved_top10=[],
            error=f"{type(exc).__name__}: {exc}",
        )

    out = RetrievalResult(
        scenario_id=scenario["id"],
        label=scenario["label"],
        expected=list(expected),
        retrieved_top10=retrieved_ids[:10],
        mrr_score=mrr(expected, retrieved_ids),
    )
    for k in K_VALUES:
        out.recall_at_k[k] = recall_at_k(expected, retrieved_ids, k)
        out.precision_at_k[k] = precision_at_k(expected, retrieved_ids, k)
    return out


# ---------------------------------------------------------------------------
# LLM-judge evaluation
# ---------------------------------------------------------------------------

JUDGE_SYSTEM_PROMPT = """\
You are a SENIOR Singapore SAO trainer reviewing AI-produced
recommendations. Your job is to be **critical and honest** — most
recommendations should NOT score 5/5 unless they are genuinely
excellent. Calibration matters more than encouragement.

Rate THREE dimensions on a 1-5 scale with these anchors:

  5  Excellent. Recommendations directly fit the case. Rationales are
     specific to THIS client's circumstances. Eligibility flags point
     at exactly the right verification items. No obvious gaps.
  4  Good. Solid fit with minor caveats (a slightly generic rationale,
     or one missing flag that an experienced SAO would expect).
  3  Mediocre. Partially fits. Recommendations cover only part of the
     case OR rationales are generic OR flags are vague.
  2  Poor. Marginally relevant or significantly off. The SAO would not
     forward these to the family without major edits.
  1  Terrible. Misleading or off-topic.

THREE dimensions:
  - relevance         : Do the recommendations actually fit the client's
                        situation? Are any major needs uncovered?
  - evidence_quality  : Are rationales SPECIFIC to this client (not
                        repeated boilerplate from the scheme description)?
                        Do they cite concrete evidence from the scheme?
  - eligibility_flags : Are the verify-with-client items the RIGHT ones
                        (income, age, citizenship, household composition
                        — the things that actually determine eligibility),
                        or are they generic ("confirm details with SAO")?

Important: a 5 means "I have nothing to suggest improving." If you can
identify ANY plausible improvement — a missed need, a vague rationale,
a missing flag — the score should be 4 or below.

Also: identify the strongest WEAKNESS of this output in one short
phrase. If there's no real weakness, write "none".

Output a single JSON object:
{
  "relevance":         <int 1-5>,
  "evidence_quality":  <int 1-5>,
  "eligibility_flags": <int 1-5>,
  "weakness":          "<one short phrase, or 'none'>",
  "overall_comment":   "<one short sentence>"
}
"""


@dataclass
class JudgeResult:
    scenario_id: str
    label: str
    relevance: int = 0
    evidence_quality: int = 0
    eligibility_flags: int = 0
    weakness: str = ""
    overall_comment: str = ""
    error: str | None = None

    @property
    def mean(self) -> float:
        return mean([self.relevance, self.evidence_quality, self.eligibility_flags])


def evaluate_with_llm_judge(scenario: dict) -> JudgeResult:
    """Run the recommender on the scenario, then have a separate LLM judge it."""
    try:
        response = recommend(
            scenario["client_situation"],
            k_candidates=15,
            n_recommendations=5,
        )
    except Exception as exc:  # noqa: BLE001
        return JudgeResult(
            scenario_id=scenario["id"],
            label=scenario["label"],
            error=f"recommender failed: {type(exc).__name__}: {exc}",
        )
    if response.blocked or not response.recommendations:
        return JudgeResult(
            scenario_id=scenario["id"],
            label=scenario["label"],
            error="no recommendations to judge (blocked or empty)",
        )

    # Format the recommendations for the judge.
    recs_block_lines: list[str] = []
    for r in response.recommendations:
        recs_block_lines.append(
            f"- [{r.fit_score}/5] {r.title} ({r.kind}, id {r.parent_id})\n"
            f"    rationale: {r.rationale}\n"
            f"    flags: {'; '.join(r.eligibility_flags) or '(none)'}"
        )
    recs_block = "\n".join(recs_block_lines)

    user_msg = (
        f"<client_situation>\n{scenario['client_situation']}\n</client_situation>\n\n"
        f"<recommendations>\n{recs_block}\n</recommendations>"
    )
    messages = [
        {"role": "system", "content": JUDGE_SYSTEM_PROMPT},
        {"role": "user",   "content": user_msg},
    ]
    try:
        raw = get_completion_from_messages(
            messages, max_tokens=300, response_format={"type": "json_object"},
        )
        parsed = json.loads(raw)
    except Exception as exc:  # noqa: BLE001
        return JudgeResult(
            scenario_id=scenario["id"],
            label=scenario["label"],
            error=f"judge failed: {type(exc).__name__}: {exc}",
        )

    return JudgeResult(
        scenario_id=scenario["id"],
        label=scenario["label"],
        relevance=int(parsed.get("relevance", 0) or 0),
        evidence_quality=int(parsed.get("evidence_quality", 0) or 0),
        eligibility_flags=int(parsed.get("eligibility_flags", 0) or 0),
        weakness=str(parsed.get("weakness", "")).strip(),
        overall_comment=str(parsed.get("overall_comment", "")).strip(),
    )


# ---------------------------------------------------------------------------
# Main runner
# ---------------------------------------------------------------------------

def run(quick: bool = False, no_llm: bool = False) -> None:
    scenarios = json.loads(EVAL_DATA.read_text(encoding="utf-8"))
    if quick:
        scenarios = scenarios[:3]

    print("=" * 70)
    print(f"RAG Evaluation — Topic 4.5")
    print(f"Scenarios: {len(scenarios)}  |  LLM judge: {'OFF' if no_llm else 'ON'}")
    print("=" * 70)

    retrieval_results: list[RetrievalResult] = []
    judge_results: list[JudgeResult] = []

    t_start = time.perf_counter()
    for sc in scenarios:
        print(f"\n  [{sc['id']}] {sc['label']}")
        r = evaluate_retrieval(sc)
        retrieval_results.append(r)
        if r.error:
            print(f"      ! retrieval error: {r.error}")
            continue
        print(f"      retrieval@5  recall={r.recall_at_k[5]:.2f}  precision={r.precision_at_k[5]:.2f}")
        print(f"      retrieval@10 recall={r.recall_at_k[10]:.2f}  precision={r.precision_at_k[10]:.2f}")
        print(f"      MRR          {r.mrr_score:.3f}")
        if not no_llm:
            j = evaluate_with_llm_judge(sc)
            judge_results.append(j)
            if j.error:
                print(f"      ! judge error: {j.error}")
            else:
                print(f"      LLM judge    relevance={j.relevance}/5  "
                      f"evidence={j.evidence_quality}/5  flags={j.eligibility_flags}/5  "
                      f"(mean={j.mean:.2f})")

    elapsed = time.perf_counter() - t_start

    # Aggregate
    valid_r = [r for r in retrieval_results if r.error is None]
    agg_recall = {
        k: round(mean(r.recall_at_k[k] for r in valid_r), 3) if valid_r else 0
        for k in K_VALUES
    }
    agg_precision = {
        k: round(mean(r.precision_at_k[k] for r in valid_r), 3) if valid_r else 0
        for k in K_VALUES
    }
    agg_mrr = round(mean(r.mrr_score for r in valid_r), 3) if valid_r else 0

    valid_j = [j for j in judge_results if j.error is None]
    agg_judge = {
        "relevance":         round(mean(j.relevance for j in valid_j), 2) if valid_j else None,
        "evidence_quality":  round(mean(j.evidence_quality for j in valid_j), 2) if valid_j else None,
        "eligibility_flags": round(mean(j.eligibility_flags for j in valid_j), 2) if valid_j else None,
        "mean":              round(mean(j.mean for j in valid_j), 2) if valid_j else None,
    }

    print()
    print("=" * 70)
    print("AGGREGATE")
    print("=" * 70)
    for k in K_VALUES:
        print(f"  recall@{k}     : {agg_recall[k]:.3f}")
        print(f"  precision@{k}  : {agg_precision[k]:.3f}")
    print(f"  MRR           : {agg_mrr:.3f}")
    if valid_j:
        print(f"  LLM judge     : relevance={agg_judge['relevance']}/5  "
              f"evidence={agg_judge['evidence_quality']}/5  "
              f"flags={agg_judge['eligibility_flags']}/5  "
              f"mean={agg_judge['mean']}/5")
    print(f"  duration      : {elapsed:.1f}s")

    # Save report
    EVAL_DIR.mkdir(parents=True, exist_ok=True)
    report = {
        "n_scenarios": len(scenarios),
        "n_retrieval_ok": len(valid_r),
        "n_retrieval_errors": len(retrieval_results) - len(valid_r),
        "aggregate": {
            "recall_at_k": agg_recall,
            "precision_at_k": agg_precision,
            "MRR": agg_mrr,
            "llm_judge": agg_judge if valid_j else None,
        },
        "duration_sec": round(elapsed, 1),
        "per_scenario": [
            {
                "id": r.scenario_id,
                "label": r.label,
                "expected": r.expected,
                "retrieved_top10": r.retrieved_top10,
                "recall_at_k": r.recall_at_k,
                "precision_at_k": r.precision_at_k,
                "MRR": r.mrr_score,
                "error": r.error,
                "judge": next(
                    (
                        {
                            "relevance": j.relevance,
                            "evidence_quality": j.evidence_quality,
                            "eligibility_flags": j.eligibility_flags,
                            "weakness": j.weakness,
                            "overall_comment": j.overall_comment,
                            "error": j.error,
                        }
                        for j in judge_results
                        if j.scenario_id == r.scenario_id
                    ),
                    None,
                ),
            }
            for r in retrieval_results
        ],
    }
    REPORT_JSON.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    # Markdown summary
    md_lines: list[str] = []
    md_lines.append("# RAG Evaluation Report (Topic 4.5)\n")
    md_lines.append(f"Scenarios evaluated: **{len(scenarios)}**  |  "
                    f"Duration: **{elapsed:.1f}s**\n")
    md_lines.append("## Aggregate metrics\n")
    md_lines.append("| Metric | Value |")
    md_lines.append("|---|---|")
    for k in K_VALUES:
        md_lines.append(f"| recall@{k} | {agg_recall[k]:.3f} |")
        md_lines.append(f"| precision@{k} | {agg_precision[k]:.3f} |")
    md_lines.append(f"| MRR | {agg_mrr:.3f} |")
    if valid_j:
        md_lines.append(f"| LLM judge — relevance | {agg_judge['relevance']}/5 |")
        md_lines.append(f"| LLM judge — evidence | {agg_judge['evidence_quality']}/5 |")
        md_lines.append(f"| LLM judge — flags | {agg_judge['eligibility_flags']}/5 |")
        md_lines.append(f"| LLM judge — mean | {agg_judge['mean']}/5 |")
    md_lines.append("\n## Per-scenario\n")
    md_lines.append("| ID | Label | recall@5 | recall@10 | MRR | Judge mean |")
    md_lines.append("|---|---|---|---|---|---|")
    for r in retrieval_results:
        if r.error:
            md_lines.append(f"| {r.scenario_id} | {r.label} | ERR | ERR | ERR | — |")
            continue
        j = next((j for j in judge_results if j.scenario_id == r.scenario_id), None)
        judge_str = (
            f"{j.mean:.1f}/5" if j and not j.error
            else ("err" if j and j.error else "—")
        )
        md_lines.append(
            f"| {r.scenario_id} | {r.label} | "
            f"{r.recall_at_k[5]:.2f} | {r.recall_at_k[10]:.2f} | "
            f"{r.mrr_score:.3f} | {judge_str} |"
        )
    REPORT_MD.write_text("\n".join(md_lines), encoding="utf-8")

    print()
    print(f"Saved: {REPORT_JSON.relative_to(ROOT)}")
    print(f"Saved: {REPORT_MD.relative_to(ROOT)}")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--quick", action="store_true", help="Run only 3 scenarios")
    p.add_argument("--no-llm", action="store_true", help="Skip LLM-judge step")
    args = p.parse_args()
    run(quick=args.quick, no_llm=args.no_llm)
