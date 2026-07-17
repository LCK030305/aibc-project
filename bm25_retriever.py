"""BM25 sparse retriever + Reciprocal Rank Fusion — Topic 4.3 Retrieval.

BM25 (Best Match 25) is a classical sparse-keyword retrieval method.
It complements our dense (embedding) retriever by catching cases
where the EXACT scheme acronym or term appears in the query but is
hard for the embedding model to surface:

  - "CHAS" — embedding may match generic "healthcare subsidy" pages
    but miss the literal CHAS scheme record
  - "MUIS-FAS" — same problem for Muslim community schemes
  - "ATF" — Assistive Technology Fund
  - "EASE" — Enhancement for Active Seniors

Reciprocal Rank Fusion (RRF) is the standard way to combine the
ranked lists from two different retrievers without needing to
normalise their scores. Formula:

    rrf_score(doc) = Σ over retrievers of 1 / (k + rank(doc))

where k=60 is a smoothing constant (Cormack et al. 2009, the
original RRF paper).

Public surface
--------------
    from bm25_retriever import get_bm25, rrf_merge

    bm25 = get_bm25()                  # cached singleton, loads once
    sparse_hits = bm25.search(q, k=15) # returns [(parent_id, score), ...]

    merged_pids = rrf_merge(
        [dense_pids_in_order, sparse_pids_in_order, hyde_pids_in_order],
        top_k=15,
    )
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path

from rank_bm25 import BM25Okapi

ROOT = Path(__file__).parent
CHUNKS_FILE = ROOT / "data" / "chunks" / "chunks.jsonl"

_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9\-]*")


def _tokenize(text: str) -> list[str]:
    """Lowercase + alphanumeric tokens. Cheap, deterministic."""
    return [m.group(0).lower() for m in _WORD_RE.finditer(text or "")]


class BM25Retriever:
    """In-memory BM25 over our section-level chunks, deduped to parent_id.

    We build BM25 over CHUNKS (not records) so a query that hits a
    very specific "who is this for" section ranks the parent record
    accordingly. Then dedup-by-parent at query time, keeping each
    parent's best-scoring chunk.
    """

    def __init__(self) -> None:
        self.chunks: list[dict] = []
        with CHUNKS_FILE.open("r", encoding="utf-8") as f:
            for line in f:
                self.chunks.append(json.loads(line))
        # Tokenise the searchable text per chunk: title + text gives the
        # acronym ("CHAS") AND the surrounding content, both of which BM25
        # uses for matching.
        corpus_tokens = [
            _tokenize(f"{c.get('title', '')} {c.get('text', '')}")
            for c in self.chunks
        ]
        self.bm25 = BM25Okapi(corpus_tokens)
        # Index parent_id per chunk for fast dedup.
        self.parent_ids = [c.get("parent_id", "") for c in self.chunks]

    def search(self, query: str, k: int = 15) -> list[tuple[str, float]]:
        """Return up to ``k`` (parent_id, bm25_score) pairs, ranked.

        Dedup-by-parent: each parent appears at most once, keeping its
        best-scoring chunk.
        """
        tokens = _tokenize(query)
        if not tokens:
            return []
        scores = self.bm25.get_scores(tokens)
        # Best score per parent_id.
        best_by_pid: dict[str, float] = defaultdict(lambda: float("-inf"))
        for pid, score in zip(self.parent_ids, scores):
            if score > best_by_pid[pid]:
                best_by_pid[pid] = score
        ranked = sorted(best_by_pid.items(), key=lambda x: -x[1])
        return ranked[:k]


_BM25_SINGLETON: BM25Retriever | None = None


def get_bm25() -> BM25Retriever:
    """Lazy-loaded singleton — built once per process."""
    global _BM25_SINGLETON
    if _BM25_SINGLETON is None:
        _BM25_SINGLETON = BM25Retriever()
    return _BM25_SINGLETON


def rrf_merge(
    ranked_lists: list[list[str]],
    top_k: int = 15,
    k_const: int = 60,
) -> list[str]:
    """Combine ranked parent_id lists via Reciprocal Rank Fusion.

    Args:
        ranked_lists : List of ranked parent_id lists (best first). Each
                        comes from a different retriever (e.g., dense,
                        sparse, HyDE).
        top_k        : How many parent_ids to return.
        k_const      : RRF smoothing constant. 60 is the original paper's
                        value and a fine default.

    Returns:
        List of parent_ids, ranked by aggregated RRF score, top_k entries.
    """
    rrf_scores: dict[str, float] = defaultdict(float)
    for ranked in ranked_lists:
        for rank, pid in enumerate(ranked, start=1):
            rrf_scores[pid] += 1.0 / (k_const + rank)
    return [
        pid for pid, _ in sorted(rrf_scores.items(), key=lambda x: -x[1])
    ][:top_k]
