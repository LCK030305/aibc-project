"""SupportGoWhere semantic retriever for the SAO co-pilot.

Bootcamp-principles cheat sheet
-------------------------------
- Week 1 § Helper pattern:        ``Retriever.search()`` mirrors the
  ``get_completion()`` style — single call, clean signature, deterministic.
- Week 1 § Delimiter conventions: handled in prompts.py (separate concern).
- Week 2 § Exception handling:    defensive loading + helpful errors.
- Week 4 § Embeddings & RAG:      cosine similarity over OpenAI's
  text-embedding-3-small vectors.
- Week 4 § Search beyond keywords: free-text client situations match
  semantically — no keyword overlap required.
- Week 5 § Pre-retrieval:         section-level chunking (done in chunker.py)
  so eligibility / apply / highlights can match independently.
- Week 5 § Post-retrieval:        dedup by parent_id; optional category /
  kind filtering; per-result category metadata.
- Week 6 § Modular project layout: this file does one thing, no LLM
  generation logic — that lives in recommender.py.
- Week 7+ § Streamlit-ready:      ``search()`` returns plain dataclasses
  the UI can render directly.

Public surface
--------------
    from retriever import get_retriever
    r = get_retriever()
    results = r.search("single mother lost her job", k=5)
    for result in results:
        print(result.rank, result.title, result.categories)

Run as a script to see a demo across three SAO-style client scenarios.
"""

from __future__ import annotations

import io
import json
import sys
from collections import Counter
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import numpy as np

from llm import EMBED_DIM, embed_batch

# Force UTF-8 stdout (Windows PowerShell defaults to cp1252, breaks on
# zero-width spaces / em-dashes in the corpus). Wrapped in try/except so
# Streamlit / Jupyter / other contexts that pre-wrap stdout are left alone.
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

ROOT = Path(__file__).parent
VECTORS_PATH = ROOT / "data" / "embeddings" / "vectors.npy"
INDEX_PATH = ROOT / "data" / "embeddings" / "index.jsonl"
CHUNKS_PATH = ROOT / "data" / "chunks" / "chunks.jsonl"
TOPIC_MAPPING_PATH = ROOT / "data" / "topic_mapping.json"


@dataclass
class Result:
    """A single retrieved scheme/service, deduplicated to one entry per record.

    The ``best_section`` and ``section_text`` reveal *why* this record matched
    (e.g., the query hit the "who" eligibility section). Useful for the UI
    to show evidence and for the LLM ranker to ground its reasoning.
    """

    rank: int
    score: float
    parent_id: str
    kind: str                 # "scheme" or "service"
    title: str
    tagline: str
    url: str
    best_section: str         # e.g., "who", "apply", "highlights", "tagline"
    section_text: str         # full text of the matching section
    categories: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """JSON-serialisable form (handy for UI / logging / eval)."""
        return {
            "rank": self.rank,
            "score": round(self.score, 4),
            "parent_id": self.parent_id,
            "kind": self.kind,
            "title": self.title,
            "tagline": self.tagline,
            "url": self.url,
            "best_section": self.best_section,
            "section_text": self.section_text,
            "categories": self.categories,
        }


