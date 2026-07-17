"""CrewAI orchestration — Topic 5.5 Multi-Agent Deep Analysis Mode.

Pipeline:
    1. Coordinator triages the case to 2–4 relevant SGW categories.
    2. The corresponding specialists run **in parallel** (CrewAI
       async_execution) and each drafts category-domain recommendations
       using their category-filtered retriever tool.
    3. Aggregator synthesises specialist drafts into a final ranked
       top-5 recommendation list with verbatim citations.

Inputs are the SANITISED text (CLOAK has already run as Stage 0 upstream
in ``recommender.py``), so the crew never sees raw PII.

Output is a structured dict consumed by ``recommender.recommend()`` to
populate a ``RecommendationResponse``.

This is the **opt-in Deep Mode** invoked when
``recommend(..., deep_mode=True)`` — fast single-shot mode remains the
default path and is fully preserved.
"""

from __future__ import annotations

import json
from json import JSONDecodeError

from crewai import Crew, Process, Task

from crew_specialists import (
    AGGREGATOR,
    CASE_DOCUMENTATION_OFFICER,
    CATEGORY_LABELS,
    COORDINATOR,
    SPECIALISTS,
)


def _triage_task(sanitised_text: str) -> Task:
    return Task(
        description=(
            "Read the client case below and triage to the SGW category "
            "specialists most relevant for this case.\n\n"
            f"CLIENT CASE:\n{sanitised_text}\n\n"
            "Pick between 2 and 4 categories from this exact list (do "
            f"NOT invent new ones): {', '.join(CATEGORY_LABELS)}\n\n"
            "Respond with ONLY a valid JSON object — no commentary, no "
            "code fences. Schema:\n"
            "{\"categories\": [\"category-slug\", ...]}"
        ),
        expected_output=(
            'A JSON object: {"categories": ["category-slug", ...]} '
            "with 2-4 SGW category slugs."
        ),
        agent=COORDINATOR,
    )


def _specialist_task(sanitised_text: str, category: str) -> Task:
    agent = SPECIALISTS[category]
    return Task(
        description=(
            "You are the specialist for the '" + category + "' domain. "
            "Read the client case below, then USE YOUR search_schemes "
            "tool to retrieve the most relevant schemes in your domain. "
            "Draft 1-3 recommendations from your domain only.\n\n"
            f"CLIENT CASE:\n{sanitised_text}\n\n"
            "For EACH recommendation, provide:\n"
            "  - parent_id (exact, from the tool output)\n"
            "  - title (exact, from the tool output)\n"
            "  - fit_score: integer 1-5 (5 = strongly fits this case)\n"
            "  - rationale: 1-2 sentences — every claim must appear in "
            "the candidate's text from your tool output\n"
            "  - evidence_quote: a CHARACTER-EXACT verbatim phrase "
            "(10-30 words) from the candidate's text\n"
            "  - eligibility_flags: short notes the SAO should verify\n\n"
            "Respond with ONLY a JSON object — no commentary, no code "
            "fences:\n"
            "{\"specialist\": \"" + category + "\", "
            "\"recommendations\": [ {...}, ... ]}"
        ),
        expected_output=(
            "A JSON object with the specialist name and 1-3 "
            "recommendations from this domain only."
        ),
        agent=agent,
        async_execution=True,  # ← Topic 5.5: parallel specialist execution
    )


def _documentation_task(sanitised_text: str, agg_task: Task) -> Task:
    """Agent #15 — plain-English case summary serving both purposes.

    Runs AFTER the Aggregator (context=[agg_task]) so it sees the
    final ranked top-5 with verbatim citations. Produces a single
    summary in warm plain English — usable both as a family
    communication and as a case-record entry.
    """
    return Task(
        description=(
            "You are the Case Documentation Officer. The Aggregator "
            "just produced a ranked top-5 recommendation list for "
            "this client case. Read that output (in context) and "
            "the case below.\n\n"
            f"CLIENT CASE:\n{sanitised_text}\n\n"
            "Write ONE plain-English case summary (3-5 paragraphs) "
            "that MSF policy allows to serve TWO purposes:\n"
            "  1. A communication that could be read to the family.\n"
            "  2. An entry the SAO can file in the case record.\n\n"
            "Guidance for tone and content:\n"
            "  - Empathetic, warm, direct.\n"
            "  - No jargon, no scheme codes (e.g. 'ComCare Interim' "
            "is fine but not 'COMCARE-INTERIM-ASSISTANCE').\n"
            "  - Explain WHY each recommended scheme fits, briefly.\n"
            "  - State WHAT the family can expect (application, "
            "timeframe, documents).\n"
            "  - State what the SAO will follow up on.\n"
            "  - Reference the top-5 by name — say 'we are "
            "recommending X because …' not just listing.\n\n"
            "Respond with ONLY a JSON object — no commentary, no "
            "code fences:\n"
            "{\"case_summary\": \"<3-5 paragraphs of plain English>\"}"
        ),
        expected_output=(
            "A JSON object with a single 'case_summary' field "
            "containing 3-5 paragraphs of plain-English case "
            "documentation."
        ),
        agent=CASE_DOCUMENTATION_OFFICER,
        context=[agg_task],
    )


def _aggregator_task(sanitised_text: str, specialist_tasks: list[Task]) -> Task:
    return Task(
        description=(
            "You are aggregating specialist drafts into a final ranked "
            "top-5 recommendation list for the welfare officer.\n\n"
            f"CLIENT CASE:\n{sanitised_text}\n\n"
            "The specialist drafts you received are above (each is a "
            "JSON object with a 'specialist' and 'recommendations' "
            "list). Synthesise as follows:\n\n"
            "1. Drop duplicates (same parent_id from multiple "
            "specialists — keep the highest fit_score version).\n"
            "2. Rank by fit_score, breaking ties by evidence specificity.\n"
            "3. Return EXACTLY top 5 — fewer if there are fewer than 5 "
            "unique recommendations.\n"
            "4. Preserve each recommendation's verbatim evidence_quote.\n"
            "5. Add an 'overall_summary' field — 1 sentence on the "
            "case pattern.\n"
            "6. Add a 'categories_touched' field — list of "
            "category-slugs the specialists covered.\n"
            "7. Add a 'reasoning_steps' field — 3-5 short bullets on "
            "how you synthesised.\n\n"
            "Respond with ONLY a JSON object — no commentary, no "
            "code fences:\n"
            "{\n"
            "  \"overall_summary\": \"...\",\n"
            "  \"categories_touched\": [...],\n"
            "  \"reasoning_steps\": [...],\n"
            "  \"recommendations\": [\n"
            "    {\n"
            "      \"parent_id\": \"...\",\n"
            "      \"title\": \"...\",\n"
            "      \"fit_score\": 1-5,\n"
            "      \"rationale\": \"...\",\n"
            "      \"evidence_quote\": \"...\",\n"
            "      \"eligibility_flags\": [...]\n"
            "    }\n"
            "  ]\n"
            "}"
        ),
        expected_output=(
            "A single JSON object with overall_summary, "
            "categories_touched, reasoning_steps, and top-5 "
            "recommendations with verbatim evidence quotes."
        ),
        agent=AGGREGATOR,
        context=specialist_tasks,
    )


def _parse_json_loose(text: str) -> dict:
    """Tolerate fenced JSON or pre/post-amble."""
    try:
        return json.loads(text)
    except JSONDecodeError:
        pass
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else cleaned[3:]
        if cleaned.rstrip().endswith("```"):
            cleaned = cleaned.rstrip()[:-3]
    # Try to find the first { ... } block
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(cleaned[start:end + 1])
        except JSONDecodeError:
            pass
    raise RuntimeError(
        f"Could not parse JSON from agent output. First 300 chars:\n{text[:300]}"
    )


def run_deep_analysis(sanitised_text: str) -> dict:
    """Run the full multi-agent crew on a sanitised client case.

    Args:
        sanitised_text: The CLOAK-sanitised client case (NO raw PII).

    Returns:
        A dict shaped like::

            {
                "overall_summary": str,
                "categories_touched": [str, ...],
                "reasoning_steps": [str, ...],
                "triaged_categories": [str, ...],
                "specialist_drafts": [
                    {"specialist": str, "recommendations": [...]},
                    ...
                ],
                "recommendations": [
                    {parent_id, title, fit_score, rationale,
                     evidence_quote, eligibility_flags}, ...
                ],
            }

    Raises:
        RuntimeError if any stage produces unparseable output.
    """
    # ----- Stage 1: Triage -------------------------------------------------
    triage_crew = Crew(
        agents=[COORDINATOR],
        tasks=[_triage_task(sanitised_text)],
        process=Process.sequential,
        verbose=False,
    )
    triage_output = triage_crew.kickoff()
    triage_parsed = _parse_json_loose(str(triage_output))
    triaged = [
        c for c in (triage_parsed.get("categories") or [])
        if c in SPECIALISTS
    ]
    # Safety net: if coordinator returned 0 valid categories, use a
    # broad default trio so the demo never produces an empty result.
    if not triaged:
        triaged = ["financial-support", "family-parenting", "counselling-crisis"]
    # Cap at 4 (per design)
    triaged = triaged[:4]

    # ----- Stage 2: Specialists in parallel + Aggregator + Docs -----------
    specialist_tasks = [_specialist_task(sanitised_text, c) for c in triaged]
    agg_task = _aggregator_task(sanitised_text, specialist_tasks)
    doc_task = _documentation_task(sanitised_text, agg_task)

    deep_crew = Crew(
        agents=[SPECIALISTS[c] for c in triaged]
               + [AGGREGATOR, CASE_DOCUMENTATION_OFFICER],
        tasks=specialist_tasks + [agg_task, doc_task],
        process=Process.sequential,  # async_execution on specialist tasks
                                     # makes them run in parallel anyway;
                                     # agg then doc run strictly after.
        verbose=False,
    )
    deep_output = deep_crew.kickoff()
    # deep_output is the LAST task's output — the case summary.
    # We need BOTH the aggregator's structured output AND the doc summary.
    doc_parsed_raw = str(deep_output)
    try:
        doc_parsed = _parse_json_loose(doc_parsed_raw)
    except RuntimeError:
        doc_parsed = {"case_summary": doc_parsed_raw[:2000]}
    case_summary = doc_parsed.get("case_summary", "").strip()

    # Extract Aggregator output from its task
    agg_output_raw = str(getattr(agg_task, "output", "") or "")
    try:
        aggregator_parsed = _parse_json_loose(agg_output_raw)
    except RuntimeError:
        # Fall back to trying the whole crew output (unlikely path)
        aggregator_parsed = _parse_json_loose(doc_parsed_raw)

    # Extract specialist drafts (each task's raw output)
    specialist_drafts = []
    for t in specialist_tasks:
        raw = str(getattr(t, "output", "") or "")
        try:
            specialist_drafts.append(_parse_json_loose(raw))
        except RuntimeError:
            specialist_drafts.append({
                "specialist": t.agent.role if t.agent else "?",
                "recommendations": [],
                "parse_error": True,
                "raw_output": raw[:300],
            })

    return {
        "overall_summary": aggregator_parsed.get("overall_summary", ""),
        "categories_touched": (
            aggregator_parsed.get("categories_touched") or triaged
        ),
        "reasoning_steps": aggregator_parsed.get("reasoning_steps") or [],
        "triaged_categories": triaged,
        "specialist_drafts": specialist_drafts,
        "recommendations": aggregator_parsed.get("recommendations") or [],
        "case_summary": case_summary,
    }
