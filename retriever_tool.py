"""CrewAI Tool wrapper around our retriever — Topic 5.5 §Tools.

Each specialist agent receives an instance of ``CategoryRetrieverTool``
pre-filtered to its SGW category. This is the **deterministic, task-level
tool placement** pattern from Topic 5.5: every specialist's task uses
its tool, guaranteeing every recommendation is grounded in retrieved
SupportGoWhere text.

The tool reuses our existing dense + HyDE + BM25 + RRF retrieval stack
(no duplication) — specialists just see a category-scoped slice.
"""

from __future__ import annotations

from typing import Type

from crewai.tools import BaseTool
from pydantic import BaseModel, Field

from retriever import get_retriever


class _RetrieverToolInput(BaseModel):
    """Schema CrewAI uses to validate agent calls to this tool."""
    query: str = Field(
        ...,
        description=(
            "A natural-language description of the client's need from the "
            "perspective of this specialist's domain. The retriever will "
            "embed this and surface the most relevant schemes/services."
        ),
    )


class CategoryRetrieverTool(BaseTool):
    """Per-category retriever tool. One instance per specialist agent.

    The ``category`` is baked in at construction time so the agent
    cannot accidentally search outside its domain.
    """

    name: str = "search_schemes"
    description: str = (
        "Search SupportGoWhere for schemes and services matching the "
        "client need. Returns the top candidates with their titles, "
        "section excerpts, and IDs."
    )
    args_schema: Type[BaseModel] = _RetrieverToolInput

    category: str = Field(..., description="SGW category to filter by.")
    k: int = Field(default=8, description="Top-K candidates to return.")

    def _run(self, query: str) -> str:
        retriever = get_retriever()
        results = retriever.search(query, k=self.k, category=self.category)
        if not results:
            return (
                f"No schemes found in category '{self.category}' for query: "
                f"'{query}'. This domain may not be relevant for this case."
            )
        lines = []
        for r in results:
            text = (r.section_text or "")[:600]
            lines.append(
                f"[id={r.parent_id}] {r.title}\n"
                f"  section: {r.best_section}\n"
                f"  text: {text}\n"
            )
        return (
            f"Top {len(results)} schemes in category '{self.category}' "
            f"for query '{query}':\n\n" + "\n".join(lines)
        )
