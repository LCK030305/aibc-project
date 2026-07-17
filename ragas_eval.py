"""RAGAS evaluation harness — Topic 4.5 third-party metrics.

Runs the five canonical RAGAS metrics on our 10 hand-curated eval
scenarios and outputs both ``eval/ragas_report.json`` (machine-readable)
and ``eval/ragas_report.md`` (human-readable). Complementary to
``evaluator.py``:

- ``evaluator.py`` — our custom rubric + retrieval@k metrics
- ``ragas_eval.py`` — the industry-standard RAGAS framework

Metrics computed
----------------
- **Faithfulness** — answer claims grounded in retrieved contexts (no
  hallucination)
- **ResponseRelevancy** — answer actually addresses the question
- **LLMContextPrecisionWithReference** — relevant contexts ranked above
  irrelevant ones
- **LLMContextRecall** — ground-truth claims appear in retrieved contexts
- **FactualCorrectness** — factual agreement between answer and reference

Usage
-----
    python ragas_eval.py             # full 10-scenario run
    python ragas_eval.py --quick     # first 3 scenarios only
"""

from __future__ import annotations

import argparse
import io
import json
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# RAGAS 0.4.3 imports ChatVertexAI from a path that newer langchain-community
# has removed. We only use OpenAI, so stub the missing module before importing
# ragas. (Removable once ragas ships a release that drops this import.)
import types as _types  # noqa: E402

_vertex_stub = _types.ModuleType("langchain_community.chat_models.vertexai")
_vertex_stub.ChatVertexAI = type("ChatVertexAI", (), {})  # type: ignore
sys.modules["langchain_community.chat_models.vertexai"] = _vertex_stub

from langchain_openai import ChatOpenAI, OpenAIEmbeddings  # noqa: E402
from ragas import EvaluationDataset, evaluate  # noqa: E402
from ragas.dataset_schema import SingleTurnSample  # noqa: E402
from ragas.embeddings import LangchainEmbeddingsWrapper  # noqa: E402
from ragas.llms import LangchainLLMWrapper  # noqa: E402
from ragas.metrics import (  # noqa: E402
    FactualCorrectness,
    Faithfulness,
    LLMContextPrecisionWithReference,
    LLMContextRecall,
    ResponseRelevancy,
)

from recommender import recommend  # noqa: E402

ROOT = Path(__file__).parent
EVAL_DATA = ROOT / "eval" / "eval_data.json"
CHUNKS_FILE = ROOT / "data" / "chunks" / "chunks.jsonl"
OUT_JSON = ROOT / "eval" / "ragas_report.json"
OUT_MD = ROOT / "eval" / "ragas_report.md"


def _setup_utf8_stdout() -> None:
    try:
        if (
            hasattr(sys.stdout, "isatty")
            and sys.stdout.isatty()
            and sys.stdout.encoding
            and sys.stdout.encoding.lower() != "utf-8"
        ):
            sys.stdout = io.TextIOWrapper(
                sys.stdout.buffer, encoding="utf-8", line_buffering=True,
            )
    except (AttributeError, OSError, ValueError):
        pass


def load_parent_summaries() -> dict[str, str]:
    """Build a ``parent_id → one-line summary`` map from chunks.jsonl.

    Prefers the tagline section; falls back to the first chunk's text.
    """
    by_parent: dict[str, list[dict]] = defaultdict(list)
    with CHUNKS_FILE.open("r", encoding="utf-8") as f:
        for line in f:
            c = json.loads(line)
            by_parent[c["parent_id"]].append(c)

    summaries: dict[str, str] = {}
    for pid, chunks in by_parent.items():
        title = chunks[0].get("title", pid)
        tagline = next(
            (c["text"] for c in chunks if c.get("section") == "tagline"),
            chunks[0]["text"][:240],
        )
        summaries[pid] = f"{title}: {tagline}"
    return summaries


