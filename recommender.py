"""LLM-based recommender for UC#1 — end-to-end pipeline.

Bootcamp-principles cheat sheet
-------------------------------
- Week 1 § Helper pattern        : ``recommend()`` is the single public
  entrypoint (mirrors ``get_completion`` in shape).
- Week 1 § CO-STAR               : prompt lives in prompts.py; we just
  compose retrieval + prompt + LLM.
- Week 2 § Prompt chaining       : explicit four-stage pipeline
  (retrieve → render → generate → parse).
- Week 2 § Exception handling    : defensive JSON parsing with fallback,
  validation that returned parent_ids came from the candidate pool.
- Week 4 § RAG                   : retrieval-augmented generation —
  candidates are the "R" (retrieved context), LLM is the "G" (generator).
- Week 5 § Post-retrieval re-rank: LLM re-ranks the embedding top-K with
  reasoning the embedding layer can't do.
- Week 5 § Evaluation hooks      : ``RecommendationResponse`` carries the
  raw LLM output and the input candidate pool so eval can replay /
  diff offline.
- Week 7+ § Streamlit-ready      : ``Recommendation`` is a dataclass with
  ``to_dict()`` for clean UI rendering.

Usage
-----
    from recommender import recommend
    resp = recommend("Single mother, lost her job, two children")
    for r in resp.recommendations:
        print(r.fit_score, r.title, r.rationale)

Run as a script for a 3-scenario demo:
    python recommender.py
"""

from __future__ import annotations

import io
import json
import sys
from dataclasses import asdict, dataclass, field
from json import JSONDecodeError

from llm import get_completion
from prompts import make_recommender_prompt, render_candidates_block
from retriever import Result, get_retriever

# Force UTF-8 stdout (Windows PowerShell default cp1252 breaks on zwsp).
# Wrapped in try/except so Streamlit / Jupyter contexts that pre-wrap
# stdout don't trip on the .buffer access.
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


@dataclass
class Recommendation:
    """One LLM-ranked recommendation with reasoning + evidence + provenance."""

    parent_id: str
    title: str
    fit_score: int                                # 1–5 from the LLM
    rationale: str                                # 1–2 sentences, why it fits
    eligibility_flags: list[str] = field(default_factory=list)
    evidence_quote: str = ""                      # verbatim phrase from corpus
    # Filled in from the retriever's Result (provenance for the UI).
    kind: str = ""                                # "scheme" or "service"
    url: str = ""
    categories: list[str] = field(default_factory=list)
    retrieval_score: float = 0.0                  # original cosine score

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class RecommendationResponse:
    """Full response from the recommender pipeline (UI + eval consume this)."""

    client_situation: str
    recommendations: list[Recommendation]
    overall_summary: str = ""
    categories_touched: list[str] = field(default_factory=list)
    retrieved_candidates: list[Result] = field(default_factory=list)
    raw_llm_output: str = ""                      # for debugging / eval replay

    def to_dict(self) -> dict:
        return {
            "client_situation": self.client_situation,
            "overall_summary": self.overall_summary,
            "categories_touched": self.categories_touched,
            "recommendations": [r.to_dict() for r in self.recommendations],
            "n_candidates_considered": len(self.retrieved_candidates),
        }


# ---------------------------------------------------------------------------
# Defensive JSON parsing — LLMs occasionally wrap output in code fences
# despite response_format being set, so we strip them as a fallback.
# ---------------------------------------------------------------------------

