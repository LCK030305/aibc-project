"""Thin LLM helper module — single place every other module imports from.

Patterns follow what the bootcamp Week 1 notebook uses (raw `openai` SDK,
`get_completion(prompt, model)`), with a few production-friendly additions
the bootcamp picks up in Week 2 / Week 5:

  - Loads OPENAI_API_KEY from .env via python-dotenv (Week 5 Topic 5.2)
  - Single shared client (avoids re-init on every call)
  - `embed_batch(texts)` wrapper for embeddings with batching
  - Defensive defaults (temperature=0 for deterministic calls)
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable

from dotenv import load_dotenv
from openai import OpenAI

# Load .env from the same dir as this module — robust to caller CWD.
load_dotenv(Path(__file__).parent / ".env")

# Bootcamp default models (Week 1 / Week 4).
# NOTE: gpt-4o-mini in the bootcamp notebook is replaced here with
# gpt-4.1-mini because the latter is what this project's key actually has
# access to. They are equivalent-tier (cheap, capable) workhorses.
DEFAULT_CHAT_MODEL = "gpt-4.1-mini"
DEFAULT_EMBED_MODEL = "text-embedding-3-small"  # 1536-dim, cheapest tier
EMBED_DIM = 1536

_client: OpenAI | None = None


def get_client() -> OpenAI:
    """Return a lazily-initialised shared OpenAI client."""
    global _client
    if _client is None:
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError(
                "OPENAI_API_KEY not set. Add it to .env at the project root."
            )
        _client = OpenAI(api_key=api_key)
    return _client


def get_completion(
    prompt: str,
    model: str = DEFAULT_CHAT_MODEL,
    temperature: float = 0.0,
    response_format: dict | None = None,
) -> str:
    """Single-turn completion helper. Matches Week 1 notebook signature.

    Args:
        prompt          : The full prompt text.
        model           : Chat model to use.
        temperature     : 0.0 by default for deterministic outputs (W1 default).
        response_format : Optional dict, e.g. {"type": "json_object"} to force
                          the model to return valid JSON (useful for structured
                          downstream parsing — see recommender.py).
    """
    client = get_client()
    kwargs: dict = dict(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=temperature,
    )
    if response_format is not None:
        kwargs["response_format"] = response_format
    response = client.chat.completions.create(**kwargs)
    return response.choices[0].message.content or ""


def embed_batch(texts: list[str], model: str = DEFAULT_EMBED_MODEL) -> list[list[float]]:
    """Embed a list of strings; returns a list of float vectors in the same order.

    OpenAI accepts up to 2048 inputs per request; we let the caller batch
    if their list is bigger.
    """
    if not texts:
        return []
    if len(texts) > 2048:
        raise ValueError(
            f"OpenAI embeddings API limits to 2048 inputs per call; got {len(texts)}. "
            "Split into smaller batches."
        )
    client = get_client()
    response = client.embeddings.create(model=model, input=texts)
    # Preserve input order — OpenAI returns results in order with .index.
    return [d.embedding for d in sorted(response.data, key=lambda d: d.index)]