def build_reference(
    expected_ids: list[str], summaries: dict[str, str]
) -> str:
    """Synthesize a single ground-truth reference from expected parent_ids."""
    lines: list[str] = []
    for pid in expected_ids[:5]:  # cap at 5 for brevity
        if pid in summaries:
            lines.append(summaries[pid])
    if not lines:
        return "(no ground-truth summaries available)"
    body = "\n\n".join(f"- {ln}" for ln in lines)
    return f"Relevant programmes for this client situation:\n\n{body}"


def build_answer(response) -> str:
    """Flatten a RecommendationResponse into a single answer string."""
    parts: list[str] = []
    if response.overall_summary:
        parts.append(response.overall_summary)
    for rec in response.recommendations:
        parts.append(
            f"- {rec.title} (fit {rec.fit_score}/5): {rec.rationale} "
            f'Evidence: "{rec.evidence_quote}"'
        )
    return "\n\n".join(parts) if parts else "(no recommendations)"


def main() -> int:
    _setup_utf8_stdout()
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--quick", action="store_true",
        help="Only run the first 3 scenarios (cheaper smoke test).",
    )
    args = parser.parse_args()

    scenarios = json.loads(EVAL_DATA.read_text(encoding="utf-8"))
    if args.quick:
        scenarios = scenarios[:3]
        print(f"[--quick] running first {len(scenarios)} scenarios only")

    print(f"Loading parent summaries from {CHUNKS_FILE.name}...")
    summaries = load_parent_summaries()
    print(f"  Loaded {len(summaries)} parent records.\n")

    samples: list[SingleTurnSample] = []
    sample_meta: list[dict] = []

    print(f"Running recommend() on {len(scenarios)} scenarios...")
    for i, s in enumerate(scenarios, 1):
        print(f"  [{i}/{len(scenarios)}] {s['label']}")
        try:
            response = recommend(s["client_situation"])
        except Exception as exc:
            print(f"      ERROR: {type(exc).__name__}: {exc}")
            continue
        if response.blocked:
            print(f"      BLOCKED: {response.block_reason}")
            continue

        contexts = [
            r.section_text for r in response.retrieved_candidates[:10]
        ]
        answer = build_answer(response)
        reference = build_reference(s["expected_parent_ids"], summaries)

        samples.append(SingleTurnSample(
            user_input=s["client_situation"],
            retrieved_contexts=contexts,
            response=answer,
            reference=reference,
        ))
        sample_meta.append({
            "id": s["id"], "label": s["label"],
            "n_contexts": len(contexts),
            "n_recommendations": len(response.recommendations),
        })

    if not samples:
        print("\nNo successful samples — aborting.")
        return 1

    print(f"\nBuilt {len(samples)} RAGAS samples.")

    print("\nConfiguring RAGAS judge (gpt-4.1-mini, temperature=0)...")
    judge_llm = LangchainLLMWrapper(
        ChatOpenAI(model="gpt-4.1-mini", temperature=0)
    )
    judge_embeddings = LangchainEmbeddingsWrapper(
        OpenAIEmbeddings(model="text-embedding-3-small")
    )

    print("\nRunning RAGAS evaluation...")
    dataset = EvaluationDataset(samples=samples)
    metrics = [
        Faithfulness(llm=judge_llm),
        ResponseRelevancy(llm=judge_llm, embeddings=judge_embeddings),
        LLMContextPrecisionWithReference(llm=judge_llm),
        LLMContextRecall(llm=judge_llm),
        FactualCorrectness(llm=judge_llm),
    ]
    result = evaluate(dataset=dataset, metrics=metrics)

    # Per-row scores
    df = result.to_pandas()
    metric_cols = [
        c for c in df.columns
        if c not in {
            "user_input", "retrieved_contexts", "response", "reference"
        }
    ]
    per_row: list[dict] = []
    for idx, row in df.iterrows():
        rec = {"id": sample_meta[idx]["id"], "label": sample_meta[idx]["label"]}
        for c in metric_cols:
            v = row[c]
            try:
                rec[c] = float(v)
            except (TypeError, ValueError):
                rec[c] = None
        per_row.append(rec)

    aggregates = {}
    for c in metric_cols:
        vals = [
            float(v) for v in df[c]
            if v is not None and not (isinstance(v, float) and (v != v))  # NaN
        ]
        aggregates[c] = round(sum(vals) / len(vals), 3) if vals else None

    report = {
        "framework": "RAGAS v0.4.3 (industry-standard RAG eval)",
        "judge_llm": "gpt-4.1-mini @ temperature=0",
        "judge_embeddings": "text-embedding-3-small",
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "n_scenarios": len(scenarios),
        "n_evaluated": len(samples),
        "aggregates": aggregates,
        "per_row": per_row,
    }

    OUT_JSON.write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # ----- Markdown report -----
    md_lines = [
        "# RAGAS Evaluation Report",
        "",
        f"- **Framework**: {report['framework']}",
        f"- **Judge LLM**: `{report['judge_llm']}`",
        f"- **Judge embeddings**: `{report['judge_embeddings']}`",
        f"- **Run time**: {report['timestamp']}",
        f"- **Scenarios evaluated**: {report['n_evaluated']} of "
        f"{report['n_scenarios']}",
        "",
        "## Aggregate scores",
        "",
        "| Metric | Score | Range | Interpretation |",
        "|---|---:|---|---|",
    ]
    interpretations = {
        "faithfulness":
            "Higher = fewer hallucinations vs. retrieved context.",
        "answer_relevancy":
            "Higher = answer is more on-topic for the question.",
        "llm_context_precision_with_reference":
            "Higher = relevant chunks ranked above irrelevant ones.",
        "context_recall":
            "Higher = ground-truth coverage in retrieved contexts.",
        "factual_correctness(mode=f1)":
            "F1 between answer claims and reference claims.",
    }
    for col in metric_cols:
        v = aggregates.get(col)
        v_str = f"{v:.3f}" if v is not None else "n/a"
        interp = interpretations.get(col, "Higher = better.")
        md_lines.append(f"| `{col}` | {v_str} | 0.0 – 1.0 | {interp} |")

    md_lines += [
        "",
        "## Per-scenario scores",
        "",
        "| ID | Scenario | " + " | ".join(f"`{c}`" for c in metric_cols) + " |",
        "|---|---|" + "|".join(["---:"] * len(metric_cols)) + "|",
    ]
    for row in per_row:
        cells = []
        for c in metric_cols:
            v = row[c]
            cells.append(f"{v:.3f}" if isinstance(v, float) else "n/a")
        md_lines.append(
            f"| {row['id']} | {row['label']} | " + " | ".join(cells) + " |"
        )

    md_lines += [
        "",
        "## How to read these scores",
        "",
        "- **Faithfulness** is the most important — it directly measures "
        "whether the LLM hallucinates eligibility details that aren't in the "
        "retrieved SupportGoWhere text. For a public-sector tool this is "
        "the single hardest constraint.",
        "- **Context Recall** measures whether the retriever surfaced the "
        "evidence the answer needed. Low recall ⇒ either the reference is "
        "broader than what's actually relevant for that case, or our "
        "retriever missed a record.",
        "- **Factual Correctness** uses F1 over claims; ~0.3–0.5 is normal "
        "when the reference and answer use different vocabularies for the "
        "same facts.",
        "- All RAGAS scores are LLM-judged and **approximate**. Use them "
        "alongside the deterministic retrieval@k metrics in "
        "`eval_report.{json,md}` for a complete picture.",
        "",
    ]

    OUT_MD.write_text("\n".join(md_lines), encoding="utf-8")

    print(f"\nWrote:\n  {OUT_JSON.relative_to(ROOT)}\n  {OUT_MD.relative_to(ROOT)}")
    print("\nAggregate scores:")
    for col, val in aggregates.items():
        val_str = f"{val:.3f}" if val is not None else "n/a"
        print(f"  {col:<42} {val_str}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
