"""CO-STAR prompt templates for the SAO Co-Pilot capstone.

Bootcamp principles baked in
----------------------------
- Week 1 § CO-STAR framework  : every template has explicit Context,
  Objective, Style, Tone, Audience, Response-format sections
  (GovTech Prompt Engineering Playbook, pages 26–40).
- Week 1 § Delimiter conventions : ``<tags>`` for multi-section inputs
  (client situation, candidates), triple-backticks reserved for single
  text blocks. We use tags here because we have multiple sections.
- Week 1 § f-strings + triple-quote : templates are functions returning
  formatted strings rather than ``str.format()`` constants — avoids
  brace-escaping pain when JSON examples appear in the prompt.
- Week 2 § Multi-action prompts : the recommender template asks the LLM
  to *select, rank, justify, and cite* in one structured response.
- Week 2 § Prompt chaining : this module exports prompt builders only;
  composition into a pipeline lives in recommender.py.
- Week 5 § Post-retrieval re-ranking : recommender uses these prompts to
  refine the embedding retriever's top-K with reasoning the embedding
  layer cannot do (e.g., "is this client likely above the income cap?").

Each prompt builder is a pure function: deterministic given inputs, no
side effects, easy to unit-test by inspecting the rendered string.
"""

from __future__ import annotations

from typing import Iterable, TYPE_CHECKING

if TYPE_CHECKING:
    from retriever import Result  # avoid circular import at runtime


# ---------------------------------------------------------------------------
# UC#1 RECOMMENDER PROMPT  (Pain Point #3 — programme matching)
# ---------------------------------------------------------------------------
#
# Job: Given a free-text client situation + a list of candidate schemes /
# services (the embedding retriever's top-K), select the most relevant 3–5
# and explain WHY for each, with explicit citation of supporting text.
#
# Why CO-STAR fits here:
#   - The TASK is multi-objective (select + rank + reason + cite), so the
#     Objective section needs to enumerate each goal.
#   - The AUDIENCE is technical (SAOs know their domain), so we tell the
#     model not to over-explain basics — Audience section saves tokens.
#   - The RESPONSE format must be machine-readable JSON for the downstream
#     UI / evaluator — so Response-format spells out the exact schema.

# Separated as its own constant so JSON braces don't conflict with .format()
# escaping. Cleaner than wrapping the example in {{ }}.
_RECOMMENDER_OUTPUT_SCHEMA = """{
  "overall_summary": "<1-sentence summary of the case pattern>",
  "categories_touched": ["<sgw category slug>", "..."],
  "recommendations": [
    {
      "parent_id": "<exact id from one of the candidates>",
      "title": "<exact title from that candidate>",
      "fit_score": <integer 1-5, where 5 = strongly fits>,
      "rationale": "<1-2 sentences on why this fits this client>",
      "eligibility_flags": ["<short note on something the SAO should verify>"],
      "evidence_quote": "<short verbatim phrase from the candidate text>"
    }
  ]
}"""


def render_candidates_block(results: "Iterable[Result]") -> str:
    """Render retriever Results as XML-delimited candidate blocks.

    XML tags (rather than triple backticks) are used because we have many
    candidates and need per-candidate boundaries that the model can address
    by ID in its output. This is the standard W1 advice for multi-section
    structured inputs.
    """
    lines: list[str] = []
    for r in results:
        cats = ",".join(r.categories) if r.categories else ""
        # Truncate section_text to keep prompt size manageable. Full text
        # remains available in the corpus if the UI wants to expand.
        section_text = r.section_text or ""
        if len(section_text) > 1200:
            section_text = section_text[:1200].rstrip() + "..."
        lines.append(
            f'<candidate id="{r.parent_id}" '
            f'title="{r.title}" '
            f'kind="{r.kind}" '
            f'categories="{cats}">'
        )
        lines.append(f"  tagline: {r.tagline}")
        lines.append(f"  matched_section ({r.best_section}): {section_text}")
        lines.append("</candidate>")
    return "\n".join(lines)


def make_recommender_prompt(client_situation: str, candidates_block: str) -> str:
    """Build the CO-STAR prompt for the UC#1 recommender LLM call.

    Args:
        client_situation : Natural-language description of the client's
                           situation (one short paragraph is ideal — long
                           inputs dilute the signal).
        candidates_block : The XML-rendered candidate list, typically built
                           by :func:`render_candidates_block` from the
                           retriever's top-K results.

    Returns:
        The full prompt string, ready to pass to ``llm.get_completion``.
    """
    return f"""# CONTEXT
You are an AI co-pilot assisting a Social Assistance Officer (SAO) at
Singapore's Ministry of Social and Family Development (MSF). The SAO is
reviewing a client's situation and needs to identify which government
schemes and community services from the SupportGoWhere catalogue are
most relevant.

This is a high-stakes domain: recommending an irrelevant scheme wastes
the SAO's time; missing a relevant one means a family doesn't get help
they qualify for. The SAO will make the final call — your job is to
surface the strongest candidates with clear evidence so they can decide
quickly.

# OBJECTIVE
From the candidate list below, identify the 3-5 most relevant
schemes/services for this client. For each one:
  1. State WHY it fits (cite a short verbatim phrase from the candidate text).
  2. Flag any key eligibility considerations the SAO should verify.
  3. Assign a fit_score from 1 (weak) to 5 (strong).

Do NOT include candidates that are clearly off-topic. It is better to
return 3 strong recommendations than 5 mediocre ones.

# STYLE
Professional, concise, factual. Plain English. No marketing language.
Each rationale should be 1-2 sentences max — the SAO needs a quick
glance, not a report.

# TONE
Helpful and neutral. Do not assume facts about the client that are not
stated in the situation. If a scheme might be relevant but depends on
unstated information, say so explicitly (e.g., "if household income
qualifies").

# AUDIENCE
A trained SAO who already knows the scheme names and basic mechanics.
You don't need to explain what ComCare is — they know. Focus on
*fit-to-this-client*, not on basic scheme description.

# RESPONSE FORMAT
Return a single valid JSON object matching this schema exactly. No
markdown fences, no commentary outside the JSON.

{_RECOMMENDER_OUTPUT_SCHEMA}

# CLIENT SITUATION
<client_situation>
{client_situation}
</client_situation>

# CANDIDATES
{candidates_block}
"""
