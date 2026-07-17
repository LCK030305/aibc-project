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

from openai import (
    APIConnectionError,
    AuthenticationError,
    BadRequestError,
    RateLimitError,
)

from bm25_retriever import get_bm25, rrf_merge
from decomposer import step_3_decompose
from faithfulness_check import audit_recommendations
from hyde import generate_hypothetical_scheme
from llm import get_completion
from pii_filter import sanitize
from prompts import make_recommender_prompt, render_candidates_block
from retriever import Result, get_retriever
from router import step_2_classify_query
from safety import step_1_safety_check

# Topic 5.5 — CrewAI multi-agent Deep Mode (opt-in).
# Imported lazily inside recommend() to avoid loading CrewAI when running
# in fast single-shot mode (CrewAI pulls in chromadb, opentelemetry, etc).

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
    # Topic 4.4 Post-Retrieval verification — populated by the secondary
    # faithfulness self-check pass in ``faithfulness_check.py``. Values:
    #   "verified"    — every claim in the rationale is grounded in source
    #   "partial"     — rationale mostly grounded, minor paraphrase
    #   "unsupported" — rationale invents facts not in source
    #   "unverified"  — audit pass failed (fail-OPEN) or skipped
    faithfulness_status: str = "unverified"
    faithfulness_note: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class RecommendationResponse:
    """Full response from the recommender pipeline (UI + eval consume this).

    A ``blocked`` response carries an empty ``recommendations`` list and a
    populated ``block_reason``. The UI is expected to check ``blocked``
    first and render a refusal banner before any other content.
    """

    client_situation: str
    recommendations: list[Recommendation]
    overall_summary: str = ""
    categories_touched: list[str] = field(default_factory=list)
    retrieved_candidates: list[Result] = field(default_factory=list)
    raw_llm_output: str = ""                      # for debugging / eval replay
    # Topic 2.6 Decision Chain — first-step refusal carries these fields.
    blocked: bool = False
    block_reason: str = ""
    # Topic 2.6 Decision Chain — second-step router result; populated even
    # when blocked=False so downstream code / UI can inspect the
    # classification decision.
    classification: dict | None = None
    # Topic 2.4 Chain-of-Thought / Topic 2.5 Inner Monologue — the LLM's
    # step-by-step reasoning chain extracted from the JSON response.
    # Empty list when the response was blocked / short-circuited.
    reasoning_steps: list[str] = field(default_factory=list)
    # Topic 2.4 Least-to-Most decomposition — the sub-needs the
    # decomposer split this case into. For simple cases this is a
    # single-element list; for complex cases 2-5 entries.
    decomposition: dict | None = None
    # Topic 2.6 Decision Chain — the safety guard's verdict dict. Populated
    # even for safe inputs (so the Behind-the-Scenes panel can show it).
    safety_result: dict | None = None
    # The actual CO-STAR prompt sent to the re-ranker LLM. Useful for the
    # Behind-the-Scenes panel and for offline eval replay.
    prompt_sent: str = ""
    # Topic 5.5.2 CLOAK PII guard — ``sanitized_situation`` is the text
    # that actually went to every LLM and the retriever (PII redacted).
    # ``client_situation`` above is preserved unchanged as the raw input
    # for UI display. ``pii_result`` carries the full sanitize() return:
    # which entities were redacted at which offsets, useful for audit and
    # for the "raw vs sanitised" side-by-side UI pane.
    sanitized_situation: str = ""
    pii_result: dict | None = None
    # Topic 5.5 CrewAI Deep Mode — populated only when recommend() was
    # called with deep_mode=True. ``triaged_categories`` is what the
    # Coordinator agent decided; ``specialist_drafts`` is the per-agent
    # output that fed the Aggregator (visible in the UI "Specialist
    # perspectives" expander). Empty list / False in fast mode.
    deep_mode_used: bool = False
    triaged_categories: list[str] = field(default_factory=list)
    specialist_drafts: list[dict] = field(default_factory=list)
    # Topic 5.5 Agent #15 (Case Documentation Officer) — plain-English
    # summary usable both as family communication AND SAO case-record
    # entry. Populated only in Deep Mode.
    case_summary: str = ""

    def to_dict(self) -> dict:
        return {
            "client_situation": self.client_situation,
            "sanitized_situation": self.sanitized_situation,
            "blocked": self.blocked,
            "block_reason": self.block_reason,
            "classification": self.classification,
            "decomposition": self.decomposition,
            "overall_summary": self.overall_summary,
            "categories_touched": self.categories_touched,
            "reasoning_steps": self.reasoning_steps,
            "recommendations": [r.to_dict() for r in self.recommendations],
            "n_candidates_considered": len(self.retrieved_candidates),
            "pii_entities_redacted": (
                len((self.pii_result or {}).get("items", []) or [])
            ),
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
    override_sub_needs: list[str] | None = None,
    bypass_pii: bool = False,
    pii_score_threshold: float = 0.3,
    skip_faithfulness_audit: bool = False,
    use_hyde: bool = True,
    use_bm25: bool = True,
    deep_mode: bool = False,
) -> RecommendationResponse:
    """Run the full UC#1 pipeline: retrieve → re-rank → reason → structure.

    Args:
        client_situation   : Free-text description of the client's situation.
                             One short paragraph works best — too long and
                             the embedding signal dilutes.
        k_candidates       : How many candidates to pull from the retriever.
                             More = more options for the LLM to weigh but
                             longer prompt and higher cost. Default 15 keeps
                             prompt size ~15 KB which is well within limits.
        n_recommendations  : Max recommendations to keep from the LLM output.
        category           : Optional SGW category slug to filter retrieval
                             (e.g., "financial-support" only).
        kind               : Optional "scheme" or "service" filter.
        override_sub_needs : If provided, SKIP the decomposer LLM call and
                             use these sub-needs verbatim. This is the
                             HITL hook (Topic 2.6 advantage): the SAO
                             reviews and edits the AI's decomposition,
                             then submits the edited version for retrieval.

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

    # STAGE 0: CLOAK PII GUARD (Topic 5.5.2 — Free-Text Anonymisation)
    # -----------------------------------------------------------------
    # Before ANY downstream LLM call or embedding, run the input through
    # CLOAK's `/transform` endpoint. Identifying entities (PERSON, NRIC,
    # addresses, phones, emails, bank accounts, dates) are redacted to
    # labelled tokens; matcher-relevant signal (life events, family
    # structure, financial state) is preserved.
    #
    # FAIL-CLOSED: if CLOAK errors (network down, rate limit, signing
    # mismatch), we refuse the request rather than risk leaking raw PII.
    # ``bypass_pii=True`` skips CLOAK — for offline dev only; production
    # callers (Streamlit, batch, RPA) should never set this.
    if bypass_pii:
        sanitized_text = client_situation
        pii_result: dict = {
            "success": True, "bypassed": True,
            "sanitised": client_situation,
            "original": client_situation, "items": [],
        }
    else:
        pii_result = sanitize(
            client_situation, score_threshold=pii_score_threshold,
        )
        if not pii_result.get("success"):
            return RecommendationResponse(
                client_situation=client_situation,
                sanitized_situation="",
                recommendations=[],
                blocked=True,
                block_reason=(
                    "PII guard (CLOAK) unavailable — refusing to forward "
                    "raw text to the LLM. "
                    f"Reason: {pii_result.get('error', 'unknown')}"
                ),
                pii_result=pii_result,
                overall_summary="Blocked at PII guard (fail-CLOSED).",
            )
        sanitized_text = pii_result["sanitised"]

    # 1. SAFETY CHECK (Topic 2.6 Decision Chain — fail-closed)
    #    Block prompt-injection / jailbreak attempts before any downstream
    #    processing or retrieval happens. Operates on the SANITISED text
    #    (which is what would actually go to OpenAI).
    safety = step_1_safety_check(sanitized_text)
    if not safety["is_safe"]:
        return RecommendationResponse(
            client_situation=client_situation,
            sanitized_situation=sanitized_text,
            recommendations=[],
            blocked=True,
            block_reason=safety["reason"],
            safety_result=safety,
            pii_result=pii_result,
            overall_summary="Input refused by safety check.",
        )

    # ---- Deep Mode branch (Topic 5.5 CrewAI multi-agent) ----------------
    # Opt-in alternative to the fast single-shot pipeline below. CrewAI
    # imports happen lazily here so fast mode doesn't pay the import cost.
    if deep_mode:
        return _recommend_deep_mode(
            client_situation=client_situation,
            sanitized_text=sanitized_text,
            pii_result=pii_result,
            safety=safety,
            n_recommendations=n_recommendations,
            skip_faithfulness_audit=skip_faithfulness_audit,
        )

    # 2. ROUTING (Topic 2.6 Decision Chain — multi-class, fail-open)
    #    Classify the input intent. general_question and out_of_scope
    #    short-circuit the pipeline with a helpful redirect; client_case
    #    and scheme_lookup both proceed to retrieval.
    classification = step_2_classify_query(sanitized_text)
    category_tag = classification["category"]

    if category_tag == "general_question":
        return RecommendationResponse(
            client_situation=client_situation,
            sanitized_situation=sanitized_text,
            recommendations=[],
            classification=classification,
            safety_result=safety,
            pii_result=pii_result,
            overall_summary=(
                "This looks like a general question rather than a client "
                "case. Try rephrasing as a client's situation (e.g. \"single "
                "mother with two children, lost her job, needs rent help\") "
                "to get scheme recommendations."
            ),
        )

    if category_tag == "out_of_scope":
        return RecommendationResponse(
            client_situation=client_situation,
            sanitized_situation=sanitized_text,
            recommendations=[],
            classification=classification,
            safety_result=safety,
            pii_result=pii_result,
            overall_summary=(
                "This question doesn't appear to be about Singapore social "
                "services. This tool helps SAOs match clients to MSF "
                "schemes and community services — try describing a "
                "client's situation."
            ),
        )

    # client_case and scheme_lookup both continue through retrieval.

    # 3. LEAST-TO-MOST decomposition (Topic 2.4)
    #    For complex multi-need cases, split into discrete sub-needs and
    #    retrieve against each. Single-need cases yield a 1-element list,
    #    making the rest of the pipeline behave identically to before.
    #    HITL hook (Topic 2.6): if `override_sub_needs` was supplied, the
    #    SAO has edited the decomposer's output; we use theirs verbatim
    #    and skip the LLM call.
    if override_sub_needs is not None:
        clean_overrides = [s.strip() for s in override_sub_needs if s.strip()]
        if not clean_overrides:
            clean_overrides = [sanitized_text]
        decomposition = {
            "is_complex": len(clean_overrides) > 1,
            "sub_needs": clean_overrides,
            "edited_by_sao": True,
        }
    else:
        decomposition = step_3_decompose(sanitized_text)
    sub_needs = decomposition["sub_needs"]

    # 4. RETRIEVE — hybrid dense + HyDE + BM25, fused with RRF.
    #
    # Topic 4.2 (Pre-Retrieval) — HyDE generates a hypothetical SGW-style
    # scheme description for each sub-need, then we embed that and search.
    # Closes the vocabulary gap between SAO phrasing and SGW phrasing.
    #
    # Topic 4.3 (Retrieval) — BM25 sparse keyword retrieval catches exact
    # acronym matches (CHAS, MUIS-FAS, ATF, EASE) that the embedder may
    # miss because they're rare tokens. Run alongside dense retrieval.
    #
    # Topic 4.3 (Retrieval) — Reciprocal Rank Fusion combines the three
    # ranked lists without needing to normalise scores across retrievers.
    #
    # Per-sub-need budget: each retriever pulls k_candidates. We then RRF-
    # merge and filter to parent_ids we have full Result objects for
    # (i.e., found by dense or HyDE). BM25 acts mainly as a re-ranker —
    # its votes shift dense+HyDE hits in the final order.
    retriever = get_retriever()
    bm25 = get_bm25() if use_bm25 else None

    best_by_parent: dict[str, Result] = {}
    for sub_need in sub_needs:
        # (a) Dense retrieval over the original sub-need.
        dense_results = retriever.search(
            sub_need, k=k_candidates, category=category, kind=kind,
        )
        dense_pids = [r.parent_id for r in dense_results]

        # (b) HyDE — embed a hypothetical SGW-style description.
        hyde_pids: list[str] = []
        if use_hyde:
            hyde_text = generate_hypothetical_scheme(sub_need)
            if hyde_text and hyde_text != sub_need:
                hyde_results = retriever.search(
                    hyde_text, k=k_candidates,
                    category=category, kind=kind,
                )
                hyde_pids = [r.parent_id for r in hyde_results]
                # Fold HyDE hits into the same Result map (keep best score).
                for r in hyde_results:
                    existing = best_by_parent.get(r.parent_id)
                    if existing is None or r.score > existing.score:
                        best_by_parent[r.parent_id] = r

        # (c) BM25 sparse retrieval.
        bm25_pids: list[str] = []
        if bm25 is not None:
            bm25_hits = bm25.search(sub_need, k=k_candidates)
            bm25_pids = [pid for pid, _ in bm25_hits]

        # Fold dense hits in (and let them win ties — they already filter
        # by category/kind, which BM25 / HyDE don't).
        for r in dense_results:
            existing = best_by_parent.get(r.parent_id)
            if existing is None or r.score > existing.score:
                best_by_parent[r.parent_id] = r

        # (d) RRF — combine the three ranked lists for this sub-need.
        ranked_lists = [pids for pids in [dense_pids, hyde_pids, bm25_pids] if pids]
        merged_pids = rrf_merge(ranked_lists, top_k=k_candidates * 2)

        # Re-score the parents using their RRF order so later sub-needs'
        # cross-merge respects this sub-need's ranking. (We piggy-back on
        # the existing score field — higher = better.)
        n = len(merged_pids)
        for rank, pid in enumerate(merged_pids):
            if pid not in best_by_parent:
                continue
            rrf_boost = (n - rank) / max(n, 1)  # 1.0 → 0.0
            current = best_by_parent[pid].score
            # Take the max so dense's category-filtered priority isn't lost.
            best_by_parent[pid].score = max(current, rrf_boost)

    candidates = sorted(
        best_by_parent.values(), key=lambda r: -r.score
    )[:k_candidates]
    # Re-stamp the rank for clarity (it's a merged pool now).
    for new_rank, cand in enumerate(candidates, start=1):
        cand.rank = new_rank
    if not candidates:
        return RecommendationResponse(
            client_situation=client_situation,
            sanitized_situation=sanitized_text,
            recommendations=[],
            classification=classification,
            decomposition=decomposition,
            safety_result=safety,
            pii_result=pii_result,
            overall_summary="No candidates matched the filters.",
        )

    # 5. RENDER — build CO-STAR prompt with candidates as XML blocks.
    #    Prompt uses the SANITISED text so no raw PII reaches OpenAI.
    candidates_block = render_candidates_block(candidates)
    prompt = make_recommender_prompt(sanitized_text, candidates_block)

    # 3. GENERATE — single LLM call, JSON mode for guaranteed parseability.
    #    Topic 2.7 Exception Handling — catch the OpenAI-specific errors
    #    most likely to fire in a live demo (network flicker, rate burst,
    #    rotated key, model removed from project) and re-raise with
    #    user-friendly messages the Streamlit UI surfaces verbatim.
    try:
        raw = get_completion(
            prompt,
            temperature=0.0,
            # 5 full recommendation cards (title + summary + eligibility flags +
            # evidence quotes + reasoning) easily exceed the 1024-token default,
            # especially on complex multi-need cases — truncation produces
            # invalid JSON. 4096 is well within gpt-4.1-mini's 32k output cap.
            max_tokens=4096,
            response_format={"type": "json_object"},
        )
    except RateLimitError as exc:
        raise RuntimeError(
            "OpenAI rate limit hit — wait ~30 seconds and retry."
        ) from exc
    except APIConnectionError as exc:
        raise RuntimeError(
            "Couldn't reach OpenAI. Check your internet connection and retry."
        ) from exc
    except AuthenticationError as exc:
        raise RuntimeError(
            "OpenAI authentication failed — your API key may have rotated. "
            "Update .env (local) or st.secrets (Streamlit Cloud)."
        ) from exc
    except BadRequestError as exc:
        raise RuntimeError(
            f"OpenAI rejected the request: {getattr(exc, 'message', str(exc))}. "
            "Often this means the project doesn't allow this model — enable "
            "it under platform.openai.com → project → Limits → Allowed models."
        ) from exc

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
            eligibility_flags=_normalize_flags(item.get("eligibility_flags")),
            evidence_quote=item.get("evidence_quote", ""),
            kind=cand.kind,
            url=cand.url,
            categories=cand.categories,
            retrieval_score=cand.score,
        ))

    # 7. FAITHFULNESS AUDIT (Topic 4.4 Post-Retrieval verification)
    #    Secondary LLM pass: for each recommendation, verify the rationale
    #    is grounded in the candidate's source text and the evidence_quote
    #    is an exact substring. Mutates each rec in-place. Fail-OPEN.
    if recs and not skip_faithfulness_audit:
        audit_recommendations(sanitized_text, recs, cand_by_pid)

    return RecommendationResponse(
        client_situation=client_situation,
        sanitized_situation=sanitized_text,
        recommendations=recs,
        overall_summary=parsed.get("overall_summary", ""),
        categories_touched=parsed.get("categories_touched", []) or [],
        retrieved_candidates=candidates,
        raw_llm_output=raw,
        classification=classification,
        decomposition=decomposition,
        reasoning_steps=parsed.get("reasoning_steps", []) or [],
        safety_result=safety,
        pii_result=pii_result,
        prompt_sent=prompt,
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


# ---------------------------------------------------------------------------
# Deep Mode (Topic 5.5 CrewAI) — opt-in multi-agent alternative
# ---------------------------------------------------------------------------

_chunk_lookup_cache: dict[str, Result] | None = None


def _normalize_flags(value) -> list[str]:
    """Coerce LLM ``eligibility_flags`` output to a clean ``list[str]``.

    LLMs sometimes return a bare string (e.g., ``"Verify"``) instead of
    the requested ``["Verify ..."]`` list. Without normalisation the
    Streamlit UI iterates the string character-by-character and
    displays one bullet per letter (V / e / r / i / f / y). This
    guarantees whatever came out — string, list, dict, None — becomes
    a clean list of non-empty strings.
    """
    if value is None:
        return []
    if isinstance(value, str):
        s = value.strip()
        return [s] if s else []
    if isinstance(value, (list, tuple)):
        out: list[str] = []
        for item in value:
            if item is None:
                continue
            s = str(item).strip()
            if s:
                out.append(s)
        return out
    # Anything else (dict, number, etc.) — best-effort stringify.
    s = str(value).strip()
    return [s] if s else []


def _build_chunk_lookup() -> dict[str, Result]:
    """Build a parent_id → minimal Result lookup once per process.

    Used to feed the faithfulness audit with source text for each
    crew-produced recommendation (which carries parent_id but not
    section_text). Cheap one-time JSONL scan, cached.
    """
    global _chunk_lookup_cache
    if _chunk_lookup_cache is not None:
        return _chunk_lookup_cache
    from collections import defaultdict
    from pathlib import Path
    chunks_path = (
        Path(__file__).parent / "data" / "chunks" / "chunks.jsonl"
    )
    by_parent: dict[str, list[dict]] = defaultdict(list)
    with chunks_path.open("r", encoding="utf-8") as f:
        for line in f:
            c = json.loads(line)
            by_parent[c["parent_id"]].append(c)
    lookup: dict[str, Result] = {}
    for pid, chunks in by_parent.items():
        best = next(
            (c for c in chunks if c.get("section") == "tagline"), chunks[0]
        )
        lookup[pid] = Result(
            rank=0,
            score=0.0,
            parent_id=pid,
            kind=best.get("kind", ""),
            title=best.get("title", ""),
            tagline=best.get("tagline", ""),
            url=best.get("url", ""),
            best_section=best.get("section", "tagline"),
            section_text=best.get("text", ""),
            categories=[],
        )
    _chunk_lookup_cache = lookup
    return lookup


def _recommend_deep_mode(
    client_situation: str,
    sanitized_text: str,
    pii_result: dict,
    safety: dict,
    n_recommendations: int,
    skip_faithfulness_audit: bool,
) -> RecommendationResponse:
    """Run the CrewAI Deep Mode pipeline and return a RecommendationResponse.

    Pipeline (after CLOAK Stage 0 + Safety, which already ran upstream):
      - Coordinator agent triages → 2-4 SGW category specialists
      - Specialists run in parallel via CrewAI async_execution
      - Aggregator synthesises into ranked top-5 with verbatim citations
      - Same faithfulness audit (Topic 4.4) runs on the final output
    """
    # Lazy import — only loaded when deep_mode=True (avoids ~3s CrewAI
    # import cost on every fast-mode call).
    from crew_runner import run_deep_analysis

    try:
        crew_out = run_deep_analysis(sanitized_text)
    except Exception as exc:  # noqa: BLE001 - surface as a blocked response
        return RecommendationResponse(
            client_situation=client_situation,
            sanitized_situation=sanitized_text,
            recommendations=[],
            blocked=True,
            block_reason=(
                f"Deep Analysis Mode (CrewAI) failed: "
                f"{type(exc).__name__}: {str(exc)[:200]}"
            ),
            safety_result=safety,
            pii_result=pii_result,
            deep_mode_used=True,
            overall_summary="Deep Mode crew execution failed.",
        )

    # Build Recommendation objects from the Aggregator's output.
    chunk_lookup = _build_chunk_lookup()
    recs: list[Recommendation] = []
    for item in crew_out.get("recommendations", [])[:n_recommendations]:
        pid = item.get("parent_id", "")
        source = chunk_lookup.get(pid)
        recs.append(Recommendation(
            parent_id=pid,
            title=item.get("title") or (source.title if source else pid),
            fit_score=int(item.get("fit_score", 0) or 0),
            rationale=item.get("rationale", ""),
            eligibility_flags=_normalize_flags(item.get("eligibility_flags")),
            evidence_quote=item.get("evidence_quote", ""),
            kind=source.kind if source else "",
            url=source.url if source else "",
            categories=source.categories if source else [],
            retrieval_score=0.0,  # not applicable in crew mode
        ))

    # Faithfulness audit (Topic 4.4) on crew output — same pass as fast
    # mode. Reuses _build_chunk_lookup() to provide source text per pid.
    if recs and not skip_faithfulness_audit:
        cand_by_pid = {r.parent_id: chunk_lookup.get(r.parent_id) for r in recs}
        cand_by_pid = {k: v for k, v in cand_by_pid.items() if v is not None}
        if cand_by_pid:
            audit_recommendations(sanitized_text, recs, cand_by_pid)

    # Build the retrieved_candidates list from triaged category specialists'
    # consolidated outputs (so the Behind-the-Scenes panel still has data)
    retrieved_results: list[Result] = []
    for draft in crew_out.get("specialist_drafts", []):
        for r_item in draft.get("recommendations", []):
            pid = r_item.get("parent_id", "")
            src = chunk_lookup.get(pid)
            if src is not None:
                retrieved_results.append(src)

    return RecommendationResponse(
        client_situation=client_situation,
        sanitized_situation=sanitized_text,
        recommendations=recs,
        overall_summary=crew_out.get("overall_summary", ""),
        categories_touched=crew_out.get("categories_touched", []) or [],
        retrieved_candidates=retrieved_results,
        raw_llm_output=json.dumps(crew_out, indent=2)[:5000],
        reasoning_steps=crew_out.get("reasoning_steps", []) or [],
        safety_result=safety,
        pii_result=pii_result,
        deep_mode_used=True,
        triaged_categories=crew_out.get("triaged_categories", []) or [],
        specialist_drafts=crew_out.get("specialist_drafts", []) or [],
        case_summary=crew_out.get("case_summary", "") or "",
        prompt_sent="(Deep Mode — multi-agent CrewAI; no single prompt)",
    )


if __name__ == "__main__":
    try:
        _demo()
    except Exception as exc:  # noqa: BLE001
        print(f"FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise
