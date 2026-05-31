"""Router layer for UC#1 — Topic 2.6 Decision Chain (multi-class).

After the safety guard (step 1) passes the input, this classifier routes
the input to one of four downstream behaviours:

  - ``client_case``       The user is describing a client's situation —
                          family circumstances, income, life events.
                          The system runs the full RAG pipeline.
  - ``scheme_lookup``     The user is asking about a specific named
                          scheme or service. The system still uses RAG
                          retrieval but the tagging helps later UI
                          differentiation.
  - ``general_question``  General question about the SGW catalogue or
                          procedural ("how do I refer a client?"). The
                          system politely redirects; no retrieval.
  - ``out_of_scope``      Question not related to Singapore social
                          services. Polite refusal; no retrieval.

Bootcamp-principles cheat sheet
-------------------------------
- Topic 2.6 § Decision Chain (multi-class) — exact bootcamp framing of
  routing via "soft programming logic" using the LLM instead of regex
  or keyword rules.
- Topic 2.5 § Multi-action — single LLM call returns BOTH the category
  AND a one-sentence rationale (handy for the Behind-the-Scenes panel).
- Topic 2.7 § Exception Handling — fail-OPEN here (unlike safety): if
  the classifier itself errors, default to ``client_case`` so the user
  still gets a recommendation attempt rather than being stranded.

Public surface
--------------
    from router import step_2_classify_query
    result = step_2_classify_query("Single mother, lost job")
    # -> {"category": "client_case", "reason": "..."}
"""

from __future__ import annotations

import json

from llm import get_completion_from_messages

ROUTER_SYSTEM_PROMPT = """\
You are a router for a Singapore Social Assistance Officer (SAO) AI tool.
The tool's main job is to recommend MSF programmes and community services
from the SupportGoWhere catalogue based on a client's situation.

Classify the user's input into EXACTLY ONE of these four categories:

  - "client_case"      The user is describing a real or hypothetical
                       client's situation: family circumstances, income,
                       needs, life events, demographic details. The
                       system should retrieve relevant schemes/services.

  - "scheme_lookup"    The user is asking about a specific named scheme
                       or service (e.g. "tell me about ComCare SMTA",
                       "what does CHAS cover?"). The system should
                       retrieve information about that specific item.

  - "general_question" The user is asking a procedural or definitional
                       question about Singapore social services or how
                       the tool works (e.g. "what is the difference
                       between schemes and services?"). No retrieval.

  - "out_of_scope"     The user's input is not related to Singapore
                       social services at all (weather, jokes, unrelated
                       coding tasks). Politely refuse.

Output a single JSON object in this exact shape (no markdown fences):
{
  "category": "<one of: client_case, scheme_lookup, general_question, out_of_scope>",
  "reason":   "<one short sentence (<= 20 words) on why you chose this category>"
}
"""

VALID_CATEGORIES: set[str] = {
    "client_case",
    "scheme_lookup",
    "general_question",
    "out_of_scope",
}


def step_2_classify_query(client_text: str) -> dict:
    """Topic 2.6 Decision Chain — multi-class router.

    Args:
        client_text : The raw client-side input. Assumed to have already
                      passed the safety guard.

    Returns:
        A dict ``{"category": "<one of VALID_CATEGORIES>", "reason": str}``.

    Failure mode (fail-OPEN — opposite of the safety guard):
        If the classifier LLM call errors out, or returns non-JSON, or
        returns an unknown category, we default to ``client_case`` so
        the user still gets a retrieval attempt rather than a blank
        screen. The router is a *helpful* convenience, not a *gate*.
    """
    messages: list[dict] = [
        {"role": "system", "content": ROUTER_SYSTEM_PROMPT},
        {"role": "user",   "content": f"<incoming-message>{client_text}</incoming-message>"},
    ]

    try:
        raw = get_completion_from_messages(
            messages,
            max_tokens=120,
            response_format={"type": "json_object"},
        )
    except Exception as exc:  # noqa: BLE001 — fail-open by design
        return {
            "category": "client_case",
            "reason": (
                f"Classifier call failed ({type(exc).__name__}); "
                "defaulting to client_case so the user still gets results."
            ),
        }

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {
            "category": "client_case",
            "reason": "Classifier returned non-JSON; defaulting to client_case.",
        }

    category = str(parsed.get("category", "")).strip().lower()
    if category not in VALID_CATEGORIES:
        return {
            "category": "client_case",
            "reason": (
                f"Classifier returned unknown category {category!r}; "
                "defaulting to client_case."
            ),
        }
    return {
        "category": category,
        "reason": str(parsed.get("reason", "")).strip(),
    }
