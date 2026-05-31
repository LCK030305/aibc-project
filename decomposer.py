"""Decomposer for UC#1 — Topic 2.4 Least-to-Most Prompting.

For complex multi-need client situations, split the case into discrete
sub-needs and retrieve against each separately. The recommender then
sees a richer, more diverse candidate pool than a single embedding
query over the whole text could surface.

Why this helps
--------------
A single client paragraph that mixes 3 needs (e.g., financial help for
a mother + dementia day-care for her parent + special-ed for her child)
embeds to a vector that pulls toward the "centre" of those needs — and
may miss the strongest fit for any individual sub-need. Decomposing
into separate retrieval queries (one per sub-need) recovers that
precision without us having to engineer the embedding manually.

Behaviour
---------
- **Single-need cases** (e.g. "single mother lost her job, needs rent help"):
  decomposer returns a 1-element list containing the original text.
  The downstream pipeline behaves exactly as before.
- **Multi-need cases**: returns 2-5 short sub-need descriptions, each
  focused on ONE dimension of need.

Bootcamp-principles cheat sheet
-------------------------------
- Topic 2.4 § Least-to-Most Prompting (Cornell paper) — split a complex
  problem into smaller sub-problems, solve each, then combine.
- Topic 2.6 § Prompt Chaining — output of this step (list of sub-needs)
  becomes the input to N parallel retrieval calls.
- Topic 2.7 § Exception Handling — fail-OPEN: if decomposition errors,
  fall back to single-need pipeline so the user never loses results.

Public surface
--------------
    from decomposer import step_3_decompose
    sub_needs = step_3_decompose("Caregiver of dementia parent...")
    # -> ["Financial help for caregiver", "Dementia day-care...", ...]
"""

from __future__ import annotations

import json

from llm import get_completion_from_messages

DECOMPOSER_SYSTEM_PROMPT = """\
You are a decomposer for a Singapore Social Assistance Officer (SAO) AI
tool. Your job is to read a client situation and split it into
DISCRETE sub-needs — one focused need per item.

Rules:
  1. SIMPLE cases with a single coherent need (e.g. "single mother lost
     her job, needs rent help") — return a 1-element array containing a
     concise restatement of that single need. Do NOT split it further.
  2. COMPLEX cases with multiple distinct needs (e.g. caregiver of
     dementia parent + child with special needs + financial strain) —
     return 2 to 5 sub-need descriptions, each focused on ONE dimension.
  3. Each sub-need should be a short standalone sentence that a
     retrieval system can match against a scheme/service description.
  4. Preserve concrete signals from the original (income, ages, family
     structure, geographic info if present) inside the relevant
     sub-need. Don't lose detail in the split.
  5. Do NOT invent needs that aren't supported by the original text.

Output a single JSON object in this exact shape (no markdown fences):
{
  "is_complex": <true if you split into 2+ sub-needs, false otherwise>,
  "sub_needs": [
    "<sub-need 1, short standalone sentence>",
    "<sub-need 2 if any>",
    "..."
  ]
}
"""


def step_3_decompose(client_text: str) -> dict:
    """Topic 2.4 Least-to-Most — return sub-needs for the client case.

    Args:
        client_text : The (already safety-checked, already routed)
                      client-situation text.

    Returns:
        A dict::

            {
                "is_complex": bool,
                "sub_needs":  [str, ...],   # always non-empty
            }

        For simple cases, ``sub_needs`` is a single-element list (often
        the original text rephrased). For complex cases, 2-5 items.

    Failure mode (fail-OPEN):
        If the LLM call errors, returns
        ``{"is_complex": False, "sub_needs": [client_text]}`` so the
        downstream pipeline still runs against the original input.
    """
    if not client_text or not client_text.strip():
        return {"is_complex": False, "sub_needs": [client_text or ""]}

    messages: list[dict] = [
        {"role": "system", "content": DECOMPOSER_SYSTEM_PROMPT},
        {"role": "user",   "content": f"<incoming-message>{client_text}</incoming-message>"},
    ]

    try:
        raw = get_completion_from_messages(
            messages,
            max_tokens=400,
            response_format={"type": "json_object"},
        )
    except Exception:
        return {"is_complex": False, "sub_needs": [client_text]}

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {"is_complex": False, "sub_needs": [client_text]}

    sub_needs_raw = parsed.get("sub_needs", [])
    if not isinstance(sub_needs_raw, list):
        return {"is_complex": False, "sub_needs": [client_text]}

    # Filter to non-empty strings; cap at 5 to bound downstream cost.
    sub_needs: list[str] = []
    for item in sub_needs_raw[:5]:
        if isinstance(item, str) and item.strip():
            sub_needs.append(item.strip())
    if not sub_needs:
        return {"is_complex": False, "sub_needs": [client_text]}

    return {
        "is_complex": bool(parsed.get("is_complex", len(sub_needs) > 1)),
        "sub_needs": sub_needs,
    }