def _parse_llm_json(raw: str) -> dict:
    """Parse an LLM response into a dict, tolerating fenced code blocks."""
    try:
        return json.loads(raw)
    except JSONDecodeError:
        pass
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        # Remove opening fence (with optional language tag).
        cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else cleaned[3:]
        # Remove closing fence.
        if cleaned.rstrip().endswith("```"):
            cleaned = cleaned.rstrip()[:-3]
        try:
            return json.loads(cleaned)
        except JSONDecodeError as exc:
            raise RuntimeError(
                f"LLM did not return valid JSON. First 300 chars:\n{raw[:300]}"
            ) from exc
    raise RuntimeError(
        f"LLM did not return valid JSON. First 300 chars:\n{raw[:300]}"
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def recommend(
    client_situation: str,
    k_candidates: int = 15,
    n_recommendations: int = 5,
    category: str | None = None,
    kind: str | None = None,
) -> RecommendationResponse:
    """Run the full UC#1 pipeline: retrieve → re-rank → reason → structure.

    Args:
        client_situation  : Free-text description of the client's situation.
                            One short paragraph works best — too long and
                            the embedding signal dilutes.
        k_candidates      : How many candidates to pull from the retriever.
                            More = more options for the LLM to weigh but
                            longer prompt and higher cost. Default 15 keeps
                            prompt size ~15 KB which is well within limits.
        n_recommendations : Max recommendations to keep from the LLM output.
        category          : Optional SGW category slug to filter retrieval
                            (e.g., "financial-support" only).
        kind              : Optional "scheme" or "service" filter.

    Returns:
        :class:`RecommendationResponse` with structured results + provenance.

    Raises:
        ValueError    : on empty client_situation or invalid params.
        RuntimeError  : on unparseable LLM output (preserves the raw text in
                        the message so you can diagnose).
    """
    if not client_situation or not client_situation.strip():
        raise ValueError("client_situation must be a non-empty string")
    if k_candidates < 1 or n_recommendations < 1:
        raise ValueError("k_candidates and n_recommendations must be >= 1")
    if n_recommendations > k_candidates:
        raise ValueError("n_recommendations cannot exceed k_candidates")

    # 1. RETRIEVE — embedding-based top-K with dedup + filters.
    retriever = get_retriever()
    candidates = retriever.search(
        client_situation, k=k_candidates, category=category, kind=kind,
    )
    if not candidates:
        return RecommendationResponse(
            client_situation=client_situation,
            recommendations=[],
            overall_summary="No candidates matched the filters.",
        )

    # 2. RENDER — build CO-STAR prompt with candidates as XML blocks.
    candidates_block = render_candidates_block(candidates)
    prompt = make_recommender_prompt(client_situation, candidates_block)

    # 3. GENERATE — single LLM call, JSON mode for guaranteed parseability.
    raw = get_completion(
        prompt,
        temperature=0.0,
        response_format={"type": "json_object"},
    )

    # 4. PARSE + JOIN with retrieval metadata (provenance).
    parsed = _parse_llm_json(raw)
    cand_by_pid: dict[str, Result] = {c.parent_id: c for c in candidates}

    recs: list[Recommendation] = []
    for item in parsed.get("recommendations", [])[:n_recommendations]:
        pid = item.get("parent_id", "")
        cand = cand_by_pid.get(pid)
        # Guard rail: drop any recommendation whose parent_id wasn't actually
        # in the candidate pool (defensive — LLM could hallucinate IDs).
        if cand is None:
            print(f"  WARNING: LLM returned unknown parent_id {pid!r}; "
                  f"dropping.", file=sys.stderr)
            continue
        recs.append(Recommendation(
            parent_id=pid,
            title=item.get("title", cand.title),
            fit_score=int(item.get("fit_score", 0) or 0),
            rationale=item.get("rationale", ""),
            eligibility_flags=item.get("eligibility_flags", []) or [],
            evidence_quote=item.get("evidence_quote", ""),
            kind=cand.kind,
            url=cand.url,
            categories=cand.categories,
            retrieval_score=cand.score,
        ))

    return RecommendationResponse(
        client_situation=client_situation,
        recommendations=recs,
        overall_summary=parsed.get("overall_summary", ""),
        categories_touched=parsed.get("categories_touched", []) or [],
        retrieved_candidates=candidates,
        raw_llm_output=raw,
    )


# ---------------------------------------------------------------------------
# Demo / smoke test — 3 SAO client scenarios end-to-end.
# Invoke with: python recommender.py
# ---------------------------------------------------------------------------

DEMO_QUERIES = [
    ("Client 1",
     "Single mother of two young children, recently lost her job, needs "
     "financial help to pay rent and utilities."),
    ("Client 2",
     "Elderly with dementia, family needs respite care during the day so "
     "they can work."),
    ("Client 3",
     "Teenager showing suicide warning signs, family needs urgent support."),
]


def _demo() -> None:
    for label, situation in DEMO_QUERIES:
        print("=" * 88)
        print(f"{label}")
        print(f"Situation: {situation}")
        print()
        resp = recommend(situation, k_candidates=15, n_recommendations=5)
        print(f"Summary           : {resp.overall_summary}")
        print(f"Categories touched: {', '.join(resp.categories_touched)}")
        print(f"Candidates pulled : {len(resp.retrieved_candidates)}")
        print()
        for r in resp.recommendations:
            print(f"  [{r.fit_score}/5]  {r.title}   ({r.kind})")
            print(f"         id        : {r.parent_id}")
            print(f"         categories: {', '.join(r.categories)}")
            print(f"         why       : {r.rationale}")
            if r.eligibility_flags:
                print(f"         verify    : {' | '.join(r.eligibility_flags)}")
            if r.evidence_quote:
                print(f"         quote     : \"{r.evidence_quote}\"")
            print(f"         url       : {r.url}")
            print()


if __name__ == "__main__":
    try:
        _demo()
    except Exception as exc:  # noqa: BLE001
        print(f"FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise
