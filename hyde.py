"""HyDE (Hypothetical Document Embeddings) — Topic 4.2 Pre-Retrieval.

Closes the vocabulary gap between how SAOs phrase a client need
("dementia day-care") and how SupportGoWhere describes the matching
scheme ("Senior Activity Centre with respite services"). Embedding
similarity works best when query and document use similar wording;
HyDE generates a hypothetical SGW-style scheme description for the
query, then embeds THAT for retrieval.

Source: Gao et al. 2022 — "Precise Zero-Shot Dense Retrieval without
Relevance Labels." Topic 4.2 references this as a query-transformation
technique.

Public surface
--------------
    from hyde import generate_hypothetical_scheme
    hyde_text = generate_hypothetical_scheme("single mum, lost job, kids")
    # hyde_text -> "...a scheme that provides short-to-medium-term
    #              financial assistance for low-income families..."

The returned text is then embedded and used for retrieval ALONGSIDE
the original query — not as a replacement.
"""

from __future__ import annotations

from llm import get_completion


_HYDE_PROMPT_TEMPLATE = """You are helping a Social Assistance Officer (SAO) in Singapore find the
right government scheme or community service for a client.

Given the client need below, write a 2-3 sentence description of a
HYPOTHETICAL Singapore government scheme or community service that
would help. Use the vocabulary and phrasing typical of SupportGoWhere
scheme descriptions:
  - Mention WHO the scheme is for (eligibility hints).
  - Mention WHAT it provides (financial aid, counselling, day-care,
    home help, etc.).
  - Use formal Singapore public-sector language (e.g. "low-income
    households", "Singapore Citizens", "respite care services").

Do NOT invent a specific scheme name. Just describe what such a
scheme would do.

Return ONLY the description text — no preamble, no commentary, no
quotation marks.

# CLIENT NEED
{client_need}

# HYPOTHETICAL SCHEME DESCRIPTION
"""


def generate_hypothetical_scheme(client_need: str) -> str:
    """Generate an SGW-style scheme description for a client need.

    Fail-soft: if the LLM call errors, returns the original need
    unchanged. This guarantees that HyDE never breaks retrieval —
    worst case it's just a no-op augmentation.
    """
    prompt = _HYDE_PROMPT_TEMPLATE.format(client_need=client_need.strip())
    try:
        text = get_completion(prompt, temperature=0.0)
    except Exception:  # noqa: BLE001 — fail-soft to original query
        return client_need
    return (text or client_need).strip().strip('"').strip()
