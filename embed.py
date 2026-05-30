"""Embed the chunked SupportGoWhere corpus with OpenAI text-embedding-3-small.

Inputs : data/chunks/chunks.jsonl
Outputs: data/embeddings/vectors.npy   (float32 array, shape (N, 1536))
         data/embeddings/index.jsonl   (lightweight metadata per row, in
                                       the same order as vectors.npy)
         data/embeddings/manifest.json (stats + provenance)

Resumable: if vectors.npy already exists and matches the chunk count, the
script no-ops (skip the API calls). Delete vectors.npy to force a re-embed.

Cost: ~$0.005 for our 2,070-chunk corpus on text-embedding-3-small.
"""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from llm import EMBED_DIM, embed_batch

ROOT = Path(__file__).parent
CHUNKS_JSONL = ROOT / "data" / "chunks" / "chunks.jsonl"
OUT_DIR = ROOT / "data" / "embeddings"
VECTORS_PATH = OUT_DIR / "vectors.npy"
INDEX_PATH = OUT_DIR / "index.jsonl"
MANIFEST_PATH = OUT_DIR / "manifest.json"

# OpenAI accepts up to 2048 inputs per embeddings request; use a smaller
# batch for friendlier latency + safer error recovery.
BATCH_SIZE = 256


def load_chunks() -> list[dict]:
    """Read chunks.jsonl in order. Order is the canonical row index."""
    chunks: list[dict] = []
    with CHUNKS_JSONL.open("r", encoding="utf-8") as fp:
        for line in fp:
            line = line.strip()
            if line:
                chunks.append(json.loads(line))
    return chunks


def index_record(chunk: dict, row: int) -> dict:
    """Lightweight metadata we store alongside the vectors for lookup."""
    return {
        "row": row,
        "chunk_id": chunk["chunk_id"],
        "parent_id": chunk["parent_id"],
        "kind": chunk["kind"],
        "section": chunk["section"],
        "title": chunk["title"],
        "char_count": chunk["char_count"],
    }


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    chunks = load_chunks()
    print(f"Loaded {len(chunks)} chunks from {CHUNKS_JSONL.relative_to(ROOT)}")

    # Skip chunks with empty text (defensive — chunker shouldn't produce these,
    # but if it does, we exclude them rather than embed empty strings).
    valid = [c for c in chunks if (c.get("text") or "").strip()]
    skipped = len(chunks) - len(valid)
    if skipped:
        print(f"  Skipping {skipped} empty-text chunks")

    # Resume: if vectors already exist and match count, no-op.
    if VECTORS_PATH.exists():
        existing = np.load(VECTORS_PATH)
        if existing.shape == (len(valid), EMBED_DIM):
            print(
                f"vectors.npy already present with matching shape "
                f"{existing.shape}; nothing to do."
            )
            return
        print(f"  vectors.npy exists but shape mismatch "
              f"(have {existing.shape}, want {(len(valid), EMBED_DIM)}); re-embedding")

    # Embed in batches.
    started = datetime.now(timezone.utc)
    all_vectors: list[list[float]] = []
    n_batches = (len(valid) + BATCH_SIZE - 1) // BATCH_SIZE
    for batch_idx in range(n_batches):
        lo = batch_idx * BATCH_SIZE
        hi = min(lo + BATCH_SIZE, len(valid))
        texts = [valid[i]["text"] for i in range(lo, hi)]
        t0 = time.time()
        vecs = embed_batch(texts)
        dt = time.time() - t0
        all_vectors.extend(vecs)
        print(f"  batch {batch_idx + 1:2d}/{n_batches}  "
              f"rows {lo:5d}-{hi - 1:5d}  ({dt:.2f}s)")

    vectors = np.asarray(all_vectors, dtype=np.float32)
    assert vectors.shape == (len(valid), EMBED_DIM), (
        f"unexpected vector shape: got {vectors.shape}, "
        f"expected {(len(valid), EMBED_DIM)}"
    )

    # Save vectors + lightweight index (same row order).
    np.save(VECTORS_PATH, vectors)
    with INDEX_PATH.open("w", encoding="utf-8") as fp:
        for row, chunk in enumerate(valid):
            fp.write(json.dumps(index_record(chunk, row), ensure_ascii=False) + "\n")

    ended = datetime.now(timezone.utc)
    manifest = {
        "started_at": started.isoformat(),
        "ended_at": ended.isoformat(),
        "duration_sec": (ended - started).total_seconds(),
        "model": "text-embedding-3-small",
        "embedding_dim": EMBED_DIM,
        "batch_size": BATCH_SIZE,
        "chunks_input": len(chunks),
        "chunks_skipped_empty": skipped,
        "chunks_embedded": len(valid),
        "vectors_path": str(VECTORS_PATH.relative_to(ROOT)),
        "index_path": str(INDEX_PATH.relative_to(ROOT)),
        "vectors_bytes": VECTORS_PATH.stat().st_size,
    }
    MANIFEST_PATH.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print()
    print(f"Embedded   : {len(valid)} chunks")
    print(f"Vectors    : {VECTORS_PATH.relative_to(ROOT)} "
          f"({vectors.nbytes / 1024:.1f} KB)")
    print(f"Index      : {INDEX_PATH.relative_to(ROOT)}")
    print(f"Manifest   : {MANIFEST_PATH.relative_to(ROOT)}")
    print(f"Duration   : {manifest['duration_sec']:.1f}s")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001 — print and exit non-zero
        print(f"FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise
