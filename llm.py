"""Thin LLM helper module — single place every other module imports from.

Patterns follow the AI Bootcamp Week 1 + Week 2 notebooks (raw ``openai``
SDK, ``get_completion`` / ``get_completion_from_messages`` pair), with a
few production-friendly additions from Week 5 (secrets) and Week 2.7
(exception handling).

Public surface
--------------
- ``get_completion(prompt, model, temperature, top_p, max_tokens, n,
  response_format)``
      Single-string-prompt helper. Matches the Week 1 notebook signature
      and is what every existing module already calls.
- ``get_completion_from_messages(messages, model, temperature, top_p,
  max_tokens, n, response_format)``
      Messages-list helper for multi-turn / system+user role prompts.
      Matches the Week 2 Part 3 notebook signature. Use this for
      Decision Chains, Inner Monologue prompts with system messages,
      and any flow that benefits from few-shot exemplars in the
      messages array.
- ``embed_batch(texts, model)``
      Embeds a list of strings via OpenAI's embeddings API.
- ``num_tokens_from_message_rough(messages, model)``
      Quick tiktoken-based token count for a messages list. Useful when
      monitoring prompt size as chains grow (Week 2.6 performance note).
- ``get_secret(name)``
      Streamlit-Cloud-friendly secret accessor: tries ``st.secrets``
      first, falls back to ``os.environ`` (and therefore ``.env`` via
      python-dotenv).
"""

from __future__ import annotations

import os
from pathlib import Path

import tiktoken
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


# ---------------------------------------------------------------------------
# Secrets — unified accessor for Streamlit Cloud and local .env contexts.
# ---------------------------------------------------------------------------

def get_secret(name: str) -> str | None:
    """Return a secret value by name.

    Resolution order:
        1. ``st.secrets[name]`` if running inside a Streamlit app and the
           key exists there.
        2. ``os.environ[name]`` (populated from ``.env`` at import time).

    Returns ``None`` if neither has the key.

    Why this matters: when we eventually deploy to Streamlit Community
    Cloud (Topic 8.4), secrets live in the platform's secrets manager, not
    in ``.env``. Same code path works in both contexts.
    """
    try:
        import streamlit as st  # local import: optional dep at this layer
        # `st.secrets` raises if not in a Streamlit runtime, hence try/except.
        if hasattr(st, "secrets") and name in st.secrets:
            return st.secrets[name]
    except Exception:
        # Not in a Streamlit context, or st.secrets not configured.
        pass
    return os.environ.get(name)


# ---------------------------------------------------------------------------
# Client — lazily-initialised, shared across calls.
# ---------------------------------------------------------------------------

def get_client() -> OpenAI:
    """Return a lazily-initialised shared OpenAI client."""
    global _client
    if _client is None:
        api_key = get_secret("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError(
                "OPENAI_API_KEY not set. Add it to .env (local) or "
                "st.secrets (Streamlit Cloud)."
            )
        _client = OpenAI(api_key=api_key)
    return _client


# ---------------------------------------------------------------------------
# Chat completions — two parallel helpers matching the bootcamp pattern.
# ---------------------------------------------------------------------------

def get_completion(
    prompt: str,
    model: str = DEFAULT_CHAT_MODEL,
    temperature: float = 0.0,
    top_p: float = 1.0,
    max_tokens: int = 1024,
    n: int = 1,
    response_format: dict | None = None,
) -> str:
    """Single-prompt chat completion.

    Signature mirrors the Week 1 notebook ``get_completion``. ``temperature=0``
    is the bootcamp default for deterministic outputs.

    Args:
        prompt          : The full user-side prompt text.
        model           : Chat model to use (defaults to bootcamp's mini tier).
        temperature     : Sampling temperature. 0 = deterministic.
        top_p           : Nucleus sampling threshold.
        max_tokens      : Hard cap on the response length in tokens.
        n               : Number of completions to generate. Almost always 1.
        response_format : Optional dict, e.g. ``{"type": "json_object"}`` to
                          force valid JSON output (used by recommender.py).
    """
    client = get_client()
    kwargs: dict = dict(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=temperature,
        top_p=top_p,
        max_tokens=max_tokens,
        n=n,
    )
    if response_format is not None:
        kwargs["response_format"] = response_format
    response = client.chat.completions.create(**kwargs)
    return response.choices[0].message.content or ""


def get_completion_from_messages(
    messages: list[dict],
    model: str = DEFAULT_CHAT_MODEL,
    temperature: float = 0.0,
    top_p: float = 1.0,
    max_tokens: int = 1024,
    n: int = 1,
    response_format: dict | None = None,
) -> str:
    """Messages-list chat completion.

    Signature mirrors the Week 2 Part 3 notebook
    ``get_completion_from_messages``. Use this when your prompt benefits
    from explicit ``system`` + ``user`` + ``assistant`` role separation,
    such as:
      - Decision Chains (system prompt = classifier rules)
      - Inner Monologue prompts with step delimiters
      - Few-shot exemplars (alternating user/assistant pairs)

    Args:
        messages : A list of dicts shaped
                   ``[{"role": "system"|"user"|"assistant", "content": str}, ...]``
        (others same as :func:`get_completion`).
    """
    client = get_client()
    kwargs: dict = dict(
        model=model,
        messages=messages,
        temperature=temperature,
        top_p=top_p,
        max_tokens=max_tokens,
        n=n,
    )
    if response_format is not None:
        kwargs["response_format"] = response_format
    response = client.chat.completions.create(**kwargs)
    return response.choices[0].message.content or ""


# ---------------------------------------------------------------------------
# Embeddings.
# ---------------------------------------------------------------------------

def embed_batch(texts: list[str], model: str = DEFAULT_EMBED_MODEL) -> list[list[float]]:
    """Embed a list of strings; returns float vectors in the same order.

    OpenAI accepts up to 2048 inputs per request; we let the caller batch
    if their list is bigger.
    """
    if not texts:
        return []
    if len(texts) > 2048:
        raise ValueError(
            f"OpenAI embeddings API limits to 2048 inputs per call; "
            f"got {len(texts)}. Split into smaller batches."
        )
    client = get_client()
    response = client.embeddings.create(model=model, input=texts)
    # Preserve input order — OpenAI returns results in order with .index.
    return [d.embedding for d in sorted(response.data, key=lambda d: d.index)]


# ---------------------------------------------------------------------------
# Token counting (rough but useful for monitoring chain growth).
# ---------------------------------------------------------------------------

def num_tokens_from_message_rough(
    messages: list[dict],
    model: str = DEFAULT_CHAT_MODEL,
) -> int:
    """Approximate token count for a messages list.

    Mirrors the Week 2 Part 3 helper. Concatenates message contents and
    counts via tiktoken. This is a *rough* estimate that ignores
    role-token overhead and message-format tokens — good enough for
    monitoring whether a chain's prompt is growing dangerously large
    (Week 2.6 "performance" warning).

    For exact counts (rare), use ``tiktoken.encoding_for_model`` directly
    with OpenAI's documented per-role overhead.
    """
    try:
        encoding = tiktoken.encoding_for_model(model)
    except KeyError:
        # Fallback for newer models tiktoken hasn't indexed yet
        # (gpt-4.1-* uses the same o200k_base encoding as gpt-4o).
        encoding = tiktoken.get_encoding("o200k_base")
    value = " ".join(m.get("content", "") or "" for m in messages)
    return len(encoding.encode(value))
