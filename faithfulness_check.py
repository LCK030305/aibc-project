"""Faithfulness self-check — Topic 4.4 Post-Retrieval verification pass.

After the recommender produces 3–5 candidates with rationales and
evidence quotes, this module runs a SECONDARY LLM call that audits
each recommendation: "Is every claim in the rationale grounded in
the candidate's section_text and the evidence_quote?"

This addresses our RAGAS Faithfulness baseline (0.467) — Tier 1
of the v1.x → v1.1 improvement plan (Topic 4.4 Post-Retrieval
Re-Ranking / verification).

Design
------
- **One combined LLM call** for all recommendations (cheaper than N
  calls). Returns a JSON array with one verdict per recommendation.
- **JSON-mode + structured schema** — guaranteed parseable.
- **Verdict per rec**: ``faithfulness_status`` ∈ {verified,
  partial, unsupported} + ``faithfulness_note`` (1-line reason).
- **Fail-OPEN**: if the verification call errors, recommendations
  are returned unchanged with status="unverified" — better to show
  un-audited recommendations than to block legitimate help.

Public surface
--------------
    from faithfulness_check import audit_recommendations
    audited = audit_recommendations(
        client_situation, recommendations, candidates_by_pid,
    )

The function mutates each Recommendation in-place by setting
``faithfulness_status`` and ``faithfulness_note`` on each.
"""

from __future__ import annotations

import json
from json import JSONDecodeError

from llm import get_completion


_AUDIT_PROMPT_TEMPLATE = """# CONTEXT
You are a faithfulness auditor for an AI welfare-recommendation tool.
A separate LLM has just generated recommendations for a Singapore
Social Assistance Officer. Each recommendation includes:
  - a rationale (why this scheme fits the client)
  - an evidence_quote (claimed verbatim phrase from the source text)
You must verify, for each recommendation, that:
  (1) the rationale's claims are supported by the source text (no
      invented eligibility details, no hallucinated scheme features),
  (2) the evidence_quote actually appears verbatim in the source text.

This is a HIGH-STAKES domain (government welfare). False positives
(approving an unfaithful recommendation) are worse than false
negatives (flagging a recommendation that was actually fine — the
human SAO can still review it).

# OBJECTIVE
For each recommendation, return a verdict:
  - "verified"    — rationale fully supported by source + quote is exact
  - "partial"     — rationale mostly supported, but at least one claim
                     is loosely paraphrased or the quote is not exact
  - "unsupported" — rationale invents facts not in the source text

Also return a short (1 line, ≤20 words) ``note`` explaining the verdict.
For "verified" cases the note can be terse (e.g., "Rationale matches
source.").

# STYLE
Be strict. If you can find a sentence in the rationale that the source
text does not literally state, mark it "partial" at best, not "verified".

# RESPONSE FORMAT
Return a single JSON object exactly matching this schema:

{{
  "audits": [
    {{
      "parent_id": "<copy from recommendation>",
      "status": "verified" | "partial" | "unsupported",
      "note": "<one short line, ≤20 words>"
    }}
  ]
}}

# CLIENT SITUATION
<client_situation>
{client_situation}
</client_situation>

# RECOMMENDATIONS TO AUDIT
{recommendations_block}
"""


def _build_audit_block(recommendations, candidates_by_pid) -> str:
    blocks = []
    for r in recommendations:
        cand = candidates_by_pid.get(r.parent_id)
        source_text = cand.section_text if cand else "(source not found)"
        # Cap source text at 1200 chars; same budget as the recommender prompt.
        if len(source_text) > 1200:
            source_text = source_text[:1200].rstrip() + "..."
        blocks.append(
            f'<rec id="{r.parent_id}" title="{r.title}">\n'
            f'  rationale       : {r.rationale}\n'
            f'  evidence_quote  : "{r.evidence_quote}"\n'
            f'  source_text     : {source_text}\n'
            f'</rec>'
        )
    return "\n".join(blocks)


def audit_recommendations(
    client_situation: str,
    recommendations: list,
    candidates_by_pid: dict,
) -> list:
    """Run a single LLM audit pass over all recommendations.

    Mutates each ``Recommendation`` in-place to set
    ``faithfulness_status`` and ``faithfulness_note`` fields.
    Returns the same list for chaining convenience.

    Fail-OPEN: any error leaves status="unverified" and note="audit
    failed: <error>", but does NOT raise — the SAO still gets the
    recommendations.
    """
    if not recommendations:
        return recommendations

    audit_block = _build_audit_block(recommendations, candidates_by_pid)
    prompt = _AUDIT_PROMPT_TEMPLATE.format(
        client_situation=client_situation,
        recommendations_block=audit_block,
    )

    try:
        raw = get_completion(
            prompt,
            temperature=0.0,
            response_format={"type": "json_object"},
        )
    except Exception as exc:  # noqa: BLE001
        # Fail-OPEN — mark all as unverified but don't block.
        for r in recommendations:
            r.faithfulness_status = "unverified"
            r.faithfulness_note = (
                f"Audit pass failed ({type(exc).__name__}); SAO to review."
            )
        return recommendations

    try:
        parsed = json.loads(raw)
        audits = parsed.get("audits", []) or []
    except JSONDecodeError:
        for r in recommendations:
            r.faithfulness_status = "unverified"
            r.faithfulness_note = "Audit response was not valid JSON."
        return recommendations

    by_pid = {a.get("parent_id"): a for a in audits if a.get("parent_id")}
    for r in recommendations:
        a = by_pid.get(r.parent_id)
        if a is None:
            r.faithfulness_status = "unverified"
            r.faithfulness_note = "No audit returned for this recommendation."
        else:
            status = a.get("status", "unverified")
            if status not in {"verified", "partial", "unsupported"}:
                status = "unverified"
            r.faithfulness_status = status
            r.faithfulness_note = (a.get("note") or "").strip()[:200]

    return recommendations