class Retriever:
    """Embedding-based retrieval over the chunked SupportGoWhere corpus.

    The corpus is loaded once at construction time (~50 ms). Subsequent
    ``search()`` calls only pay for a single embedding API call (~0.3 s) plus
    in-memory cosine similarity (microseconds at this scale).
    """

    def __init__(self) -> None:
        # --- vectors --------------------------------------------------------
        if not VECTORS_PATH.exists():
            raise FileNotFoundError(
                f"{VECTORS_PATH} missing — run `python embed.py` first."
            )
        self._vectors: np.ndarray = np.load(VECTORS_PATH)
        # Pre-normalise to unit length for fast cosine similarity (= dot product).
        norms = np.linalg.norm(self._vectors, axis=1, keepdims=True)
        self._unit_vectors: np.ndarray = self._vectors / np.clip(norms, 1e-12, None)

        # --- light index (one record per vector row) -----------------------
        self._index: list[dict] = []
        with INDEX_PATH.open("r", encoding="utf-8") as f:
            for line in f:
                self._index.append(json.loads(line))
        if self._unit_vectors.shape[0] != len(self._index):
            raise RuntimeError(
                f"vector/index row mismatch: {self._unit_vectors.shape[0]} vs "
                f"{len(self._index)} — re-run embed.py to regenerate."
            )

        # --- full chunks (we need the text for ``section_text`` + tagline) -
        self._chunks: dict[str, dict] = {}
        with CHUNKS_PATH.open("r", encoding="utf-8") as f:
            for line in f:
                c = json.loads(line)
                self._chunks[c["chunk_id"]] = c

        # --- parent_id -> list of SGW topic slugs --------------------------
        if TOPIC_MAPPING_PATH.exists():
            topic_data = json.loads(TOPIC_MAPPING_PATH.read_text(encoding="utf-8"))
            self._parent_topics: dict[str, list[str]] = {}
            for topic, items in topic_data.items():
                for pid in items.get("schemes", []):
                    self._parent_topics.setdefault(pid, []).append(topic)
                for pid in items.get("services", []):
                    self._parent_topics.setdefault(pid, []).append(topic)
            for pid in self._parent_topics:
                self._parent_topics[pid] = sorted(self._parent_topics[pid])
        else:
            self._parent_topics = {}

    # ---- public API -------------------------------------------------------

    def search(
        self,
        query: str,
        k: int = 5,
        category: str | None = None,
        kind: str | None = None,
    ) -> list[Result]:
        """Return top-``k`` deduplicated results for a free-text query.

        Args:
            query    : Natural-language description of the client's situation.
            k        : Maximum number of distinct schemes/services to return.
            category : Optional SGW topic slug filter (e.g., "financial-support").
                       Only records tagged under this category are kept.
            kind     : Optional "scheme" or "service" filter.

        Returns:
            List of :class:`Result`, ranked best-first. Each entry is a
            *distinct* parent record (the best-scoring section determines
            its rank). May be shorter than ``k`` if filters are restrictive.

        Raises:
            ValueError: if the query is empty after stripping.
        """
        if not query or not query.strip():
            raise ValueError("query must be a non-empty string")
        if k < 1:
            raise ValueError("k must be at least 1")

        # 1. Embed the query (one API call).
        q_vec = np.asarray(embed_batch([query])[0], dtype=np.float32)
        q_unit = q_vec / max(np.linalg.norm(q_vec), 1e-12)

        # 2. Cosine similarity vs. every chunk (in-memory, microseconds).
        sims = self._unit_vectors @ q_unit
        order = np.argsort(-sims)  # descending

        # 3. Walk in score order; dedup by parent; apply filters.
        seen_parents: set[str] = set()
        results: list[Result] = []
        for i in order:
            idx_item = self._index[int(i)]
            pid: str = idx_item["parent_id"]
            if pid in seen_parents:
                continue
            if kind is not None and idx_item["kind"] != kind:
                continue
            cats = self._parent_topics.get(pid, [])
            if category is not None and category not in cats:
                continue

            chunk = self._chunks.get(idx_item["chunk_id"], {})
            tagline_chunk = self._chunks.get(f"{pid}__tagline", {})

            seen_parents.add(pid)
            results.append(Result(
                rank=len(results) + 1,
                score=float(sims[int(i)]),
                parent_id=pid,
                kind=idx_item["kind"],
                title=idx_item["title"],
                tagline=tagline_chunk.get("text", chunk.get("tagline", "")),
                url=chunk.get("url", ""),
                best_section=idx_item["section"],
                section_text=chunk.get("text", ""),
                categories=cats,
            ))
            if len(results) >= k:
                break
        return results

    def category_breakdown(self, results: list[Result]) -> dict[str, int]:
        """Count how often each SGW category appears across the given results.

        Useful for "this case touches: Financial (8/10), Family (10/10), ..."
        UX in the recommender and for the eventual Streamlit summary card.
        """
        counter: Counter = Counter()
        for r in results:
            counter.update(r.categories)
        return dict(counter.most_common())

    @property
    def n_records(self) -> int:
        return len({item["parent_id"] for item in self._index})

    @property
    def n_chunks(self) -> int:
        return len(self._index)


# Module-level singleton so callers don't reload the corpus per request.
@lru_cache(maxsize=1)
def get_retriever() -> Retriever:
    """Return the lazily-initialised, process-wide :class:`Retriever` singleton."""
    return Retriever()


# ---------------------------------------------------------------------------
# Demo / smoke test — re-runs the 3-client scenario with the locked corpus.
# Invoke with: python retriever.py
# ---------------------------------------------------------------------------

DEMO_QUERIES = [
    ("Client 1", "Single mother of two young children, recently lost her job, "
                 "needs financial help to pay rent and utilities"),
    ("Client 2", "Elderly with dementia, family needs respite care during the "
                 "day so they can work"),
    ("Client 3", "Teenager showing suicide warning signs, family needs urgent "
                 "support"),
]


def _demo() -> None:
    r = get_retriever()
    print(f"Corpus loaded: {r.n_records} records / {r.n_chunks} chunks")
    print()
    for label, query in DEMO_QUERIES:
        print("=" * 88)
        print(f"{label}: {query}")
        print()
        results = r.search(query, k=10)

        # Per-result table.
        header = f"{'rank':>4} {'score':>5}  {'kind':7s}  {'parent_id':20s}  {'title':40s}  categories"
        print(header)
        print("-" * len(header))
        for res in results:
            title = (res.title[:38] + "..") if len(res.title) > 40 else res.title
            cats = ", ".join(res.categories) or "(none)"
            print(f"{res.rank:4d} {res.score:.3f}  {res.kind:7s}  "
                  f"{res.parent_id:20s}  {title:40s}  {cats}")

        # Category-occurrence summary.
        print()
        print("Categories touched (frequency across top 10):")
        for cat, n in r.category_breakdown(results).items():
            bar = "#" * n
            print(f"  {cat:25s} {n:2d}  {bar}")
        print()


if __name__ == "__main__":
    try:
        _demo()
    except Exception as exc:  # noqa: BLE001
        print(f"FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise
